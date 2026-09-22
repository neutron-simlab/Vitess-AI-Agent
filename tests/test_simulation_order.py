"""CP4: the rebuilt supervisor holds the execution order, and proves it.

The hand-rolled graph the rebuild replaces held the pipeline order in its
edges. Losing that was the one way this rebuild could produce something worse
than what it replaced: a supervisor that configures the monitor before the
guide runs a simulation that completes, reports success, and is physically
wrong.

**A completeness check is not an order check.** Asserting that all five modules
have configurations proves the set, not the sequence; a supervisor that
configured the monitor first and the guide last passes it. So this file runs
the real graph and records three orders:

1. the order `plan_simulation` returned;
2. the order specialists were actually delegated to;
3. the order the modules appear in for execution.

Three lists, compared element by element. Nothing weaker demonstrates it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import Runnable
from langgraph.store.memory import InMemoryStore

from juena_core.artifacts import ArtifactStore, set_artifact_store_for_tests
from juena_core.server.agent.registry import list_registered_agents
from vitess_ai.agents import vitess_agent as agent_module
from vitess_ai.agents.vitess_agent import VITESS_AGENT_ID, build_vitess_graph
from vitess_ai.cli.command import generate_cli_command
from vitess_ai.modules.catalog import cli_executables, execution_order
from vitess_ai.run import VitessGateway
from vitess_ai.tools import build_vitess_tools, plan_simulation

from doubles import THREAD_ID, configured_modules, raw_tools, simulation_payload


@dataclass(frozen=True)
class _Context:
    """The trusted runtime context, with model selection deliberately empty.

    `RuntimeModelMiddleware` swaps the request model whenever the context names
    a provider and a model, which would replace the scripted model with a real
    one and put this test on the network.
    """

    thread_id: str
    user_id: str
    run_id: str
    provider: str = ""
    model: str = ""


class _ScriptedSupervisor(FakeMessagesListChatModel):
    """Plays a fixed sequence of tool calls; `bind_tools` is a no-op."""

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_ScriptedSupervisor":
        return self


class _RecordingSpecialist(Runnable):
    """A specialist that records being called and returns a real configuration."""

    def __init__(self, module: str, entry: dict[str, Any], log: list[str]) -> None:
        self._module = module
        self._entry = entry
        self._log = log

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> dict[str, Any]:  # noqa: A002
        self._log.append(self._module)
        return {
            "messages": [AIMessage(f"{self._module} is configured.")],
            "module_results": {self._module: self._entry},
        }

    async def ainvoke(
        self, input: Any, config: Any = None, **kwargs: Any  # noqa: A002
    ) -> dict[str, Any]:
        return self.invoke(input, config, **kwargs)


def _call(name: str, arguments: dict[str, Any], index: int) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": arguments, "id": f"call-{index}", "type": "tool_call"}
        ],
    )


def _delegations(modules: list[str], start: int = 1) -> list[AIMessage]:
    return [
        _call(
            "task",
            {
                "description": f"Configure {module} for this simulation.",
                "subagent_type": f"{module}-specialist",
            },
            index,
        )
        for index, module in enumerate(modules, start=start)
    ]


class _Harness:
    """One real supervisor graph, with everything it touched recorded."""

    def __init__(
        self,
        tmp_path: Path,
        offline_model: Any,
        script: list[AIMessage],
        *,
        specialist_modules: list[str] | None = None,
        extra_entries: dict[str, Any] | None = None,
    ) -> None:
        self.project_root = tmp_path
        self.delegated: list[str] = []
        self.entries = {**configured_modules(tmp_path), **(extra_entries or {})}
        self.raw = raw_tools(run_simulation=self._run_the_real_generator)
        self.executed: list[list[str]] = []
        self.argument_vectors: list[list[str]] = []

        modules = specialist_modules or list(execution_order())
        specialists = [
            {
                "name": f"{module}-specialist",
                "description": f"Configure the VITESS {module} module.",
                "runnable": _RecordingSpecialist(
                    module, self.entries[module], self.delegated
                ),
                "module": module,
            }
            for module in modules
        ]
        gateway = VitessGateway(self.raw)
        self.graph = build_vitess_graph(
            supervisor_model=_ScriptedSupervisor(responses=script),
            summarizer_model=offline_model,
            fallback_models=[],
            specialists=specialists,
            tools=[
                plan_simulation,
                *build_vitess_tools(gateway, project_root=tmp_path),
            ],
            store=InMemoryStore(),
        )

    def _run_the_real_generator(self, call: dict[str, Any]) -> dict[str, Any]:
        """Stand in for the MCP server by running CP1's real command builder.

        The third order has to come from the argument vectors that would
        actually be executed, not from the request. So the double builds them
        with `generate_cli_command`, against stub executables, exactly as
        `vitess_ai.mcp.server.run_pipeline` does.
        """
        arguments = call["args"]
        modules_root = self.project_root / "modules"
        modules_root.mkdir(exist_ok=True)
        for basename in cli_executables().values():
            binary = modules_root / basename
            if not binary.exists():
                binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                binary.chmod(0o755)

        generated = generate_cli_command(
            arguments["module_results"],
            arguments["execution_order"],
            thread_id=arguments["thread_id"],
            simulation_run_id=arguments["simulation_run_id"],
            project_path=self.project_root,
            modules_path=modules_root,
            module_executables=cli_executables(),
        )
        assert generated["success"], generated["message"]
        self.executed.append(list(generated["modules_included"]))
        self.argument_vectors = generated["argument_vectors"]
        return simulation_payload(
            thread_id=arguments["thread_id"],
            simulation_run_id=arguments["simulation_run_id"],
            modules=list(generated["modules_included"]),
        )

    def run(self) -> dict[str, Any]:
        context = _Context(
            thread_id=THREAD_ID, user_id=str(uuid4()), run_id=str(uuid4())
        )
        return asyncio.run(
            self.graph.ainvoke(
                {"messages": [HumanMessage("Run a VITESS simulation.")]},
                {
                    "configurable": {"thread_id": THREAD_ID},
                    "run_id": context.run_id,
                },
                context=context,
            )
        )

    @staticmethod
    def planned(result: dict[str, Any]) -> list[str]:
        """The order `plan_simulation` told the supervisor, read from its reply."""
        for message in result["messages"]:
            if isinstance(message, ToolMessage) and "in this order:" in message.text:
                listed = message.text.split("in this order:")[1].split(".")[0]
                return [module.strip() for module in listed.split("->")]
        raise AssertionError("plan_simulation never answered")

    @staticmethod
    def tool_errors(result: dict[str, Any]) -> list[str]:
        return [
            message.text
            for message in result["messages"]
            if isinstance(message, ToolMessage) and message.status == "error"
        ]


@pytest.fixture
def artifact_store(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts", tmp_path / "audit.jsonl")
    set_artifact_store_for_tests(store)
    yield store
    set_artifact_store_for_tests(None)


def test_the_planned_the_delegated_and_the_executed_orders_agree(
    tmp_path: Path, offline_model: Any, artifact_store: ArtifactStore
) -> None:
    """The golden test. Three orders, recorded separately, compared."""
    script = [
        _call("plan_simulation", {}, 0),
        *_delegations(list(execution_order())),
        _call("run_simulation", {"run_name": "golden"}, 9),
        AIMessage(content="The simulation is finished."),
    ]
    harness = _Harness(tmp_path, offline_model, script)

    result = harness.run()

    planned = harness.planned(result)
    assert planned == list(execution_order())
    assert harness.delegated == planned
    assert harness.executed == [planned]
    # And the fourth list, which is what actually runs: one argument vector per
    # module, each starting with that module's own executable.
    assert [Path(vector[0]).name for vector in harness.argument_vectors] == [
        cli_executables()[module] for module in planned
    ]
    assert harness.tool_errors(result) == []
    assert "<verified_by_server>" in result["messages"][-1].text
    assert f"Executions: {len(execution_order())}" in result["messages"][-1].text


def test_the_executed_arguments_are_the_ones_the_specialists_validated(
    tmp_path: Path, offline_model: Any, artifact_store: ArtifactStore
) -> None:
    """Nothing between validation and execution may edit the numbers.

    The read-in vector must carry the staged input file the read-in validation
    tool accepted -- a path no model ever typed into a tool call.
    """
    script = [
        _call("plan_simulation", {}, 0),
        *_delegations(list(execution_order())),
        _call("run_simulation", {"run_name": "golden"}, 9),
        AIMessage(content="Done."),
    ]
    harness = _Harness(tmp_path, offline_model, script)

    harness.run()

    readin_vector = harness.argument_vectors[0]
    staged = str(tmp_path / THREAD_ID / "uploads" / "readin" / "beam.dat")
    assert f"-A{staged}" in readin_vector


def test_a_simulation_that_was_never_planned_is_refused(
    tmp_path: Path, offline_model: Any, artifact_store: ArtifactStore
) -> None:
    """Fail closed. Without this the plan would be decorative."""
    script = [
        *_delegations(list(execution_order()), start=0),
        _call("run_simulation", {"run_name": "unplanned"}, 9),
        AIMessage(content="Done."),
    ]
    harness = _Harness(tmp_path, offline_model, script)

    result = harness.run()

    assert harness.executed == []
    assert any(
        "has no plan" in error for error in harness.tool_errors(result)
    ), harness.tool_errors(result)


def test_a_plan_called_after_delegation_does_not_retroactively_order_it(
    tmp_path: Path, offline_model: Any, artifact_store: ArtifactStore
) -> None:
    script = [
        *_delegations(list(execution_order()), start=0),
        _call("plan_simulation", {}, 6),
        _call("run_simulation", {"run_name": "late-plan"}, 7),
        AIMessage(content="Done."),
    ]
    harness = _Harness(tmp_path, offline_model, script)

    result = harness.run()

    assert harness.executed == []
    assert any("after the latest plan" in error for error in harness.tool_errors(result))


def test_a_missing_module_stops_the_pipeline_and_names_it(
    tmp_path: Path, offline_model: Any, artifact_store: ArtifactStore
) -> None:
    """Four of five is not a shorter pipeline; it is a different experiment."""
    delegated = [module for module in execution_order() if module != "guide"]
    script = [
        _call("plan_simulation", {}, 0),
        *_delegations(delegated),
        _call("run_simulation", {"run_name": "incomplete"}, 9),
        AIMessage(content="Done."),
    ]
    harness = _Harness(tmp_path, offline_model, script)

    result = harness.run()

    assert harness.executed == []
    errors = harness.tool_errors(result)
    assert any("guide" in error for error in errors), errors


def test_delegating_all_modules_out_of_order_is_refused(
    tmp_path: Path, offline_model: Any, artifact_store: ArtifactStore
) -> None:
    """Completeness is a set check; this pins the separate sequence check."""
    reversed_order = list(reversed(execution_order()))
    script = [
        _call("plan_simulation", {}, 0),
        *_delegations(reversed_order),
        _call("run_simulation", {"run_name": "reversed"}, 9),
        AIMessage(content="Done."),
    ]
    harness = _Harness(tmp_path, offline_model, script)

    result = harness.run()

    assert harness.delegated == reversed_order
    assert harness.executed == []
    assert any("configured in order" in error for error in harness.tool_errors(result))


def test_delegating_the_same_module_twice_replaces_only_its_own_entry(
    tmp_path: Path, offline_model: Any, artifact_store: ArtifactStore
) -> None:
    """Going back to change one module is normal, and must not undo the rest."""
    repeated = [*execution_order(), "guide"]
    script = [
        _call("plan_simulation", {}, 0),
        *_delegations(repeated),
        _call("run_simulation", {"run_name": "revised"}, 9),
        AIMessage(content="Done."),
    ]
    harness = _Harness(tmp_path, offline_model, script)

    result = harness.run()

    assert harness.delegated == repeated
    assert harness.executed == [list(execution_order())]
    assert harness.tool_errors(result) == []


def test_a_configuration_for_an_unplanned_module_is_refused(
    tmp_path: Path, offline_model: Any, artifact_store: ArtifactStore
) -> None:
    """A sixth specialist's configuration must not ride along unexecuted."""
    script = [
        _call("plan_simulation", {}, 0),
        *_delegations([*execution_order(), "instrument"]),
        _call("run_simulation", {"run_name": "extra"}, 9),
        AIMessage(content="Done."),
    ]
    harness = _Harness(
        tmp_path,
        offline_model,
        script,
        specialist_modules=[*execution_order(), "instrument"],
        # `instrument` runs no binary, so it has no parameter model and no
        # validation tool. This "configuration" is one a specialist could only
        # have invented, which is the case being refused.
        extra_entries={
            "instrument": {
                "module": "instrument",
                "validated_at": "2026-09-17T00:00:00+00:00",
                "parameters": {},
                "schema_version": "invented",
            }
        },
    )

    result = harness.run()

    assert harness.executed == []
    errors = harness.tool_errors(result)
    assert any("belong to no planned module" in error for error in errors), errors


