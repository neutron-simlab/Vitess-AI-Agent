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
from langchain_core.tools import tool
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command
from pydantic import TypeAdapter

from juena_core.artifacts import ArtifactStore, set_artifact_store_for_tests
from juena_core.server.agent.registry import (
    get_default_agent,
    list_registered_agents,
)
from vitess_ai.agents.advanced_mode import ADVANCED_MODE_AGENT_ID
from vitess_ai.agents.advanced_mode import agent as agent_module
from vitess_ai.agents.advanced_mode.agent import (
    _ADVANCED_FACADE_TOOL_NAMES,
    _advanced_facade_tools,
    build_advanced_mode_graph,
)
from vitess_ai.agents.advanced_mode.tools import (
    MAX_SWEEP_RUNS,
    build_batch_tools,
    describe_module_parameters,
)
from vitess_ai.agents.delegation import ModuleSpecialistDelegate
from vitess_ai.agents.vitess_agent import VITESS_FILESYSTEM_TOOLS
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
        (["same", " same "], "must be distinct"),
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


def test_a_guide_sweep_gets_exact_monitor_and_writeout_defaults(
    tmp_path: Path, artifact_store
) -> None:
    """Untouched modules are filled by code, not by model-authored JSON."""
    variants = swept_modules(tmp_path, guide_widths=(3.0, 1.0))
    for module in ("writeout", "monitor1d", "monitor2d"):
        del variants[module]

    command, _tools = _plan(tmp_path, variants=variants)

    assert not _errors(command)
    plan = command.update["simulation_plan"]
    assert len(plan) == 2
    for entry in plan:
        for module in ("writeout", "monitor1d", "monitor2d"):
            assert entry["modules"][module]["parameters"] == parameter_model(
                module
            )().model_dump(mode="json")
        assert entry["modules"]["monitor2d"]["parameters"]["xParam"] == 1
        assert entry["modules"]["monitor2d"]["parameters"]["yParam"] == 2


def test_a_sweep_missing_readin_is_refused_by_name(tmp_path: Path) -> None:
    """READIN has staged paths and therefore has no runnable server default."""
    variants = swept_modules(tmp_path)
    del variants["readin"]

    command, _tools = _plan(tmp_path, variants=variants)

    assert "readin" in _errors(command)[0]
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


