"""One run of a parameter sweep, as a tool recorded it -- not as the model typed it.

The guided agent keeps **one** checked configuration per module, in
`module_results`. A sweep needs *N* per module -- that is what a sweep is -- so
the sweep has a place of its own, shaped and filled the same way: by a tool,
through `Command(update=...)`, never by the model.

The first version did it the other way: its batch tool took the list of runs,
settings included, straight from the model. So the sweep agent could still run
VITESS with values the model typed, even after that was stopped for single
simulations. **Closing it in one agent and leaving it open in the other is worse
than not closing it, because the fix looks done.**

A run has two names, and they are not the same thing:

``run_name``
    Readable and **chosen by the model**: "m=3 guide, 2 A" is a good name. It
    names a run in the conversation and in a summary. It is not an identifier.

``simulation_run_id``
    A UUID made by trusted application code, one per VITESS run. It names the
    output folder. The first version passed the run name straight through as
    the run id, so whatever the model called a run became a folder name on a
    shared volume.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from vitess_ai.schema.module_result import ModuleConfigurationResult

__all__ = ["MAX_SWEEP_RUNS", "SimulationPlanEntry"]

#: One limit shared by variant collection, matrix expansion and execution. A
#: module cannot contribute more variants than any valid sweep could consume.
#: 36 so a full 6 x 6 grid of two parameters fits.
MAX_SWEEP_RUNS = 36


class SimulationPlanEntry(BaseModel):
    """One simulation of a sweep: what it is called, where it goes, what it runs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_name: str = Field(min_length=1, max_length=120)
    simulation_run_id: UUID
    #: One validated configuration per module, keyed by module name. The keys are
    #: checked against the catalog's execution order when the entry is executed, so
    #: a sweep cannot quietly run a four-module pipeline.
    modules: dict[str, ModuleConfigurationResult]

    @field_validator("run_name")
    @classmethod
    def clean_run_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("run name must not be blank")
        if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
            raise ValueError("run name must not contain control characters")
        return cleaned
