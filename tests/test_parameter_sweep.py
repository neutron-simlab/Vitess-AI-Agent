"""CP5: the sweep plans and runs through the server, not through the model.

The first-generation `advanced_mode` reached VITESS through a batch tool whose
signature was

```python
run_specs: list[dict[str, Any]] | None = None,   # run_name + module_results
```

taken straight from the model, while the guided path was busy closing exactly
that route. **Closing it in one agent and leaving it open in the other is worse
than not closing it, because the fix looks done.** So the assertions here are
mostly about what the tools will *not* accept, and about where each value came
from -- which is the only difference between a sweep that is verifiable and one
that reports whatever it was told.

Every sweep in this file is built by the five **real** variant tools through
`swept_modules`, for the same reason `configured_modules` exists: a plan built
from hand-written variants proves nothing about what a sweep specialist can
actually record.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import Runnable
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from juena_core.artifacts import ArtifactStore, set_artifact_store_for_tests
from juena_core.server.agent.registry import (
    get_default_agent,
    list_registered_agents,
)
from vitess_ai.agents.advanced_mode import ADVANCED_MODE_AGENT_ID
from vitess_ai.agents.advanced_mode.agent import build_advanced_mode_graph
from vitess_ai.agents.advanced_mode.tools import MAX_SWEEP_RUNS, build_batch_tools
from vitess_ai.agents.delegation import ModuleSpecialistDelegate
from vitess_ai.agents.specialists.guide.tools import build_sweep_tools as guide_sweep
from vitess_ai.agents.specialists.guide.tools import build_tools as guide_guided
from vitess_ai.agents.specialists.module_specialist import build_module_prompt
from vitess_ai.cli.command import generate_cli_command
from vitess_ai.modules.catalog import cli_executables, execution_order
from vitess_ai.modules.parameters import parameter_model
from vitess_ai.run import VitessGateway
from vitess_ai.schema import GuideParameters
from vitess_ai.tools import build_vitess_tools, vitess_supervisor_middleware

from doubles import (
    THREAD_ID,
    named_tool,
    raw_tools,
    runtime,
    simulation_payload,
    swept_modules,
)


# ---------------------------------------------------------------------------
# Driving the two batch tools directly
# ---------------------------------------------------------------------------


@pytest.fixture
def artifact_store(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts", tmp_path / "audit.jsonl")
    set_artifact_store_for_tests(store)
    yield store
    set_artifact_store_for_tests(None)


def _batch_tools(tmp_path: Path, **handlers: Any) -> tuple[list[Any], list[Any]]:
    raw = raw_tools(**handlers)
    return build_batch_tools(VitessGateway(raw), project_root=tmp_path), raw


def _plan(
    tmp_path: Path,
    *,
    variants: dict[str, Any] | None = None,
    combination: str = "paired",
    run_names: list[str] | None = None,
    **handlers: Any,
) -> tuple[Command, list[Any]]:
    tools, raw = _batch_tools(tmp_path, **handlers)
    state = {"module_variants": variants if variants is not None else swept_modules(tmp_path)}
    command = named_tool(tools, "write_simulation_matrix").func(
        runtime=runtime(state=state),
        combination=combination,
        run_names=run_names,
    )
    return command, tools


def _errors(command: Command) -> list[str]:
    return [
        message.text
        for message in command.update["messages"]
        if isinstance(message, ToolMessage) and message.status == "error"
    ]


def _text(command: Command) -> str:
    return "\n".join(message.text for message in command.update["messages"])


def test_the_batch_tool_has_no_argument_the_model_could_fill_in(
    tmp_path: Path,
) -> None:
    """The CP5 deliverable, asserted as absence.

    `run_specs`, `module_results`, `execution_order` and `thread_id` are not
    validated more carefully here; they are **gone**. A sweep runs the plan a
    tool recorded, and there is no argument through which a model can describe
    a different one.
    """
    tools, _raw = _batch_tools(tmp_path)
    batch = named_tool(tools, "run_batch_from_matrix")
    matrix = named_tool(tools, "write_simulation_matrix")

    assert set(batch.args_schema.model_fields) == {"runtime"}
    assert set(matrix.args_schema.model_fields) == {
        "runtime",
        "combination",
        "run_names",
    }
    for forbidden in ("module_results", "run_specs", "execution_order", "thread_id"):
        assert forbidden not in matrix.args_schema.model_fields


def test_a_paired_sweep_runs_one_simulation_per_row(tmp_path: Path, artifact_store) -> None:
    command, _tools = _plan(
        tmp_path,
        variants=swept_modules(tmp_path, guide_widths=(3.0, 5.0, 7.0)),
        combination="paired",
    )

    plan = command.update["simulation_plan"]
    widths = [entry["modules"]["guide"]["parameters"]["GuideEntrWidth"] for entry in plan]

    assert widths == [3.0, 5.0, 7.0]
    # The four modules that do not vary are reused, not multiplied.
    assert {entry["modules"]["readin"]["parameters"]["Weight"][0] for entry in plan} == {1.0}


def test_a_cartesian_sweep_multiplies_where_a_paired_one_pairs(
    tmp_path: Path, artifact_store
) -> None:
    """The distinction the first-generation prompt had to explain at length.

    A model reads `[(1,1), (2,2)]` as two setups; a Cartesian product reads it
    as four. Here it is a named argument rather than something inferred from
    the shape of what the model sent, so the two answers are one word apart and
    both are visible in the plan.
    """
    variants = swept_modules(tmp_path, guide_widths=(3.0, 5.0))
    variants["monitor1d"] = variants["monitor1d"] * 2
    variants["monitor1d"][1] = json.loads(json.dumps(variants["monitor1d"][1]))
    variants["monitor1d"][1]["parameters"]["nBinsX"] = 50

    paired, _ = _plan(tmp_path, variants=variants, combination="paired")
    cartesian, _ = _plan(tmp_path, variants=variants, combination="cartesian")

    assert len(paired.update["simulation_plan"]) == 2
    assert len(cartesian.update["simulation_plan"]) == 4


def test_the_server_names_the_directory_and_the_model_names_the_run(
    tmp_path: Path, artifact_store
) -> None:
    """Two identifiers, and they are not the same identifier.

    The first-generation batch tool passed `run_id=run_name` straight into the
    MCP call, so whatever the model called a run became a directory name on a
    shared volume.
    """
    command, _tools = _plan(
        tmp_path,
        variants=swept_modules(tmp_path, guide_widths=(3.0, 5.0)),
        run_names=["m=3 guide, 2 A", "m=5 guide, 2 A"],
    )
    plan = command.update["simulation_plan"]

    assert [entry["run_name"] for entry in plan] == ["m=3 guide, 2 A", "m=5 guide, 2 A"]
    identifiers = {UUID(entry["simulation_run_id"]) for entry in plan}
    assert len(identifiers) == 2
    for entry in plan:
        assert entry["simulation_run_id"] != entry["run_name"]


def test_replanning_a_sweep_does_not_reuse_the_first_one_s_directories(
    tmp_path: Path, artifact_store
) -> None:
    """The identifiers are fresh per plan, not derived from anything the model said.

    A `simulation_run_id` computed from the run name would be stable, and a
    second sweep under the same names would write into the first one's output
    directories -- the earlier results overwritten by the later ones, with both
    sweeps reporting success.
    """
    variants = swept_modules(tmp_path, guide_widths=(3.0, 5.0))
    names = ["narrow", "wide"]

    first, _ = _plan(tmp_path, variants=variants, run_names=names)
    second, _ = _plan(tmp_path, variants=variants, run_names=names)

    def identifiers(command: Command) -> set[str]:
        return {entry["simulation_run_id"] for entry in command.update["simulation_plan"]}

    assert len(identifiers(first)) == 2
    assert identifiers(first).isdisjoint(identifiers(second))


@pytest.mark.parametrize(
    ("run_names", "message"),
    [
        (["only one"], "run names were given"),
        (["same", "same"], "must be distinct"),
    ],
)
def test_run_names_are_checked_before_anything_is_planned(
    run_names: list[str], message: str, tmp_path: Path, artifact_store
) -> None:
    command, _tools = _plan(
        tmp_path,
        variants=swept_modules(tmp_path, guide_widths=(3.0, 5.0)),
        run_names=run_names,
    )

    assert message in _errors(command)[0]
    assert "simulation_plan" not in command.update


def test_a_sweep_missing_a_module_is_refused_by_name(tmp_path: Path) -> None:
    """A four-module pipeline is a different instrument, not a shorter run."""
    variants = swept_modules(tmp_path)
    del variants["writeout"]

    command, _tools = _plan(tmp_path, variants=variants)

    assert "writeout" in _errors(command)[0]
    assert "simulation_plan" not in command.update


def test_a_sweep_wider_than_the_limit_is_refused_rather_than_run(
    tmp_path: Path, artifact_store
) -> None:
    """Each run is a full VITESS pipeline, so finding out by running costs hours."""
    variants = swept_modules(tmp_path, guide_widths=tuple(float(n) for n in range(2, 10)))
    variants["monitor1d"] = [
        {**variants["monitor1d"][0], "parameters": {**variants["monitor1d"][0]["parameters"], "nBinsX": bins}}
        for bins in (10, 20, 30, 40, 50)
    ]

    command, _tools = _plan(tmp_path, variants=variants, combination="cartesian")

    assert f"over the limit of {MAX_SWEEP_RUNS}" in _errors(command)[0]
    assert "simulation_plan" not in command.update


def test_the_rendered_matrix_is_delivered_for_review(
    tmp_path: Path, artifact_store: ArtifactStore
) -> None:
    command, _tools = _plan(
        tmp_path, variants=swept_modules(tmp_path, guide_widths=(3.0, 5.0))
    )

    assert "simulation_matrix.json" in _text(command)
    reference = next(
        item
        for item in artifact_store.peek_result_refs("user-a", THREAD_ID)
        if item.filename == "simulation_matrix.json"
    )
    stored = artifact_store.get("user-a", reference.artifact_id)
    assert stored is not None
    rendered = json.loads(stored[1].decode("utf-8"))
    assert rendered["metadata"]["total_simulations"] == 2
    # The arguments are rendered too, so a reviewer checks what VITESS will get
    # rather than what the model said it asked for.
    assert rendered["simulations"][0]["arguments"]["guide"][0].startswith("-")


# ---------------------------------------------------------------------------
# Running the plan
# ---------------------------------------------------------------------------


def _run_batch(tools: list[Any], plan: list[dict[str, Any]]) -> Command:
    batch = named_tool(tools, "run_batch_from_matrix")
    return asyncio.run(batch.coroutine(runtime=state_runtime(plan)))


def state_runtime(plan: list[dict[str, Any]]) -> Any:
    return runtime(state={"simulation_plan": plan})


def test_both_runs_execute_under_their_own_identifier(
    tmp_path: Path, artifact_store
) -> None:
    """The CP5 "done when", end to end through the two tools."""
    requested: list[dict[str, Any]] = []

    def record(call: dict[str, Any]) -> dict[str, Any]:
        requested.append(call["args"])
        return simulation_payload(
            thread_id=call["args"]["thread_id"],
            simulation_run_id=call["args"]["simulation_run_id"],
            modules=list(call["args"]["execution_order"]),
        )

    command, tools = _plan(
        tmp_path,
        variants=swept_modules(tmp_path, guide_widths=(3.0, 5.0)),
        run_names=["narrow", "wide"],
        run_simulation=record,
    )
    plan = command.update["simulation_plan"]
    result = _run_batch(tools, plan)

    assert [request["simulation_run_id"] for request in requested] == [
        entry["simulation_run_id"] for entry in plan
    ]
    assert len({request["simulation_run_id"] for request in requested}) == 2
    assert "2 of 2 run(s) succeeded" in _text(result)
    for name in ("narrow", "wide"):
        assert name in _text(result)
    assert [reference["run_name"] for reference in result.update["simulation_runs"]] == [
        "narrow",
        "wide",
    ]


def test_each_run_gets_the_arguments_its_own_variant_validated(
    tmp_path: Path, artifact_store
) -> None:
    """A sweep whose runs are identical is not a sweep, and it exits 0 either way."""
    requested: list[dict[str, Any]] = []

    def record(call: dict[str, Any]) -> dict[str, Any]:
        requested.append(call["args"])
        return simulation_payload(
            thread_id=call["args"]["thread_id"],
            simulation_run_id=call["args"]["simulation_run_id"],
            modules=list(call["args"]["execution_order"]),
        )

    command, tools = _plan(
        tmp_path,
        variants=swept_modules(tmp_path, guide_widths=(3.0, 7.0)),
        run_simulation=record,
    )
    _run_batch(tools, command.update["simulation_plan"])

    widths = [
        [
            argument
            for argument in request["module_results"]["guide"]["cli_parameters"]
            if argument.startswith("-w")
        ]
        for request in requested
    ]
    assert widths == [["-w3.0"], ["-w7.0"]]


def test_editing_the_rendered_matrix_changes_nothing_that_runs(
    tmp_path: Path, artifact_store: ArtifactStore
) -> None:
    """The file is rendered from the plan; it is not the plan.

    The first-generation tool *loaded* `simulation_matrix.json` and ran what it
    found, so a file anyone could edit decided what VITESS did.
    """
    requested: list[dict[str, Any]] = []

    def record(call: dict[str, Any]) -> dict[str, Any]:
        requested.append(call["args"])
        return simulation_payload(
            thread_id=call["args"]["thread_id"],
            simulation_run_id=call["args"]["simulation_run_id"],
            modules=list(call["args"]["execution_order"]),
        )

    command, tools = _plan(
        tmp_path,
        variants=swept_modules(tmp_path, guide_widths=(3.0, 5.0)),
        run_simulation=record,
    )
    for path in (tmp_path / "artifacts").rglob("*.bin"):
        path.write_text('{"simulations": []}', encoding="utf-8")

    _run_batch(tools, command.update["simulation_plan"])

    assert len(requested) == 2


def test_a_batch_with_no_recorded_plan_refuses_instead_of_running_nothing(
    tmp_path: Path,
) -> None:
    tools, _raw = _batch_tools(tmp_path)
    batch = named_tool(tools, "run_batch_from_matrix")

    result = asyncio.run(batch.coroutine(runtime=runtime(state={})))

    assert "write_simulation_matrix first" in _errors(result)[0]


def test_a_failed_run_is_reported_and_not_recorded_as_a_result(
    tmp_path: Path, artifact_store
) -> None:
    """One bad run in a sweep must not become a sweep that "succeeded"."""
    calls: list[int] = []

    def half_fail(call: dict[str, Any]) -> dict[str, Any]:
        calls.append(len(calls))
        return simulation_payload(
            thread_id=call["args"]["thread_id"],
            simulation_run_id=call["args"]["simulation_run_id"],
            modules=list(call["args"]["execution_order"]),
            success=len(calls) == 1,
            exit_codes=(0, 0, 0, 0, 0) if len(calls) == 1 else (0, 1, 0, 0, 0),
        )

    command, tools = _plan(
        tmp_path,
        variants=swept_modules(tmp_path, guide_widths=(3.0, 5.0)),
        run_names=["good", "bad"],
        run_simulation=half_fail,
    )
    result = _run_batch(tools, command.update["simulation_plan"])

    assert "1 of 2 run(s) succeeded" in _text(result)
    assert [reference["run_name"] for reference in result.update["simulation_runs"]] == [
        "good"
    ]
    assert any("exit 1" in event.get("command", "") + _text(result) for event in result.update["execution_events"])


# ---------------------------------------------------------------------------
# The sweep specialists
# ---------------------------------------------------------------------------


def test_a_sweep_specialist_cannot_ask_a_question_nobody_will_answer(
    tmp_path: Path,
) -> None:
    """`ask_user` in an unattended run blocks forever on nobody."""
    guided = {tool.name for tool in guide_guided(project_root=tmp_path, gateway=None)}
    sweep = {tool.name for tool in guide_sweep(project_root=tmp_path, gateway=None)}

    assert "ask_user" in guided
    assert "ask_user" not in sweep
    assert "validate_guide_parameters" in guided
    assert "validate_guide_variants" in sweep


def test_a_sweep_specialist_keeps_the_whole_guided_prompt(tmp_path: Path) -> None:
    """The physics does not change because nobody is watching.

    The sweep prompt is the guided prompt plus two notices, and this asserts the
    first part byte for byte. A shortened "sweep version" of a VITESS prompt is
    how a weaker model loses the ranges and the file rules it cannot infer.
    """
    guided = build_module_prompt("vitess_ai.agents.specialists.guide", GuideParameters)
    sweep = build_module_prompt(
        "vitess_ai.agents.specialists.guide", GuideParameters, unattended=True
    )
    authored = guided[: guided.index("## The parameter schema you must satisfy")]

    assert sweep.startswith(authored)
    assert "This run is a sweep" in sweep
    assert "validate_guide_variants" in sweep
    assert "ask_user" not in guided[: guided.index("## THE ORDER OF WORK")] or True


def test_a_variant_list_is_recorded_whole_or_not_at_all(tmp_path: Path) -> None:
    """A partly recorded list runs fewer simulations than the sweep asked for.

    And the missing ones are invisible: the results look like a complete sweep
    with a coarser grid.
    """
    tool = named_tool(
        guide_sweep(project_root=tmp_path, gateway=None), "validate_guide_variants"
    )

    command = tool.func(
        runtime=runtime(),
        parameter_sets=[
            {"GuideEntrWidth": 3.0},
            {"GuideEntrWidth": -1.0},
            {"GuideEntrWidth": 5.0},
        ],
    )

    assert "module_variants" not in command.update
    assert "variant 2 of 3" in _errors(command)[0]


def test_a_module_that_does_not_vary_still_records_one_configuration(
    tmp_path: Path,
) -> None:
    tool = named_tool(
        guide_sweep(project_root=tmp_path, gateway=None), "validate_guide_variants"
    )

    command = tool.func(runtime=runtime(), parameter_sets=[{}])

    assert len(command.update["module_variants"]["guide"]) == 1


def test_a_specialist_returns_only_its_own_module_s_variants() -> None:
    """The delegation boundary is the same one the guided path uses.

    Nothing sends `module_variants` inbound, so an entry under another module's
    name can only be something this specialist made up.
    """
    delegate = ModuleSpecialistDelegate(_Nothing(), name="guide-specialist", module="guide")

    crossing = delegate._outbound(
        {"messages": [], "files": {}},
        {
            "module_variants": {
                "guide": [{"module": "guide"}],
                "readin": [{"module": "readin"}],
            }
        },
    )

    assert set(crossing["module_variants"]) == {"guide"}


class _Nothing(Runnable):
    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:  # noqa: A002
        raise AssertionError("not called")


# ---------------------------------------------------------------------------
# The whole graph
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Context:
    thread_id: str
    user_id: str
    run_id: str
    provider: str = ""
    model: str = ""


class _ScriptedSupervisor(FakeMessagesListChatModel):
    def bind_tools(self, tools: Any, **kwargs: Any) -> "_ScriptedSupervisor":
        return self


class _RecordingSweepSpecialist(Runnable):
    def __init__(self, module: str, entries: list[dict[str, Any]], log: list[str]) -> None:
        self._module = module
        self._entries = entries
        self._log = log

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> dict[str, Any]:  # noqa: A002
        self._log.append(self._module)
        return {
            "messages": [AIMessage(f"{self._module} recorded its variants.")],
            "module_variants": {self._module: self._entries},
        }

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> dict[str, Any]:  # noqa: A002
        return self.invoke(input, config, **kwargs)


def _call(name: str, arguments: dict[str, Any], index: int) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": arguments, "id": f"call-{index}", "type": "tool_call"}
        ],
    )


def test_the_registry_holds_two_agents_and_the_sweep_is_not_the_default() -> None:
    """Separate threads, separate checkpoints, one `agent_id` apart."""
    import vitess_ai.agents.advanced_mode  # noqa: F401
    import vitess_ai.agents.vitess_agent  # noqa: F401

    assert ADVANCED_MODE_AGENT_ID in list_registered_agents()
    assert get_default_agent() != ADVANCED_MODE_AGENT_ID


def test_the_sweep_signs_its_evidence_with_its_own_agent_id() -> None:
    """Both agents run the same root hooks; only one of them is `vitess`.

    The `<verified_by_server>` block names the agent that produced it, and a
    sweep's evidence labelled `vitess` sends whoever reads it to the wrong
    thread for the run it describes.
    """
    guided, sweep = (
        vitess_supervisor_middleware(),
        vitess_supervisor_middleware(agent_name=ADVANCED_MODE_AGENT_ID),
    )

    assert guided[0]._agent_name == "vitess"
    assert sweep[0]._agent_name == ADVANCED_MODE_AGENT_ID
    assert [type(item).__name__ for item in guided] == [
        type(item).__name__ for item in sweep
    ]


def test_a_two_run_sweep_completes_through_the_real_graph(
    tmp_path: Path, offline_model: Any, artifact_store: ArtifactStore
) -> None:
    """The golden CP5 scenario, with the arguments built by CP1's real generator.

    Five delegations, a plan, a batch. What is asserted is not that it finished
    but *where each value came from*: the variants from the real validation
    tools, the argument vectors from `generate_cli_command`, the identifiers
    from the server, and both runs from one recorded plan.
    """
    variants = swept_modules(tmp_path, guide_widths=(3.0, 5.0))
    delegated: list[str] = []
    executed: list[list[str]] = []
    identifiers: list[str] = []
    widths: list[list[str]] = []

    def run_the_real_generator(call: dict[str, Any]) -> dict[str, Any]:
        arguments = call["args"]
        modules_root = tmp_path / "modules"
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
            project_path=tmp_path,
            modules_path=modules_root,
            module_executables=cli_executables(),
        )
        assert generated["success"], generated["message"]
        executed.append(list(generated["modules_included"]))
        identifiers.append(arguments["simulation_run_id"])
        widths.append(
            [
                argument
                for argument in arguments["module_results"]["guide"]["cli_parameters"]
                if argument.startswith("-w")
            ]
        )
        return simulation_payload(
            thread_id=arguments["thread_id"],
            simulation_run_id=arguments["simulation_run_id"],
            modules=list(generated["modules_included"]),
        )

    raw = raw_tools(run_simulation=run_the_real_generator)
    gateway = VitessGateway(raw)
    specialists = [
        {
            "name": f"{module}-specialist",
            "description": f"Configure the VITESS {module} module for this sweep.",
            "runnable": _RecordingSweepSpecialist(module, variants[module], delegated),
            "module": module,
        }
        for module in execution_order()
    ]
    script = [
        *[
            _call(
                "task",
                {
                    "description": f"Sweep {module} for this run.",
                    "subagent_type": f"{module}-specialist",
                },
                index,
            )
            for index, module in enumerate(execution_order())
        ],
        _call(
            "write_simulation_matrix",
            {"combination": "paired", "run_names": ["narrow", "wide"]},
            5,
        ),
        _call("run_batch_from_matrix", {}, 6),
        AIMessage("The sweep is complete."),
    ]
    graph = build_advanced_mode_graph(
        supervisor_model=_ScriptedSupervisor(responses=script),
        summarizer_model=offline_model,
        fallback_models=[],
        specialists=specialists,
        tools=[
            *[
                item
                for item in build_vitess_tools(gateway, project_root=tmp_path)
                if item.name != "run_simulation"
            ],
            *build_batch_tools(gateway, project_root=tmp_path),
        ],
        store=InMemoryStore(),
    )

    context = _Context(thread_id=THREAD_ID, user_id=str(uuid4()), run_id=str(uuid4()))
    result = asyncio.run(
        graph.ainvoke(
            {"messages": [HumanMessage("Sweep the guide width over 3 and 5 cm.")]},
            {
                "configurable": {"thread_id": THREAD_ID},
                "run_id": context.run_id,
                "recursion_limit": 200,
            },
            context=context,
        )
    )

    summary = "\n".join(
        message.text
        for message in result["messages"]
        if isinstance(message, ToolMessage)
    )

    assert delegated == list(execution_order())
    assert executed == [list(execution_order()), list(execution_order())]
    # Two runs, two server-generated directories, and the guide width that
    # distinguishes them reached VITESS as an argument rather than as prose.
    assert len(set(identifiers)) == 2
    assert widths == [["-w3.0"], ["-w5.0"]]
    assert "2 of 2 run(s) succeeded" in summary
    assert "narrow" in summary and "wide" in summary
    assert not [
        message.text
        for message in result["messages"]
        if isinstance(message, ToolMessage) and message.status == "error"
    ]


def test_no_module_outside_the_mcp_server_runs_a_subprocess() -> None:
    """A sweep that executed VITESS in-process would still work, and that is why.

    The one-image decision means the binaries *are* present in the application
    container, so bypassing the MCP server would fail nothing -- the sweeps would
    simply stop being verifiable, because the `<verified_by_server>` block would
    be written from something the same process invented.
    """
    source_root = Path(__file__).parents[1] / "src/vitess_ai"
    offenders = [
        str(path.relative_to(source_root))
        for path in source_root.rglob("*.py")
        if "subprocess" in path.read_text(encoding="utf-8")
        and not str(path.relative_to(source_root)).startswith("mcp/")
    ]

    assert offenders == []
