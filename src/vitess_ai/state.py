"""Private state channels owned by the VITESS application bridge."""

from __future__ import annotations

import operator
from typing import Annotated, NotRequired
from uuid import UUID

from langchain.agents.middleware.types import PrivateStateAttr
from pydantic import BaseModel, ConfigDict, Field

from juena_core.agents.specialist_outcome import SpecialistOutcomeState

__all__ = ["SimulationRunReference", "VitessBridgeState"]


class SimulationRunReference(BaseModel):
    """A human label paired with the trusted identifier it may never replace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_name: str = Field(min_length=1, max_length=120)
    simulation_run_id: UUID


class VitessBridgeState(SpecialistOutcomeState):
    """State CP3a adds; CP4 extends this with typed module configuration."""

    simulation_runs: NotRequired[
        Annotated[list[SimulationRunReference], operator.add, PrivateStateAttr]
    ]
