"""Model-safe façade tools for the raw VITESS MCP service."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, InjectedToolArg
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.json_schema import SkipJsonSchema

from juena_core.agents.specialist_outcome import (
    ArtifactMessageMiddleware,
    ExecutionEvidenceMiddleware,
)
from juena_core.artifacts import (
    DOWNLOAD_TYPES,
    MAX_ARTIFACT_BYTES,
    MAX_FILE_ARTIFACT_BYTES,
    get_artifact_store,
)
from juena_core.schema.interrupts import ExecutionEvidence
from vitess_ai.cli.arguments import ParameterConversionError, parameters_to_arguments
from vitess_ai.mcp.payloads import PlotResult, RunFile, SimulationResult
from vitess_ai.modules.catalog import execution_order
from vitess_ai.modules.parameters import parameter_model
from vitess_ai.schema.module_result import (
    ModuleConfigurationResult,
    module_schema_version,
)
from vitess_ai.run import (
    InternalSimulationRequest,
    SimulationOutcome,
    VitessGateway,
    safe_run_file,
)
from vitess_ai.state import SimulationOrderEvent, SimulationRunReference

__all__ = [
    "attach_artifacts",
    "build_vitess_tools",
    "capture_flux_summary",
    "plan_simulation",
    "register_run_files",
    "runtime_identity",
    "state_mapping",
    "tool_message",
    "vitess_supervisor_middleware",
]

# The helpers above are public because the batch path needs them too.
# `vitess_ai.agents.advanced_mode.tools` reads the same trusted identity, writes
# the same kind of tool message and registers produced files through the same
# artifact checks -- one execution path, two trusted callers (03/CP5). A second
# copy of "which files may be delivered to a user" is the kind of thing that
# drifts into a sweep quietly delivering what the guided path refuses.


class _FacadeArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    # Explicit args schemas otherwise reject the trusted value ToolNode injects
    # after the model call.  The two markers keep it injectable while omitting
    # it from both the JSON schema and the model-visible tool-call schema.
    runtime: Annotated[
        ToolRuntime[Any, Any],
        InjectedToolArg,
        SkipJsonSchema(),
    ]


class _RunArguments(_FacadeArguments):
    run_name: str | None = Field(default=None, min_length=1, max_length=120)


class _InspectArguments(_FacadeArguments):
    pass


class _PlanArguments(_FacadeArguments):
    pass


class _PlotArguments(_FacadeArguments):
    run_name: str | None = Field(default=None, min_length=1, max_length=120)
    filename: str | None = Field(default=None, min_length=1, max_length=240)


def _context_value(context: Any, name: str) -> str | None:
    if isinstance(context, Mapping):
        value = context.get(name)
    else:
        value = getattr(context, name, None)
    return str(value) if value else None


def runtime_identity(runtime: ToolRuntime[Any, Any]) -> tuple[str, str, str]:
    execution_info = getattr(runtime, "execution_info", None)
    thread_id = getattr(execution_info, "thread_id", None)
    context = getattr(runtime, "context", None)
    # The invocation id is mirrored into context because that value survives a
    # subgraph boundary.  Use the execution-info value only for callers that do
    # not delegate, matching core's evidence middleware.
    graph_run_id = _context_value(context, "run_id") or getattr(
        execution_info, "run_id", None
    )
    user_id = _context_value(context, "user_id")
    context_thread = _context_value(context, "thread_id")
    if not thread_id or not graph_run_id or not user_id:
        raise ValueError("VITESS tools require trusted user, thread and graph-run identity")
    try:
        canonical_thread = str(UUID(str(thread_id)))
    except ValueError as exc:
        raise ValueError("Trusted thread_id must be a UUID") from exc
    if str(thread_id) != canonical_thread:
        raise ValueError("Trusted thread_id must use canonical UUID form")
    if context_thread is not None and context_thread != canonical_thread:
        raise ValueError("Runtime context and execution_info disagree on thread_id")
    return user_id, canonical_thread, str(graph_run_id)


def tool_message(
    runtime: ToolRuntime[Any, Any], content: str, *, error: bool = False
) -> ToolMessage:
    return ToolMessage(
        content=content,
        tool_call_id=runtime.tool_call_id,
        status="error" if error else "success",
    )


def capture_flux_summary(result: SimulationResult) -> str | None:
    """One sentence with the capture flux the server read from the run's log.

    Both run paths append it to their tool message, so the supervisor can
    report the number without a log in its context. ``None`` when the run has
    no reading.
    """
    reading = result.capture_flux
    if reading is None:
        return None
    reference = (
        f"reference wavelength {reading.reference_wavelength:.3f} Å"
        if reading.reference_wavelength > 0
        else "no reference wavelength"
    )
    return (
        "Capture flux from the capture_flux log: "
        f"{reading.capture_flux:.3e} ± {reading.capture_flux_error:.3e} n/(s·cm²); "
        f"captured intensity {reading.captured_intensity:.3e} ± "
        f"{reading.captured_intensity_error:.3e} n/s from {reading.trajectories} "
        f"trajectories; {reference}."
    )


def state_mapping(runtime: ToolRuntime[Any, Any]) -> Mapping[str, Any]:
    state = getattr(runtime, "state", None)
    return state if isinstance(state, Mapping) else {}


def _run_references(runtime: ToolRuntime[Any, Any]) -> list[SimulationRunReference]:
    references: list[SimulationRunReference] = []
    for value in state_mapping(runtime).get("simulation_runs", []):
        try:
            references.append(SimulationRunReference.model_validate(value))
        except ValidationError:
            continue
    return references


def _planned_order(runtime: ToolRuntime[Any, Any]) -> tuple[str, ...]:
    """The pipeline `plan_simulation` recorded, or nothing.

    Read from state rather than from the catalog, even though
    `plan_simulation` fills it from the catalog. Reading the catalog here would
    make the plan decorative: a supervisor that never planned would still run,
    and "the modules were delegated in the planned order" would be a claim
    about two copies of the same constant rather than about what happened.
    """
    planned = state_mapping(runtime).get("planned_execution_order")
    if not isinstance(planned, (list, tuple)) or not planned:
        return ()
    return tuple(str(module) for module in planned)


def _configured_arguments(
    runtime: ToolRuntime[Any, Any],
    planned: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    """Rebuild each planned module's VITESS arguments from its stored result.

    The arguments are derived here rather than stored by the validation tool,
    so a configuration and the command it runs as cannot disagree: there is
    one converter and it is called once, at the moment of execution, against
    the module's own model. Re-validating also means a result checkpointed
    under an older schema fails loudly instead of running as something else.
    """
    stored = state_mapping(runtime).get("module_results")
    if not isinstance(stored, Mapping):
        raise ValueError(
            "No VITESS module has been configured yet. Delegate to the module "
            "specialists first."
        )

    missing = [module for module in planned if module not in stored]
    if missing:
        raise ValueError(
            "These planned modules have no validated configuration: "
            + ", ".join(missing)
            + ". Delegate to their specialists before running the simulation."
        )
    unplanned = sorted(set(stored) - set(planned))
    if unplanned:
        raise ValueError(
            "These configurations belong to no planned module: "
            + ", ".join(unplanned)
        )

    arguments: dict[str, dict[str, Any]] = {}
    for module in planned:
        result = ModuleConfigurationResult.model_validate(stored[module])
        if result.module != module:
            raise ValueError(
                f"The configuration stored for {module!r} says it is for "
                f"{result.module!r}"
            )
        model = parameter_model(module)
        current_version = module_schema_version(model)
        if result.schema_version != current_version:
            raise ValueError(
                f"The {module!r} parameter schema has changed since this "
                "configuration was validated. Delegate to its specialist again."
            )
        arguments[module] = {
            "cli_parameters": parameters_to_arguments(model(**result.parameters))
        }
    return arguments


def _require_configuration_order(
    runtime: ToolRuntime[Any, Any], planned: tuple[str, ...]
) -> None:
    """Require first-time configurations after the latest plan to match it.

    `module_results` is keyed by module and therefore proves completeness only.
    These append-only events retain the sequence. Reconfiguring a module after
    the complete first pass is intentionally allowed; its first occurrence is
    the one that establishes the pipeline.
    """
    raw_events = state_mapping(runtime).get("simulation_order_events")
    if not isinstance(raw_events, (list, tuple)):
        raise ValueError(
            "No server-owned module configuration sequence is recorded. Call "
            "plan_simulation and delegate to every specialist in its order."
        )

    events = [SimulationOrderEvent.model_validate(value) for value in raw_events]
    plan_indexes = [index for index, event in enumerate(events) if event.kind == "plan"]
    if not plan_indexes:
        raise ValueError("The configuration sequence contains no plan event")
    latest_plan = plan_indexes[-1]
    plan_event = events[latest_plan]
    if tuple(plan_event.execution_order or ()) != planned:
        raise ValueError("The recorded plan and planned execution order disagree")

    configured: list[str] = []
    for event in events[latest_plan + 1 :]:
        if event.kind == "configured" and event.module not in configured:
            assert event.module is not None
            configured.append(event.module)
    if tuple(configured) != planned:
        expected = " -> ".join(planned)
        observed = " -> ".join(configured) or "none"
        raise ValueError(
            "Modules were not configured in order after the latest plan. "
            f"Expected {expected}; observed {observed}. Call plan_simulation "
            "again and delegate in the returned order."
        )


def _failed_run_command(
    runtime: ToolRuntime[Any, Any],
    *,
    graph_run_id: str,
    message: str,
    status: Literal["failed", "tool_error"] = "tool_error",
) -> Command:
    event = ExecutionEvidence(
        graph_run_id=graph_run_id,
        command="VITESS simulation",
        status=status,
        exit_code=None,
    )
    return Command(
        update={
            "messages": [tool_message(runtime, message, error=True)],
            "execution_events": [event.model_dump(mode="json")],
        }
    )


def _load_descriptors(
    project_root: Path,
    result: SimulationResult,
) -> list[tuple[RunFile, Path]]:
    """Resolve every claim before artifact registration mutates the store."""

    return [
        (
            descriptor,
            safe_run_file(
                project_root,
                thread_id=result.thread_id,
                simulation_run_id=result.simulation_run_id,
                descriptor=descriptor,
            ),
        )
        for descriptor in result.files
    ]


def register_run_files(
    *,
    project_root: Path,
    user_id: str,
    thread_id: str,
    graph_run_id: str,
    result: SimulationResult,
    run_name: str | None = None,
) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    resolved = _load_descriptors(project_root, result)
    store = get_artifact_store()
    artifact_ids: list[str] = []
    artifact_filenames: list[str] = []
    dropped: list[tuple[str, str]] = []

    for descriptor, path in resolved:
        extension = path.suffix.lower()
        limit = MAX_ARTIFACT_BYTES if descriptor.kind == "plot" else MAX_FILE_ARTIFACT_BYTES
        reason: str | None = None
        if descriptor.kind == "plot" and extension != ".png":
            reason = "Server labelled a non-PNG file as a plot"
        elif descriptor.kind != "plot" and extension not in DOWNLOAD_TYPES:
            reason = "Generated file type is not allowed for chat delivery"
        elif descriptor.size_bytes == 0:
            reason = "Generated file is empty"
        elif descriptor.size_bytes > limit:
            reason = "Generated file exceeds the artifact size limit"

        if reason is not None:
            store.note_undelivered(user_id, thread_id, descriptor.path, reason)
            dropped.append((descriptor.path, reason))
            continue

        try:
            reference = store.register_artifact(
                user_id=user_id,
                thread_id=thread_id,
                run_id=graph_run_id,
                filename=path.name,
                content=path.read_bytes(),
                caption=f"VITESS output: {descriptor.path}",
                group_id=str(result.simulation_run_id),
                group_label=f"Simulation proof · {run_name or result.simulation_run_id}",
            )
        except (OSError, ValueError) as exc:
            reason = str(exc) or type(exc).__name__
            store.note_undelivered(user_id, thread_id, descriptor.path, reason)
            dropped.append((descriptor.path, reason))
            continue
        artifact_ids.append(reference.artifact_id)
        artifact_filenames.append(reference.filename)
    return artifact_ids, artifact_filenames, dropped


def attach_artifacts(
    events: Sequence[ExecutionEvidence],
    *,
    artifact_ids: list[str],
    artifact_filenames: list[str],
    dropped: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    if not events:
        return []
    updated = list(events)
    updated[-1] = updated[-1].model_copy(
        update={
            "artifact_ids": artifact_ids,
            "artifact_filenames": artifact_filenames,
            "dropped": dropped,
        }
    )
    return [event.model_dump(mode="json") for event in updated]


def _select_run(
    runtime: ToolRuntime[Any, Any], run_name: str | None
) -> SimulationRunReference:
    references = _run_references(runtime)
    if not references:
        raise ValueError("No VITESS simulation run is recorded in this conversation")
    if run_name is None:
        return references[-1]
    matches = [item for item in references if item.run_name == run_name]
    if not matches:
        raise ValueError(f"No VITESS simulation is named {run_name!r}")
    return matches[-1]


PLAN_DESCRIPTION = (
    "Return the VITESS modules this simulation needs, in the order they must be "
    "configured and run. Call this before delegating to any module specialist. "
    "run_simulation will not run a pipeline that was never planned."
)


@tool("plan_simulation", args_schema=_PlanArguments, description=PLAN_DESCRIPTION)
def plan_simulation(runtime: ToolRuntime[Any, Any]) -> Command:
    """Record the pipeline order, from the catalog, as a checked precondition.

    The first-generation simulator held this order in graph edges, and losing
    them was the one real risk in rebuilding on a free-form supervisor: a
    supervisor that configures the monitor before the guide produces a
    simulation that runs, completes, and is wrong.

    So the order is neither an edge nor a sentence in a prompt. It is written
    into state here, by a tool, from `execution_order()` -- and `run_simulation`
    reads it back from state. **Both ends are server-owned**, which is the only
    reason comparing them proves anything: a model that skipped this call gets a
    refusal rather than a pipeline in whatever order it happened to delegate.
    """
    planned = list(execution_order())
    plan_event = SimulationOrderEvent(
        kind="plan", execution_order=tuple(planned)
    ).model_dump(mode="json")
    return Command(
        update={
            "planned_execution_order": planned,
            "simulation_order_events": [plan_event],
            "messages": [
                tool_message(
                    runtime,
                    "Configure and run these VITESS modules in this order: "
                    + " -> ".join(planned)
                    + ". Delegate to one module specialist at a time, in this "
                    "order, and run the simulation only once all of them have "
                    "reported.",
                )
            ],
        }
    )


def build_vitess_tools(
    gateway: VitessGateway,
    *,
    project_root: str | Path | None = None,
) -> list[BaseTool]:
    """Wrap the MCP gateway in tool schemas containing no trusted arguments.

    Takes the gateway rather than the raw tools so that one process holds one
    gateway. The module specialists need it too -- read-in and guide ask it
    what the user has staged -- and two gateways over the same four tools would
    be two places to change a rule that has to hold in both.
    """

    root = Path(project_root or "/data/projects").expanduser().resolve()

    @tool(
        "run_simulation",
        args_schema=_RunArguments,
        description=(
            "Run the validated VITESS module configuration already stored for this "
            "conversation. Optionally give the run a short human-readable name."
        ),
    )
    async def run_simulation(
        runtime: ToolRuntime[Any, Any],
        run_name: str | None = None,
    ) -> Command:
        try:
            user_id, thread_id, graph_run_id = runtime_identity(runtime)
        except ValueError as exc:
            # There is no trustworthy graph id for an evidence event on this path.
            return Command(update={"messages": [tool_message(runtime, str(exc), error=True)]})

        references = _run_references(runtime)
        display_name = run_name or f"simulation {len(references) + 1}"
        if any(reference.run_name == display_name for reference in references):
            return _failed_run_command(
                runtime,
                graph_run_id=graph_run_id,
                message=f"A VITESS simulation is already named {display_name!r}",
            )

        planned = _planned_order(runtime)
        if not planned:
            return _failed_run_command(
                runtime,
                graph_run_id=graph_run_id,
                message=(
                    "This simulation has no plan. Call plan_simulation first, "
                    "then delegate to each module specialist in the order it "
                    "returns."
                ),
            )
        try:
            module_results = _configured_arguments(runtime, planned)
            _require_configuration_order(runtime, planned)
        except (ValidationError, ValueError, ParameterConversionError, KeyError) as exc:
            return _failed_run_command(
                runtime,
                graph_run_id=graph_run_id,
                message=f"The VITESS configuration is not runnable: {exc}",
            )

        simulation_run_id = uuid4()
        try:
            request = InternalSimulationRequest(
                thread_id=thread_id,
                simulation_run_id=simulation_run_id,
                graph_run_id=graph_run_id,
                module_results=module_results,
                execution_order=planned,
            )
        except ValidationError as exc:
            return _failed_run_command(
                runtime,
                graph_run_id=graph_run_id,
                message=f"Validated module state is incomplete: {exc}",
            )

        outcome: SimulationOutcome = await gateway.run_simulation(request)
        if outcome.result is None:
            assert outcome.failure is not None
            return Command(
                update={
                    "messages": [
                        tool_message(
                            runtime,
                            f"VITESS simulation could not be verified: {outcome.failure.message}",
                            error=True,
                        )
                    ],
                    "execution_events": [
                        event.model_dump(mode="json") for event in outcome.events
                    ],
                }
            )

        try:
            artifact_ids, artifact_filenames, dropped = register_run_files(
                project_root=root,
                user_id=user_id,
                thread_id=thread_id,
                graph_run_id=graph_run_id,
                result=outcome.result,
                run_name=display_name,
            )
        except ValueError as exc:
            failure = ExecutionEvidence(
                graph_run_id=graph_run_id,
                command="VITESS artifact verification",
                status="tool_error",
                exit_code=None,
            )
            return Command(
                update={
                    "messages": [
                        tool_message(
                            runtime,
                            f"VITESS returned unverifiable file metadata: {exc}",
                            error=True,
                        )
                    ],
                    "execution_events": [failure.model_dump(mode="json")],
                }
            )

        events = attach_artifacts(
            outcome.events,
            artifact_ids=artifact_ids,
            artifact_filenames=artifact_filenames,
            dropped=dropped,
        )
        module_summary = ", ".join(
            f"{module.name}=exit {module.exit_code}" for module in outcome.result.modules
        )
        message = (
            f"VITESS {display_name!r}: {outcome.result.message}. "
            f"Server evidence: {module_summary or 'no module process started'}."
        )
        summary = capture_flux_summary(outcome.result)
        if summary:
            message += f" {summary}"
        update: dict[str, Any] = {
            "messages": [tool_message(runtime, message, error=not outcome.success)],
            "execution_events": events,
        }
        if outcome.result.modules or outcome.result.files:
            reference = SimulationRunReference(
                run_name=display_name,
                simulation_run_id=simulation_run_id,
            )
            update["simulation_runs"] = [reference.model_dump(mode="json")]
        return Command(update=update)

    @tool(
        "inspect_thread_folders",
        args_schema=_InspectArguments,
        description="List staged VITESS inputs and prior simulation outputs for this conversation.",
    )
    async def inspect_thread_folders(runtime: ToolRuntime[Any, Any]) -> ToolMessage:
        try:
            _user_id, thread_id, _graph_run_id = runtime_identity(runtime)
        except ValueError as exc:
            return tool_message(runtime, str(exc), error=True)
        response = await gateway.inspect_thread(thread_id)
        if response.failure is not None:
            return tool_message(
                runtime,
                f"VITESS file inspection failed: {response.failure.message}",
                error=True,
            )
        assert response.value is not None
        return tool_message(
            runtime,
            json.dumps(response.value.model_dump(mode="json"), separators=(",", ":")),
        )

    def plot_tool(kind: Literal["monitor1d", "monitor2d"]) -> BaseTool:
        @tool(
            f"generate_{kind}_plot",
            args_schema=_PlotArguments,
            description=(
                f"Render the {kind} data from a VITESS simulation as a PNG artifact. "
                "Omit run_name to use the latest run."
            ),
        )
        async def generate_plot(
            runtime: ToolRuntime[Any, Any],
            run_name: str | None = None,
            filename: str | None = None,
        ) -> ToolMessage:
            try:
                user_id, thread_id, graph_run_id = runtime_identity(runtime)
                reference = _select_run(runtime, run_name)
            except ValueError as exc:
                return tool_message(runtime, str(exc), error=True)

            response = await gateway.generate_plot(
                kind=kind,
                thread_id=thread_id,
                simulation_run_id=str(reference.simulation_run_id),
                filename=filename,
            )
            if response.failure is not None:
                return tool_message(
                    runtime,
                    f"VITESS plot generation failed: {response.failure.message}",
                    error=True,
                )
            assert response.value is not None
            plot: PlotResult = response.value
            descriptor = RunFile(path=plot.path, kind="plot", size_bytes=plot.size_bytes)
            synthetic = SimulationResult(
                success=True,
                timed_out=False,
                thread_id=thread_id,
                simulation_run_id=str(reference.simulation_run_id),
                files=(descriptor,),
                message=plot.message,
            )
            try:
                artifact_ids, _filenames, dropped = register_run_files(
                    project_root=root,
                    user_id=user_id,
                    thread_id=thread_id,
                    graph_run_id=graph_run_id,
                    result=synthetic,
                    run_name=reference.run_name,
                )
            except ValueError as exc:
                return tool_message(
                    runtime,
                    f"VITESS returned unverifiable plot metadata: {exc}",
                    error=True,
                )
            if not artifact_ids or dropped:
                reason = dropped[0][1] if dropped else "artifact registration failed"
                return tool_message(
                    runtime,
                    f"The plot was rendered but could not be delivered: {reason}",
                    error=True,
                )
            return tool_message(
                runtime,
                f"Rendered {kind} plot for {reference.run_name!r} as {plot.path}.",
            )

        return generate_plot

    return [
        run_simulation,
        inspect_thread_folders,
        plot_tool("monitor1d"),
        plot_tool("monitor2d"),
    ]


def vitess_supervisor_middleware(agent_name: str = "vitess") -> list[Any]:
    """The CP3a root hooks: evidence block first, artifact attachment second.

    ``agent_name`` is what the `<verified_by_server>` block says produced the
    evidence, so the sweep passes its own id. Both agents run the same hooks over
    the same channel -- that is the point of the seam — but a sweep's evidence
    labelled `vitess` would send a reader to the wrong thread for it.
    """

    return [
        ExecutionEvidenceMiddleware(agent_name=agent_name),
        ArtifactMessageMiddleware(),
    ]
