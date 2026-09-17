"""CP3a: structured MCP evidence becomes private state and chat artifacts."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NotRequired
from uuid import uuid4

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from juena_core.agents.specialist_outcome import (
    ArtifactMessageMiddleware,
    ExecutionEvidenceMiddleware,
)
from juena_core.artifacts import (
    ARTIFACT_MESSAGE_KEY,
    ArtifactStore,
    set_artifact_store_for_tests,
)
from vitess_ai.mcp.connection import TOOL_NAMES
from vitess_ai.modules.catalog import execution_order
from vitess_ai.run import InternalSimulationRequest, VitessGateway, safe_run_file
from vitess_ai.state import VitessBridgeState
from vitess_ai.tools import (
    build_vitess_tools,
    plan_simulation,
    vitess_supervisor_middleware,
)

from doubles import (
    GRAPH_RUN_ID,
    SIMULATION_RUN_ID,
    THREAD_ID,
    configured_modules,
    named_tool,
    raw_tools,
    runtime,
    simulation_payload,
)


def _module_results() -> dict[str, dict[str, list[str]]]:
    """The gateway's own input: one argument list per module, nothing else.

    The gateway is below the façade and knows nothing about validated
    configurations -- 03/CP4's `_configured_arguments` is what turns one into
    the other, and it is tested where it lives.
    """
    return {name: {"cli_parameters": ["-a1"]} for name in execution_order()}


def _configured_state(project_root: Path) -> dict[str, Any]:
    """A conversation that has planned and configured every module.

    Both halves are what the real tools write: `plan_simulation` records the
    order and the five validation tools record the configurations.
    """
    return {
        "planned_execution_order": list(execution_order()),
        "module_results": configured_modules(project_root),
    }


def _request() -> InternalSimulationRequest:
    return InternalSimulationRequest(
        thread_id=THREAD_ID,
        simulation_run_id=SIMULATION_RUN_ID,
        graph_run_id=GRAPH_RUN_ID,
        module_results=_module_results(),
        execution_order=execution_order(),
    )


@pytest.fixture
def artifact_store(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts", tmp_path / "audit.jsonl")
    set_artifact_store_for_tests(store)
    yield store
    set_artifact_store_for_tests(None)


def test_valid_structured_content_becomes_one_event_per_module() -> None:
    tools = raw_tools()
    gateway = VitessGateway(tools)

    outcome = asyncio.run(gateway.run_simulation(_request()))

    assert outcome.success is True
    assert [event.command.split(":", 1)[0] for event in outcome.events] == list(
        execution_order()
    )
    assert {event.exit_code for event in outcome.events} == {0}
    raw_call = next(tool.calls[0] for tool in tools if tool.name == "run_simulation")
    assert raw_call["args"] == {
        "thread_id": THREAD_ID,
        "simulation_run_id": SIMULATION_RUN_ID,
        "module_results": _module_results(),
        "execution_order": list(execution_order()),
    }


@pytest.mark.parametrize(
    "artifact",
    [None, {}, {"structured_content": {"success": True}}, {"wrong": "channel"}],
)
def test_malformed_structured_content_is_a_failed_execution(artifact: Any) -> None:
    message = ToolMessage(
        content='{"success":true}',
        tool_call_id="raw-call",
        artifact=artifact,
    )
    gateway = VitessGateway(
        raw_tools(run_simulation=lambda _call: message)
    )

    outcome = asyncio.run(gateway.run_simulation(_request()))

    assert outcome.success is False
    assert outcome.result is None
    assert outcome.failure is not None
    assert outcome.failure.status == "tool_error"
    assert [event.status for event in outcome.events] == ["tool_error"]


def test_server_cannot_return_evidence_for_a_different_owner() -> None:
    gateway = VitessGateway(
        raw_tools(
            run_simulation=lambda _call: simulation_payload(
                thread_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
            )
        )
    )

    outcome = asyncio.run(gateway.run_simulation(_request()))

    assert outcome.failure is not None
    assert outcome.failure.status == "tool_error"
    assert "different thread_id" in outcome.failure.message


def test_a_partial_pipeline_failure_is_not_mislabelled_as_a_successful_retry() -> None:
    codes = (0, 0, 7, 0, 0)
    gateway = VitessGateway(
        raw_tools(
            run_simulation=lambda _call: simulation_payload(
                success=False,
                exit_codes=codes,
            )
        )
    )

    outcome = asyncio.run(gateway.run_simulation(_request()))

    assert outcome.success is False
    assert [(event.status, event.exit_code) for event in outcome.events] == [
        ("failed", 7)
    ]


def test_transport_failure_is_typed_and_bounded() -> None:
    gateway = VitessGateway(
        raw_tools(run_simulation=lambda _call: ConnectionError("down" * 2_000))
    )

    outcome = asyncio.run(gateway.run_simulation(_request()))

    assert outcome.failure is not None
    assert outcome.failure.status == "unavailable"
    assert len(outcome.failure.message) <= 2_000
    assert outcome.events[0].status == "unavailable"


def test_claimed_file_must_exist_with_the_claimed_size(tmp_path: Path) -> None:
    run_root = tmp_path / THREAD_ID / "outputs" / SIMULATION_RUN_ID
    run_root.mkdir(parents=True)
    path = run_root / "monitor1D.dat"
    path.write_text("measured", encoding="utf-8")

    descriptor = SimpleNamespace(path="monitor1D.dat", size_bytes=8)
    assert safe_run_file(
        tmp_path,
        thread_id=THREAD_ID,
        simulation_run_id=SIMULATION_RUN_ID,
        descriptor=descriptor,
    ) == path

    descriptor.size_bytes = 9
    with pytest.raises(ValueError, match="size mismatch"):
        safe_run_file(
            tmp_path,
            thread_id=THREAD_ID,
            simulation_run_id=SIMULATION_RUN_ID,
            descriptor=descriptor,
        )


@pytest.mark.parametrize("path", ["../secret.dat", "/etc/passwd", "nested/../../x"])
def test_claimed_file_path_cannot_escape_the_run(tmp_path: Path, path: str) -> None:
    descriptor = SimpleNamespace(path=path, size_bytes=1)
    with pytest.raises(ValueError, match="beneath|stay"):
        safe_run_file(
            tmp_path,
            thread_id=THREAD_ID,
            simulation_run_id=SIMULATION_RUN_ID,
            descriptor=descriptor,
        )


def test_symlink_to_another_thread_inside_the_volume_is_still_an_escape(
    tmp_path: Path,
) -> None:
    other_run = (
        tmp_path
        / "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        / "outputs"
        / SIMULATION_RUN_ID
    )
    other_run.mkdir(parents=True)
    (other_run / "monitor1D.dat").write_bytes(b"other user")
    thread_root = tmp_path / THREAD_ID
    thread_root.parent.mkdir(parents=True, exist_ok=True)
    thread_root.symlink_to(other_run.parents[1], target_is_directory=True)
    descriptor = SimpleNamespace(path="monitor1D.dat", size_bytes=10)

    with pytest.raises(ValueError, match="Thread directory must not be a symbolic link"):
        safe_run_file(
            tmp_path,
            thread_id=THREAD_ID,
            simulation_run_id=SIMULATION_RUN_ID,
            descriptor=descriptor,
        )


def test_facade_schemas_contain_only_model_authorised_arguments(tmp_path: Path) -> None:
    facade = build_vitess_tools(VitessGateway(raw_tools()), project_root=tmp_path)
    forbidden = {"thread_id", "simulation_run_id", "module_results", "run_specs"}

    assert {tool.name for tool in facade} == set(TOOL_NAMES)
    for tool in facade:
        schema = tool.args_schema.model_json_schema()
        assert "runtime" not in schema.get("properties", {})
        assert forbidden.isdisjoint(schema.get("properties", {}))
        assert schema["additionalProperties"] is False


def _runtime(*, state: dict[str, Any], tool_call_id: str = "facade-call") -> Any:
    return SimpleNamespace(
        execution_info=SimpleNamespace(thread_id=THREAD_ID, run_id=GRAPH_RUN_ID),
        context=SimpleNamespace(user_id="user-a", thread_id=THREAD_ID),
        state=state,
        tool_call_id=tool_call_id,
    )


def _tool(facade: list[Any], name: str) -> Any:
    return next(item for item in facade if item.name == name)


def _png() -> bytes:
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )


def test_facade_injects_ids_registers_files_and_updates_private_state(
    tmp_path: Path,
    artifact_store: ArtifactStore,
) -> None:
    def run(call: dict[str, Any]) -> dict[str, Any]:
        arguments = call["args"]
        run_root = (
            tmp_path
            / arguments["thread_id"]
            / "outputs"
            / arguments["simulation_run_id"]
        )
        run_root.mkdir(parents=True)
        data = b"server measurement\n"
        (run_root / "monitor1D.dat").write_bytes(data)
        return simulation_payload(
            thread_id=arguments["thread_id"],
            simulation_run_id=arguments["simulation_run_id"],
            files=[{"path": "monitor1D.dat", "kind": "data", "size_bytes": len(data)}],
        )

    raw = raw_tools(run_simulation=run)
    facade = build_vitess_tools(VitessGateway(raw), project_root=tmp_path)
    execute = named_tool(facade, "run_simulation")

    command = asyncio.run(
        execute.coroutine(
            runtime=runtime(state=_configured_state(tmp_path)),
            run_name="baseline",
        )
    )

    assert isinstance(command, Command)
    assert command.update["messages"][0].status == "success"
    assert len(command.update["execution_events"]) == len(execution_order())
    reference = command.update["simulation_runs"][0]
    assert reference["run_name"] == "baseline"
    assert reference["simulation_run_id"] not in execute.args

    raw_call = next(tool.calls[0] for tool in raw if tool.name == "run_simulation")
    assert raw_call["args"]["thread_id"] == THREAD_ID
    assert raw_call["args"]["simulation_run_id"] == reference["simulation_run_id"]
    # Derived from the stored configuration at execution time, never carried
    # in state and never authored by a model: the staged input file the
    # read-in specialist validated is on read-in's command line.
    assert any(
        argument.startswith("-A") and argument.endswith("/uploads/readin/beam.dat")
        for argument in raw_call["args"]["module_results"]["readin"]["cli_parameters"]
    )

    artifact_id = command.update["execution_events"][-1]["artifact_ids"][0]
    stored = artifact_store.get("user-a", artifact_id)
    assert stored is not None
    assert stored[0].filename == "monitor1D.dat"
    assert stored[1] == b"server measurement\n"


def test_claimed_but_absent_file_turns_success_into_tool_error(
    tmp_path: Path,
    artifact_store: ArtifactStore,
) -> None:
    def run(call: dict[str, Any]) -> dict[str, Any]:
        arguments = call["args"]
        return simulation_payload(
            thread_id=arguments["thread_id"],
            simulation_run_id=arguments["simulation_run_id"],
            files=[{"path": "missing.dat", "kind": "data", "size_bytes": 3}],
        )

    facade = build_vitess_tools(
        VitessGateway(raw_tools(run_simulation=run)), project_root=tmp_path
    )
    execute = named_tool(facade, "run_simulation")

    command = asyncio.run(
        execute.coroutine(
            runtime=runtime(state=_configured_state(tmp_path)),
            run_name="missing-output",
        )
    )

    assert command.update["messages"][0].status == "error"
    assert "absent file" in command.update["messages"][0].text
    assert command.update["execution_events"][0]["status"] == "tool_error"
    assert artifact_store.peek_result_refs("user-a", THREAD_ID) == []


def test_plot_uses_private_run_id_and_registers_png(
    tmp_path: Path,
    artifact_store: ArtifactStore,
) -> None:
    run_root = tmp_path / THREAD_ID / "outputs" / SIMULATION_RUN_ID
    run_root.mkdir(parents=True)
    content = _png()

    def plot(call: dict[str, Any]) -> dict[str, Any]:
        (run_root / "monitor1D.png").write_bytes(content)
        return {
            "kind": "monitor1d",
            "source": "monitor1D.dat",
            "path": "monitor1D.png",
            "size_bytes": len(content),
            "title": "Monitor 1D",
            "x_label": "Wavelength",
            "y_label": "Intensity",
            "message": "Rendered",
        }

    raw = raw_tools(generate_monitor1d_plot=plot)
    facade = build_vitess_tools(VitessGateway(raw), project_root=tmp_path)
    generate = named_tool(facade, "generate_monitor1d_plot")
    state = {
        "simulation_runs": [
            {"run_name": "baseline", "simulation_run_id": SIMULATION_RUN_ID}
        ]
    }

    message = asyncio.run(
        generate.coroutine(
            runtime=runtime(state=state),
            run_name="baseline",
            filename=None,
        )
    )

    assert message.status == "success"
    raw_call = next(tool.calls[0] for tool in raw if tool.name == "generate_monitor1d_plot")
    assert raw_call["args"]["simulation_run_id"] == SIMULATION_RUN_ID
    references = artifact_store.peek_result_refs("user-a", THREAD_ID)
    assert [reference.filename for reference in references] == ["monitor1D.png"]


class _ApplicationState(VitessBridgeState):
    module_results: NotRequired[dict[str, Any]]


@dataclass(frozen=True)
class _Context:
    user_id: str
    thread_id: str
    run_id: str


class _ToolModel(FakeMessagesListChatModel):
    def bind_tools(self, tools: Any, **kwargs: Any) -> _ToolModel:
        return self


def test_real_agent_writes_verified_block_and_attaches_artifact(
    tmp_path: Path,
    artifact_store: ArtifactStore,
) -> None:
    def run(call: dict[str, Any]) -> dict[str, Any]:
        arguments = call["args"]
        run_root = (
            tmp_path
            / arguments["thread_id"]
            / "outputs"
            / arguments["simulation_run_id"]
        )
        run_root.mkdir(parents=True)
        output = b"wavelength intensity\n"
        (run_root / "monitor1D.dat").write_bytes(output)
        return simulation_payload(
            thread_id=arguments["thread_id"],
            simulation_run_id=arguments["simulation_run_id"],
            files=[{"path": "monitor1D.dat", "kind": "data", "size_bytes": len(output)}],
        )

    facade = build_vitess_tools(
        VitessGateway(raw_tools(run_simulation=run)), project_root=tmp_path
    )
    model = _ToolModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "plan_simulation",
                        "args": {},
                        "id": "plan-call",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "run_simulation",
                        "args": {"run_name": "agent-run"},
                        "id": "model-call",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="The simulation finished."),
        ]
    )
    agent = create_agent(
        model=model,
        tools=[plan_simulation, *facade],
        middleware=vitess_supervisor_middleware(),
        state_schema=_ApplicationState,
        context_schema=_Context,
    )
    graph_run_id = uuid4()

    result = asyncio.run(
        agent.ainvoke(
            {
                "messages": [HumanMessage("Run it")],
                # Only `plan_simulation` can supply the order: the channel is
                # private, so it is not in the graph's input schema at all.
                "module_results": configured_modules(tmp_path),
            },
            {"configurable": {"thread_id": THREAD_ID}, "run_id": graph_run_id},
            context=_Context(
                user_id="user-a",
                thread_id=THREAD_ID,
                run_id=str(graph_run_id),
            ),
        )
    )

    final = result["messages"][-1]
    assert "<verified_by_server>" in final.text
    assert "Executions: 5" in final.text
    assert "completed (exit 0)" in final.text
    assert [
        item["filename"] for item in final.additional_kwargs[ARTIFACT_MESSAGE_KEY]
    ] == ["monitor1D.dat"]


def test_supervisor_middleware_contains_both_required_root_hooks() -> None:
    middleware = vitess_supervisor_middleware()

    assert [type(item) for item in middleware] == [
        ExecutionEvidenceMiddleware,
        ArtifactMessageMiddleware,
    ]