def test_cartesian_limit_is_checked_before_the_product_is_materialized(
    tmp_path: Path, artifact_store, monkeypatch: pytest.MonkeyPatch
) -> None:
    variants = swept_modules(tmp_path, guide_widths=tuple(float(n) for n in range(2, 10)))
    variants["monitor1d"] = [
        {
            **variants["monitor1d"][0],
            "parameters": {
                **variants["monitor1d"][0]["parameters"],
                "nBinsX": bins,
            },
        }
        for bins in (10, 20, 30, 40, 50)
    ]

    def product_must_not_run(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the oversized Cartesian product was materialized")

    monkeypatch.setattr(
        "vitess_ai.agents.advanced_mode.tools.product", product_must_not_run
    )
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


def test_execution_rechecks_the_sweep_limit_from_checkpointed_state(
    tmp_path: Path, artifact_store
) -> None:
    requested: list[dict[str, Any]] = []

    def record(call: dict[str, Any]) -> dict[str, Any]:
        requested.append(call["args"])
        return simulation_payload()

    command, tools = _plan(tmp_path, run_simulation=record)
    original = command.update["simulation_plan"][0]
    oversized = [
        {
            **original,
            "run_name": f"run {index + 1}",
            "simulation_run_id": str(uuid4()),
        }
        for index in range(MAX_SWEEP_RUNS + 1)
    ]

    result = _run_batch(tools, oversized)

    assert requested == []
    assert f"over the limit of {MAX_SWEEP_RUNS}" in _errors(result)[0]
    assert result.update["execution_events"][0]["status"] == "tool_error"


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
    assert all(message.status == "error" for message in result.update["messages"])


def test_a_stale_variant_schema_is_refused_before_planning(
    tmp_path: Path, artifact_store
) -> None:
    variants = swept_modules(tmp_path)
    variants["guide"][0] = {
        **variants["guide"][0],
        "schema_version": "old-schema",
    }

    command, _tools = _plan(tmp_path, variants=variants)

    assert "schema has changed" in _errors(command)[0]
    assert "simulation_plan" not in command.update


def test_execution_refuses_a_plan_with_an_unplanned_module(
    tmp_path: Path, artifact_store
) -> None:
    requested: list[dict[str, Any]] = []

    def record(call: dict[str, Any]) -> dict[str, Any]:
        requested.append(call["args"])
        return simulation_payload()

    command, tools = _plan(tmp_path, run_simulation=record)
    plan = json.loads(json.dumps(command.update["simulation_plan"]))
    plan[0]["modules"]["invented"] = {
        "module": "invented",
        "validated_at": "2026-09-17T00:00:00+00:00",
        "parameters": {},
        "schema_version": "invented",
    }

    result = _run_batch(tools, plan)

    assert requested == []
    assert "unplanned modules" in _text(result)


def test_execution_refuses_a_plan_whose_schema_became_stale(
    tmp_path: Path, artifact_store
) -> None:
    requested: list[dict[str, Any]] = []

    def record(call: dict[str, Any]) -> dict[str, Any]:
        requested.append(call["args"])
        return simulation_payload()

    command, tools = _plan(tmp_path, run_simulation=record)
    plan = json.loads(json.dumps(command.update["simulation_plan"]))
    plan[0]["modules"]["guide"]["schema_version"] = "old-schema"

    result = _run_batch(tools, plan)

    assert requested == []
    assert "schema has changed" in _text(result)


def test_invalid_run_name_is_a_tool_error_not_an_uncaught_validation_error(
    tmp_path: Path, artifact_store
) -> None:
    command, _tools = _plan(tmp_path, run_names=["   "])

    assert "run name" in _errors(command)[0].lower()
    assert "simulation_plan" not in command.update


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
    assert "There is no user to ask" in sweep


def test_a_single_variant_object_reaches_the_documented_compatibility_path(
    tmp_path: Path,
) -> None:
    tool = named_tool(
        guide_sweep(project_root=tmp_path, gateway=None), "validate_guide_variants"
    )
    trusted_runtime = runtime()
    validated = TypeAdapter(
        tool.args_schema.model_fields["parameter_sets"].annotation
    ).validate_python(
        {"GuideEntrWidth": 3.0}
    )

    command = tool.func(
        runtime=trusted_runtime,
        parameter_sets=validated,
    )

    assert len(command.update["module_variants"]["guide"]) == 1


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


def test_a_specialist_cannot_record_more_variants_than_a_sweep_can_run(
    tmp_path: Path,
) -> None:
    tool = named_tool(
        guide_sweep(project_root=tmp_path, gateway=None), "validate_guide_variants"
    )

    command = tool.func(
        runtime=runtime(),
        parameter_sets=[
            {"GuideEntrWidth": float(index + 1)}
            for index in range(MAX_SWEEP_RUNS + 1)
        ],
    )

    assert f"limit of {MAX_SWEEP_RUNS}" in _errors(command)[0]
    assert "module_variants" not in command.update


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


def test_the_guide_shape_conversation_uses_the_authoritative_schema(
    offline_model: Any,
) -> None:
    """Regression for the run where the supervisor invented ``linear = 0``.

    The advanced supervisor does not carry every module schema in its prompt.
    This exact request therefore has a tool route to the live Pydantic model,
    where linear is 1 and the exit dimensions are the ``-W``/``-H`` fields.
    """

    script = [
        _call("describe_module_parameters", {"module": "guide"}, 0),
        AIMessage(
            "The schema says linear is 1. I will preserve that intent and vary "
            "GuideExitWidth and GuideExitHeight over 2.0, 1.0, and 0.5 cm."
        ),
    ]
    graph = build_advanced_mode_graph(
        supervisor_model=_ScriptedSupervisor(responses=script),
        summarizer_model=offline_model,
        fallback_models=[],
        specialists=[
            {
                "name": "guide-specialist",
                "description": "Configure the guide.",
                "runnable": _Nothing(),
                "module": "guide",
            }
        ],
        tools=[],
        store=InMemoryStore(),
    )
    context = _Context(thread_id=THREAD_ID, user_id=str(uuid4()), run_id=str(uuid4()))

    result = asyncio.run(
        graph.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        "Set both guide shapes to linear and use outlet sizes "
                        "[2.0, 1.0, 0.5] for three simulations."
                    )
                ]
            },
            {
                "configurable": {"thread_id": THREAD_ID},
                "run_id": context.run_id,
            },
            context=context,
        )
    )

    schema_message = next(
        message
        for message in result["messages"]
        if isinstance(message, ToolMessage)
        and message.name == "describe_module_parameters"
    )
    described = json.loads(schema_message.text)

    assert described["enum_mappings"]["VtGdeShape"]["VT_CONSTANT"] == 0
    assert described["enum_mappings"]["VtGdeShape"]["VT_LINEAR"] == 1
    assert described["schema_defaults"]["eGuideShapeY"] == 1
    assert described["schema_defaults"]["eGuideShapeZ"] == 1
    assert described["json_schema"]["properties"]["GuideExitWidth"]["flag"] == "-W"
    assert described["json_schema"]["properties"]["GuideExitHeight"]["flag"] == "-H"


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


