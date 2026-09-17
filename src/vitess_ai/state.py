"""Private state channels owned by the VITESS application bridge."""

from __future__ import annotations

import operator
from collections.abc import Mapping
from typing import Annotated, Any, NotRequired
from uuid import UUID

from langchain.agents.middleware.types import PrivateStateAttr
from pydantic import BaseModel, ConfigDict, Field

from juena_core.agents.specialist_outcome import SpecialistOutcomeState

__all__ = [
    "SimulationRunReference",
    "VitessBridgeState",
    "merge_module_results",
]


class SimulationRunReference(BaseModel):
    """A human label paired with the trusted identifier it may never replace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_name: str = Field(min_length=1, max_length=120)
    simulation_run_id: UUID


def merge_module_results(
    left: Mapping[str, Any] | None,
    right: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Merge validated module configurations by module name.

    Re-validating one module replaces that module's entry and disturbs nothing
    else, which is what makes "go back and change the guide" cheap. Plain
    assignment would make it destructive: the last specialist to return would
    be the only module left configured.
    """

    merged = dict(left or {})
    merged.update(right or {})
    return merged


class VitessBridgeState(SpecialistOutcomeState):
    """The channels the VITESS agents add to core's specialist-outcome state."""

    #: Written by `run_simulation`, read by the plot façades so a plot names a
    #: run the server generated rather than an identifier a model invented.
    simulation_runs: NotRequired[
        Annotated[list[SimulationRunReference], operator.add, PrivateStateAttr]
    ]
    #: Written by `plan_simulation` from the catalog, read by `run_simulation`.
    #: Both ends are server-owned, which is the only reason comparing them
    #: proves anything. Last write wins: re-planning replaces the plan.
    planned_execution_order: NotRequired[Annotated[list[str], PrivateStateAttr]]
    #: One `ModuleConfigurationResult`, dumped to JSON, per configured module.
    #:
    #: **Not `PrivateStateAttr`, and that is load-bearing.** This channel is the
    #: one that has to survive the trip *out* of a specialist, and
    #: `SubAgentMiddleware` drops private keys from a subagent's returned state
    #: (`deepagents/middleware/subagents.py`, `_return_command_with_state_update`).
    #: Marking it private would leave every module unconfigured with no error --
    #: the specialists would report success and `run_simulation` would refuse a
    #: pipeline nobody had configured. `execution_events` can be private because
    #: `run_simulation` runs at the root and never crosses that boundary.
    module_results: NotRequired[Annotated[dict[str, Any], merge_module_results]]
