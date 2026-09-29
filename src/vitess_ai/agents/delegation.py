"""What passes between the supervisor and a module specialist, in each direction.

Core's :class:`~juena_core.agents.delegation.SpecialistDelegate` names exactly
what may pass each way -- `messages` and `files` -- and builds both from
scratch rather than filtering out what should not pass. So a field added to the
state elsewhere stays behind by default, instead of slipping through until
someone notices. That is still the rule here.

This app adds **one** field, in **one** direction: a specialist hands back the
`module_results` entry it checked. Without it, the guide specialist could check
a `GuideParameters` and have nowhere to put it, and the only way left to the
command builder would be the model retyping the numbers -- exactly what must not
happen.

And it hands back **only its own module's entry**. A specialist that came back
holding entries for other modules could overwrite settings it merely received,
the same argument `findings_delta` already makes for files. Here the argument
is stronger, because nothing is received at all: `module_results` is never sent
to a specialist, so the guide specialist has no honest way to know what read-in
decided, and an entry under another module's name can only be made up.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from deepagents.middleware.subagents import CompiledSubAgent
from langchain_core.runnables import Runnable

from juena_core.agents.delegation import SpecialistDelegate
from vitess_ai.state import SimulationOrderEvent

__all__ = [
    "ModuleCompiledSubAgent",
    "ModuleSpecialistDelegate",
    "with_module_delegation_boundary",
]


class ModuleCompiledSubAgent(CompiledSubAgent):
    """A compiled subagent tagged with the VITESS module it configures."""

    module: str


class ModuleSpecialistDelegate(SpecialistDelegate):
    """One module specialist, allowed to return that module's configuration.

    Guided or sweep -- the same delegate wraps both, because the rule is the
    same: one module, its own entry, nothing else.
    """

    def __init__(self, runnable: Runnable, *, name: str, module: str) -> None:
        super().__init__(runnable, name=name)
        self._module = module

    def _own(self, values: dict[str, Any], channel: str) -> Any | None:
        """This specialist's entry in one module-keyed channel, and no other's.

        Nothing sends either channel inbound, so the guide specialist has no
        legitimate way to know what read-in decided, and an entry under another
        module's name can only be something it made up.
        """
        written = values.get(channel)
        return written.get(self._module) if isinstance(written, dict) else None

    def _outbound(self, sent: dict[str, Any], result: Any) -> dict[str, Any]:
        crossing = super()._outbound(sent, result)
        values = result if isinstance(result, dict) else {}

        # The guided path writes one configuration; a sweep writes a list of
        # them. Both are this specialist's own work and both come back the same
        # way, under their own channel.
        configured = False
        for channel in ("module_results", "module_variants"):
            own = self._own(values, channel)
            if own is not None:
                crossing[channel] = {self._module: own}
                configured = True

        if configured:
            crossing["simulation_order_events"] = [
                SimulationOrderEvent(
                    kind="configured", module=self._module
                ).model_dump(mode="json")
            ]
        return crossing


def with_module_delegation_boundary(
    specialists: Sequence[ModuleCompiledSubAgent],
) -> list[CompiledSubAgent]:
    """Wrap each compiled module specialist for `SubAgentMiddleware`.

    Each entry carries a ``module`` key naming the catalog row it configures.
    It is removed here, because `SubAgentMiddleware` reads only ``name``,
    ``description`` and ``runnable`` -- the module name lives on in the
    delegate, which is the thing that needs it.
    """

    wrapped: list[CompiledSubAgent] = []
    for spec in specialists:
        wrapped_spec: CompiledSubAgent = {
            "name": spec["name"],
            "description": spec["description"],
            "runnable": ModuleSpecialistDelegate(
                spec["runnable"], name=spec["name"], module=spec["module"]
            ),
        }
        if "mode" in spec:
            wrapped_spec["mode"] = spec["mode"]
        wrapped.append(wrapped_spec)
    return wrapped