def test_advanced_mode_allowlists_its_facade_tools() -> None:
    class _Tool:
        def __init__(self, name: str) -> None:
            self.name = name

    selected = _advanced_facade_tools(
        [
            _Tool("run_simulation"),
            _Tool("inspect_thread_folders"),
            _Tool("generate_monitor1d_plot"),
            _Tool("generate_monitor2d_plot"),
            _Tool("future_dangerous_tool"),
        ]
    )

    assert [tool.name for tool in selected] == [
        "inspect_thread_folders",
        "generate_monitor1d_plot",
        "generate_monitor2d_plot",
    ]


def test_the_factory_selects_its_facade_through_the_allowlist(
    tmp_path: Path, configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An allowlist nothing calls is the same defect as a denylist.

    `_advanced_facade_tools` is tested directly, but the factory is the only
    place it matters and the factory needs a live MCP server, so nothing proved
    it was used. Replacing the call with the old
    `[item for item in facade if item.name != "run_simulation"]` passed the
    whole suite.
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
    monkeypatch.setattr(agent_module, "compile_sweep_specialists", lambda **_: [])
    monkeypatch.setattr(agent_module, "project_root", lambda: tmp_path)

    # The façade grows a tool. Today's denylist and today's allowlist select the
    # same three tools, so nothing distinguishes them until one more exists --
    # which is the entire situation the allowlist is for.
    real_facade = agent_module.build_vitess_tools

    def facade_with_a_new_tool(*args: Any, **kwargs: Any) -> list[Any]:
        @tool("purge_thread_outputs", description="A tool added later, to no fanfare.")
        def purge() -> str:
            return "purged"

        return [*real_facade(*args, **kwargs), purge]

    monkeypatch.setattr(agent_module, "build_vitess_tools", facade_with_a_new_tool)

    def capture(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(agent_module, "build_advanced_mode_graph", capture)
    asyncio.run(
        agent_module.create_advanced_mode_agent(
            provider="blablador", model=configured.DEFAULT_MODEL
        )
    )

    names = [tool.name for tool in captured["tools"]]
    assert names[: len(_ADVANCED_FACADE_TOOL_NAMES)] == list(_ADVANCED_FACADE_TOOL_NAMES)
    assert "run_simulation" not in names
    assert "purge_thread_outputs" not in names
    assert set(names) == set(_ADVANCED_FACADE_TOOL_NAMES) | {
        "write_simulation_matrix",
        "run_batch_from_matrix",
    }


def test_the_sweep_graph_adds_documentation_tools_and_the_matching_policy(
    offline_model: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The graph builder, not only the production factory, owns both halves.

    Every existing golden graph is built directly. Wiring RAG only in the
    factory made those tests incapable of seeing a prompt that named four
    absent tools.
    """
    captured: dict[str, Any] = {}

    @tool("documentation_probe", description="A documentation test tool.")
    def documentation_probe(query: str) -> str:
        return query

    def documentation(*, unattended: bool) -> tuple[list[Any], str]:
        captured["unattended"] = unattended
        return [documentation_probe], "SWEEP_DOCUMENTATION_POLICY"

    class _Graph:
        def with_config(self, config: dict[str, Any]) -> "_Graph":
            captured["config"] = config
            return self

    def capture_agent(**kwargs: Any) -> _Graph:
        captured.update(kwargs)
        return _Graph()

    monkeypatch.setattr(agent_module, "orchestrator_documentation", documentation)
    monkeypatch.setattr(agent_module, "create_agent", capture_agent)

    agent_module.build_advanced_mode_graph(
        supervisor_model=_ScriptedSupervisor(responses=[AIMessage("done")]),
        summarizer_model=offline_model,
        fallback_models=[],
        specialists=[
            {
                "name": "guide-specialist",
                "description": "Configure the guide.",
                "runnable": _Nothing(),
                "module": "guide",
            }
        ],
        tools=[],
        store=InMemoryStore(),
    )

    assert captured["unattended"] is True
    assert [item.name for item in captured["tools"]] == [
        describe_module_parameters.name,
        "documentation_probe",
    ]
    assert str(captured["system_prompt"]).endswith("SWEEP_DOCUMENTATION_POLICY")


def test_advanced_prompt_describes_the_actual_filesystem_boundary() -> None:
    prompt = (
        Path(__file__).parents[1]
        / "src/vitess_ai/agents/advanced_mode/AGENT.md"
    ).read_text(encoding="utf-8")

    assert "`read_file`" in prompt
    for name in (
        "describe_module_parameters",
        "vitess_search",
        "vitess_option_lookup",
        "vitess_module_lookup",
        "vitess_debug_retrieval",
    ):
        assert f"`{name}`" in prompt
    assert "no `ask_user` tool, project-filesystem access or shell" in prompt
    assert "`/data/projects` included, is refused with a message saying so" in prompt
    assert "Do not invent a field name" in prompt
    assert 'translate an enum label such as\n   "linear" into an integer from memory' in prompt


def test_the_sweep_binds_only_the_filesystem_tools_its_prompt_names(
    tmp_path: Path, offline_model: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The supervisor half of CP4's "name exactly the tools you have".

    Core's default hands a supervisor all eight tools its backend can offer,
    `execute` and `delete` among them. Neither can do anything here -- `execute`
    replies that the backend implements no sandbox protocol, and both refuse any
    path outside `/memories/` -- but a tool named `execute` is the one a weaker
    model reaches for when it decides to run VITESS itself, which is the single
    thing one execution path exists to prevent. This asserts three links at
    once: the agent asks for the narrowed set, the middleware binds exactly it,
    and the prompt names exactly what was bound.
    """
    captured: dict[str, Any] = {}
    real = agent_module.build_supervisor_middleware

    def capture(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(agent_module, "build_supervisor_middleware", capture)
    agent_module.build_advanced_mode_graph(
        supervisor_model=_ScriptedSupervisor(responses=[AIMessage("done")]),
        summarizer_model=offline_model,
        fallback_models=[],
        specialists=[
            {
                "name": "guide-specialist",
                "description": "Configure the guide.",
                "runnable": _Nothing(),
                "module": "guide",
            }
        ],
        tools=[],
        store=InMemoryStore(),
    )

    assert captured["filesystem_tools"] == VITESS_FILESYSTEM_TOOLS
    filesystem = next(
        item
        for item in real(**captured)
        if type(item).__name__ == "FilesystemMiddleware"
    )
    bound = {tool.name for tool in filesystem.tools}
    assert bound == set(VITESS_FILESYSTEM_TOOLS)

    prompt = (
        Path(__file__).parents[1] / "src/vitess_ai/agents/advanced_mode/AGENT.md"
    ).read_text(encoding="utf-8")
    for name in sorted(bound):
        assert f"`{name}`" in prompt, f"AGENT.md never mentions `{name}`"
    # The two it does not have appear once each, in the sentence saying so.
    assert "There is no `execute` and no `delete`." in prompt
    for absent in ("execute", "delete"):
        assert absent not in bound
        assert prompt.count(f"`{absent}`") == 1


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
            *_advanced_facade_tools(
                build_vitess_tools(gateway, project_root=tmp_path)
            ),
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
