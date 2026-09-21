"""The two tools a parameter sweep runs on.

`write_simulation_matrix` expands the sweep and `run_batch_from_matrix` executes
it. Between them sits the `simulation_plan` channel, and the point of the pair is
what is **not** in either signature: no `module_results`, no `run_specs`, no
`execution_order`, no `thread_id`. The first-generation batch tool took all four
from the model (`agents/advanced_mode/tools.py:458`), so the sweep reached
execution through model-authored parameters while the guided path was busy
closing exactly that route.

Two smaller things the first generation got wrong and this does not:

*The matrix file is written, not read.* It was the input to execution --
`run_batch_from_matrix` loaded it, converted it and ran it -- so a file anyone
could edit decided what VITESS did. Here the file is **rendered from the plan**,
the same way 03/CP1 renders a display command that is never executed: readable,
checkable, downloadable, and not the thing that runs.

*`run_id` was the model's `run_name`.* Whatever the model called a run became a
directory name on a shared volume. The two are separate fields now, and only one
of them is an identifier.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from itertools import product
from math import prod
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from langchain.tools import ToolRuntime, tool
from langchain_core.tools import BaseTool, InjectedToolArg
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.json_schema import SkipJsonSchema

from juena_core.schema.interrupts import ExecutionEvidence
from vitess_ai.agents.specialists.module_specialist import validate_module_parameters
from vitess_ai.cli.arguments import parameters_to_arguments
from vitess_ai.modules.catalog import execution_order
from vitess_ai.modules.parameters import parameter_model
from vitess_ai.run import InternalSimulationRequest, VitessGateway
from vitess_ai.schema.module_result import (
    ModuleConfigurationResult,
    module_schema_version,
)
from vitess_ai.schema.simulation_plan import MAX_SWEEP_RUNS, SimulationPlanEntry
from vitess_ai.state import SimulationRunReference
from vitess_ai.tools import (
    attach_artifacts,
    register_run_files,
    runtime_identity,
    state_mapping,
    tool_message,
)

__all__ = ["MAX_SWEEP_RUNS", "build_batch_tools"]

MATRIX_FILENAME = "simulation_matrix.json"

# READIN always needs a staged source path and therefore cannot be constructed
# from its schema defaults. These four modules have complete, runnable defaults.
AUTO_DEFAULT_MODULES = frozenset({"guide", "writeout", "monitor1d", "monitor2d"})


class _SweepArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    combination: Literal["cartesian", "paired"] = Field(
        description=(
            "How to combine the modules' variants. 'cartesian' runs every "
            "combination; 'paired' runs one simulation per row, taking the "
            "first variant of each module together, then the second, and so on."
        )
    )
    run_names: list[str] | None = Field(
        default=None,
        description=(
            "Optional human-readable name for each run, in order. Names are "
            "labels, not identifiers -- the server names the output directory."
        ),
    )
    runtime: Annotated[
        ToolRuntime[Any, Any],
        InjectedToolArg,
        SkipJsonSchema(),
    ]


class _BatchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    runtime: Annotated[
        ToolRuntime[Any, Any],
        InjectedToolArg,
        SkipJsonSchema(),
    ]


def _current_result(module: str, value: Any) -> ModuleConfigurationResult:
    """Validate one stored result against the module and schema in this build."""

    result = ModuleConfigurationResult.model_validate(value)
    if result.module != module:
        raise ValueError(
            f"A configuration recorded under {module!r} says it is for "
            f"{result.module!r}"
        )
    current_version = module_schema_version(parameter_model(module))
    if result.schema_version != current_version:
        raise ValueError(
            f"The {module!r} parameter schema has changed since its variants "
            "were validated. Delegate to that specialist again."
        )
    return result


def _variants(
    runtime: ToolRuntime[Any, Any],
    *,
    project_root: Path,
    thread_id: str,
) -> dict[str, list[ModuleConfigurationResult]]:
    """Recorded variants plus trusted schema defaults for untouched modules."""

    stored = state_mapping(runtime).get("module_variants")
    if stored is None:
        stored = {}
    if not isinstance(stored, dict):
        raise ValueError("The recorded module variants are not a module mapping")

    planned = execution_order()
    missing = [module for module in planned if module not in stored]
    required = [module for module in missing if module not in AUTO_DEFAULT_MODULES]
    if required:
        raise ValueError(
            "These modules have no validated variants: "
            + ", ".join(required)
            + ". READIN must be delegated because its staged input path has no "
            "runnable schema default."
        )
    unplanned = sorted(set(stored) - set(planned))
    if unplanned:
        raise ValueError("These variants belong to no pipeline module: " + ", ".join(unplanned))

    variants: dict[str, list[ModuleConfigurationResult]] = {}
    for module in planned:
        if module not in stored:
            model = parameter_model(module)
            variants[module] = [
                validate_module_parameters(
                    {},
                    module=module,
                    model=model,
                    schema_version=module_schema_version(model),
                    project_root=project_root,
                    thread_id=thread_id,
                )
            ]
            continue
        entries = stored[module]
        if not isinstance(entries, list) or not entries:
            raise ValueError(f"The variants recorded for {module} are not a non-empty list")
        validated = [_current_result(module, entry) for entry in entries]
        variants[module] = validated
    return variants


def _combination_size(
    variants: dict[str, list[ModuleConfigurationResult]],
    combination: str,
) -> int:
    """Return the expansion size without constructing the expansion."""

    planned = list(execution_order())
    if combination == "cartesian":
        return prod(len(variants[module]) for module in planned)
    if combination != "paired":
        raise ValueError(f"Unknown sweep combination: {combination!r}")

    lengths = {len(variants[module]) for module in planned}
    width = max(lengths)
    uneven = [
        module for module in planned if len(variants[module]) not in (1, width)
    ]
    if uneven:
        raise ValueError(
            "A paired sweep needs every module to have the same number of "
            f"variants, or exactly one to reuse. These have neither: "
            + ", ".join(f"{module} ({len(variants[module])})" for module in uneven)
            + f"; the widest is {width}."
        )
    return width


def _combine(
    variants: dict[str, list[ModuleConfigurationResult]],
    combination: str,
) -> list[dict[str, ModuleConfigurationResult]]:
    """Expand the per-module variants into one configuration set per run.

    'paired' is the case the first-generation prompt had to explain at length,
    because a model reads `[(1,1), (2,2), (3,3)]` as three setups and a Cartesian
    product reads it as nine. Here it is a named argument rather than something
    inferred from the shape of what the model sent.
    """

    planned = list(execution_order())
    if combination == "cartesian":
        return [
            dict(zip(planned, chosen, strict=True))
            for chosen in product(*(variants[module] for module in planned))
        ]

    width = _combination_size(variants, combination)
    return [
        {
            module: variants[module][index if len(variants[module]) > 1 else 0]
            for module in planned
        }
        for index in range(width)
    ]


def _render_matrix(
    entries: list[SimulationPlanEntry],
    *,
    combination: str,
) -> bytes:
    """Render the plan as the readable file the sweep can be checked against.

    Rendered from the plan rather than being the plan's source, so editing it
    changes nothing that runs.
    """

    document = {
        "metadata": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "combination": combination,
            "total_simulations": len(entries),
            "note": (
                "Rendered from the recorded simulation plan for review. Editing "
                "this file changes nothing: the plan is what executes."
            ),
        },
        "simulations": [
            {
                "run_name": entry.run_name,
                "simulation_run_id": str(entry.simulation_run_id),
                "modules": {
                    module: result.parameters
                    for module, result in entry.modules.items()
                },
                "arguments": {
                    module: parameters_to_arguments(
                        parameter_model(module)(**result.parameters)
                    )
                    for module, result in entry.modules.items()
                },
            }
            for entry in entries
        ],
    }
    return json.dumps(document, indent=2).encode("utf-8")


def build_batch_tools(
    gateway: VitessGateway,
    *,
    project_root: str | Path | None = None,
) -> list[BaseTool]:
    """Build the sweep's two tools over the one MCP gateway."""

    root = Path(project_root or "/data/projects").expanduser().resolve()

    @tool(
        "write_simulation_matrix",
        args_schema=_SweepArguments,
        description=(
            "Expand the validated module variants into the runs of this sweep "
            "and record the plan. Say whether the variants combine as a "
            "Cartesian product or as paired rows. Untouched guide, writeout, and "
            "monitor modules receive exact schema defaults in trusted code."
        ),
    )
    def write_simulation_matrix(
        runtime: ToolRuntime[Any, Any],
        combination: Literal["cartesian", "paired"],
        run_names: list[str] | None = None,
    ) -> Command:
        try:
            user_id, thread_id, graph_run_id = runtime_identity(runtime)
            variants = _variants(
                runtime,
                project_root=root,
                thread_id=thread_id,
            )
            combination_size = _combination_size(variants, combination)
        except (ValidationError, ValueError) as exc:
            return Command(
                update={"messages": [tool_message(runtime, str(exc), error=True)]}
            )

        if combination_size > MAX_SWEEP_RUNS:
            return Command(
                update={
                    "messages": [
                        tool_message(
                            runtime,
                            f"That combination is {combination_size} simulations, over "
                            f"the limit of {MAX_SWEEP_RUNS}. A sweep this wide is "
                            "usually a Cartesian product where paired rows were "
                            "meant. Check with the user which they want before "
                            "expanding it.",
                            error=True,
                        )
                    ]
                }
            )

        combined = _combine(variants, combination)

        names = list(run_names or [])
        if names and len(names) != len(combined):
            return Command(
                update={
                    "messages": [
                        tool_message(
                            runtime,
                            f"{len(names)} run names were given for "
                            f"{len(combined)} simulations.",
                            error=True,
                        )
                    ]
                }
            )
        if len(set(names)) != len(names):
            return Command(
                update={
                    "messages": [
                        tool_message(
                            runtime, "Run names must be distinct.", error=True
                        )
                    ]
                }
            )

        try:
            entries = [
                SimulationPlanEntry(
                    run_name=names[index] if names else f"run {index + 1}",
                    # Generated here, by trusted code. The model names runs; it does
                    # not name directories.
                    simulation_run_id=uuid4(),
                    modules=modules,
                )
                for index, modules in enumerate(combined)
            ]
        except ValidationError as exc:
            return Command(
                update={
                    "messages": [
                        tool_message(runtime, f"Run names are not valid: {exc}", error=True)
                    ]
                }
            )
        normalized_names = [entry.run_name for entry in entries]
        if len(set(normalized_names)) != len(normalized_names):
            return Command(
                update={
                    "messages": [
                        tool_message(runtime, "Run names must be distinct.", error=True)
                    ]
                }
            )

        rendered = _render_matrix(entries, combination=combination)
        delivered = ""
        try:
            from juena_core.artifacts import get_artifact_store

            reference = get_artifact_store().register_artifact(
                user_id=user_id,
                thread_id=thread_id,
                run_id=graph_run_id,
                filename=MATRIX_FILENAME,
                content=rendered,
                caption="Simulation matrix",
            )
            delivered = f" The matrix is attached as {reference.filename} for review."
        except (OSError, ValueError) as exc:
            delivered = f" The matrix could not be attached for review: {exc}"

        summary = ", ".join(
            f"{entry.run_name}" for entry in entries[:6]
        ) + ("…" if len(entries) > 6 else "")
        return Command(
            update={
                "messages": [
                    tool_message(
                        runtime,
                        f"Planned {len(entries)} simulation(s) as a "
                        f"{combination} sweep: {summary}.{delivered}",
                    )
                ],
                "simulation_plan": [entry.model_dump(mode="json") for entry in entries],
            }
        )

    @tool(
        "run_batch_from_matrix",
        args_schema=_BatchArguments,
        description=(
            "Run every simulation in the recorded plan, one after another, and "
            "report what each one did. Takes no arguments: it runs the plan "
            "`write_simulation_matrix` recorded and nothing else."
        ),
    )
    async def run_batch_from_matrix(runtime: ToolRuntime[Any, Any]) -> Command:
        try:
            user_id, thread_id, graph_run_id = runtime_identity(runtime)
        except ValueError as exc:
            return Command(
                update={"messages": [tool_message(runtime, str(exc), error=True)]}
            )

        stored = state_mapping(runtime).get("simulation_plan")
        if not isinstance(stored, list) or not stored:
            return Command(
                update={
                    "messages": [
                        tool_message(
                            runtime,
                            "There is no simulation plan to run. Call "
                            "write_simulation_matrix first.",
                            error=True,
                        )
                    ]
                }
            )
        try:
            plan = [SimulationPlanEntry.model_validate(entry) for entry in stored]
        except ValidationError as exc:
            return Command(
                update={
                    "messages": [
                        tool_message(
                            runtime, f"The recorded plan is not usable: {exc}", error=True
                        )
                    ]
                }
            )
        if len(plan) > MAX_SWEEP_RUNS:
            event = ExecutionEvidence(
                graph_run_id=graph_run_id,
                command="VITESS parameter sweep",
                status="tool_error",
                exit_code=None,
            )
            return Command(
                update={
                    "messages": [
                        tool_message(
                            runtime,
                            f"The recorded plan contains {len(plan)} simulations, "
                            f"over the limit of {MAX_SWEEP_RUNS}.",
                            error=True,
                        )
                    ],
                    "execution_events": [event.model_dump(mode="json")],
                }
            )

        planned = execution_order()
        events: list[dict[str, Any]] = []
        references: list[dict[str, Any]] = []
        lines: list[str] = []
        succeeded = 0

        for entry in plan:
            outcome_line, entry_events, reference = await _run_one(
                gateway,
                entry,
                planned=planned,
                project_root=root,
                user_id=user_id,
                thread_id=thread_id,
                graph_run_id=graph_run_id,
            )
            events.extend(entry_events)
            lines.append(outcome_line)
            if reference is not None:
                references.append(reference)
                succeeded += 1

        update: dict[str, Any] = {
            "messages": [
                tool_message(
                    runtime,
                    f"Sweep complete: {succeeded} of {len(plan)} run(s) succeeded.\n"
                    + "\n".join(lines),
                    error=succeeded != len(plan),
                )
            ],
            "execution_events": events,
        }
        if references:
            # Recorded the same way a single guided run is, so the plot tools
            # (03/CP3a) work unchanged for a sweep: one plot path, two agents.
            update["simulation_runs"] = references
        return Command(update=update)

    return [write_simulation_matrix, run_batch_from_matrix]