def test_a_configuration_from_an_older_schema_is_refused(
    tmp_path: Path, offline_model: Any, artifact_store: ArtifactStore
) -> None:
    configured = configured_modules(tmp_path)
    stale_guide = {**configured["guide"], "schema_version": "old-schema"}
    script = [
        _call("plan_simulation", {}, 0),
        *_delegations(list(execution_order())),
        _call("run_simulation", {"run_name": "stale"}, 9),
        AIMessage(content="Done."),
    ]
    harness = _Harness(
        tmp_path,
        offline_model,
        script,
        extra_entries={"guide": stale_guide},
    )

    result = harness.run()

    assert harness.executed == []
    assert any("schema has changed" in error for error in harness.tool_errors(result))


def test_importing_the_agent_module_registers_exactly_the_vitess_agent() -> None:
    """Without the registration line every route 404s, silently."""
    import vitess_ai.agents.vitess_agent  # noqa: F401

    assert VITESS_AGENT_ID in list_registered_agents()


def test_the_guided_factory_passes_the_gateway_to_the_facade_builder(
    tmp_path: Path, configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default agent used `gateway.raw_tools`, an attribute that never existed.

    Graph tests all supplied hand-built façade tools, so 417 tests passed while
    opening the first guided conversation raised `AttributeError` in its
    factory. This test reaches the factory and inspects its actual base tools.
    """
    captured: dict[str, Any] = {}

    async def no_health() -> None:
        return None

    async def discovered() -> list[Any]:
        return raw_tools()

    monkeypatch.setattr(agent_module, "probe_server_health", no_health)
    monkeypatch.setattr(agent_module, "discover_vitess_tools", discovered)
    monkeypatch.setattr(agent_module, "get_store", lambda: InMemoryStore())
    monkeypatch.setattr(agent_module, "get_checkpointer", lambda: None)
    monkeypatch.setattr(agent_module, "compile_module_specialists", lambda **_: [])
    monkeypatch.setattr(agent_module, "project_root", lambda: tmp_path)

    def capture(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(agent_module, "build_vitess_graph", capture)

    asyncio.run(
        agent_module.create_vitess_agent(
            provider="blablador", model=configured.DEFAULT_MODEL
        )
    )

    assert [item.name for item in captured["tools"]] == [
        "ask_user",
        "plan_simulation",
        "run_simulation",
        "inspect_thread_folders",
        "generate_monitor1d_plot",
        "generate_monitor2d_plot",
    ]


def test_the_guided_graph_adds_documentation_tools_and_the_matching_policy(
    offline_model: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Direct graph construction must exercise the RAG boundary the factory uses."""
    captured: dict[str, Any] = {}

    from langchain_core.tools import tool

    @tool("documentation_probe", description="A documentation test tool.")
    def documentation_probe(query: str) -> str:
        return query

    def documentation(*, unattended: bool) -> tuple[list[Any], str]:
        captured["unattended"] = unattended
        return [documentation_probe], "GUIDED_DOCUMENTATION_POLICY"

    class _Graph:
        def with_config(self, config: dict[str, Any]) -> "_Graph":
            captured["config"] = config
            return self

    def capture_agent(**kwargs: Any) -> _Graph:
        captured.update(kwargs)
        return _Graph()

    monkeypatch.setattr(agent_module, "orchestrator_documentation", documentation)
    monkeypatch.setattr(agent_module, "create_agent", capture_agent)

    agent_module.build_vitess_graph(
        supervisor_model=_ScriptedSupervisor(responses=[AIMessage("done")]),
        summarizer_model=offline_model,
        fallback_models=[],
        specialists=[
            {
                "name": "guide-specialist",
                "description": "Configure the guide.",
                "runnable": _RecordingSpecialist("guide", {}, []),
                "module": "guide",
            }
        ],
        tools=[],
        store=InMemoryStore(),
    )

    assert captured["unattended"] is False
    assert [item.name for item in captured["tools"]] == ["documentation_probe"]
    assert str(captured["system_prompt"]).endswith("GUIDED_DOCUMENTATION_POLICY")


def test_supervisor_markdown_names_every_production_tool() -> None:
    """A weaker model cannot discover a capability the prompt never names."""
    prompt = (
        Path(__file__).parents[1] / "src/vitess_ai/agents/SUPERVISOR.md"
    ).read_text(encoding="utf-8")
    expected = {
        "ask_user",
        "plan_simulation",
        "task",
        "run_simulation",
        "inspect_thread_folders",
        "generate_monitor1d_plot",
        "generate_monitor2d_plot",
        "vitess_search",
        "vitess_option_lookup",
        "vitess_module_lookup",
        "vitess_debug_retrieval",
        "read_file",
        "write_file",
        "edit_file",
        "ls",
        "glob",
        "grep",
    }

    for name in expected:
        assert f"`{name}`" in prompt
    assert "There is no `execute` and no `delete`." in prompt