async def _run_one(
    gateway: VitessGateway,
    entry: SimulationPlanEntry,
    *,
    planned: tuple[str, ...],
    project_root: Path,
    user_id: str,
    thread_id: str,
    graph_run_id: str,
) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None]:
    """Execute one planned run and return its line, its evidence and its reference."""

    def failure(message: str, status: str = "tool_error") -> tuple[str, list[dict[str, Any]], None]:
        event = ExecutionEvidence(
            graph_run_id=graph_run_id,
            command=f"VITESS sweep run {entry.run_name!r}",
            status=status,  # type: ignore[arg-type]
            exit_code=None,
        )
        return (
            f"- {entry.run_name}: not run -- {message}",
            [event.model_dump(mode="json")],
            None,
        )

    missing = [module for module in planned if module not in entry.modules]
    if missing:
        return failure(f"planned modules missing from the entry: {', '.join(missing)}")
    unplanned = sorted(set(entry.modules) - set(planned))
    if unplanned:
        return failure(f"entry contains unplanned modules: {', '.join(unplanned)}")

    try:
        module_results = {
            module: {
                "cli_parameters": parameters_to_arguments(
                    parameter_model(module)(
                        **_current_result(module, entry.modules[module]).parameters
                    )
                )
            }
            for module in planned
        }
        request = InternalSimulationRequest(
            thread_id=UUID(thread_id),
            simulation_run_id=entry.simulation_run_id,
            graph_run_id=graph_run_id,
            module_results=module_results,
            execution_order=planned,
        )
    except (ValidationError, ValueError, KeyError) as exc:
        return failure(f"its configuration is not runnable: {exc}")

    outcome = await gateway.run_simulation(request)
    if outcome.result is None:
        assert outcome.failure is not None
        return (
            f"- {entry.run_name}: {outcome.failure.status} -- {outcome.failure.message}",
            [event.model_dump(mode="json") for event in outcome.events],
            None,
        )

    try:
        artifact_ids, artifact_filenames, dropped = register_run_files(
            project_root=project_root,
            user_id=user_id,
            thread_id=thread_id,
            graph_run_id=graph_run_id,
            result=outcome.result,
        )
    except ValueError as exc:
        return failure(f"VITESS returned unverifiable file metadata: {exc}")

    events = attach_artifacts(
        outcome.events,
        artifact_ids=artifact_ids,
        artifact_filenames=artifact_filenames,
        dropped=dropped,
    )
    exits = ", ".join(
        f"{module.name}=exit {module.exit_code}" for module in outcome.result.modules
    )
    if not outcome.success:
        return (f"- {entry.run_name}: failed -- {exits or outcome.result.message}", events, None)

    reference = SimulationRunReference(
        run_name=entry.run_name, simulation_run_id=entry.simulation_run_id
    )
    return (
        f"- {entry.run_name}: completed ({exits})",
        events,
        reference.model_dump(mode="json"),
    )
