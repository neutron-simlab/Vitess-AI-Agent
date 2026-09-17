"""The boundary a VITESS module specialist is invoked across.

Core's :class:`~juena_core.agents.delegation.SpecialistDelegate` names exactly
what may cross in each direction -- `messages` and `files` -- and builds both
from scratch rather than filtering, so a state field added upstream is absent by
default instead of crossing until someone notices. That is still the rule here.

v2 adds **one** field, in **one** direction: a specialist returns the
`module_results` entry it validated. Without it a guide specialist can validate
a `GuideParameters` and have nowhere to put it, and the only remaining route to
the command builder is the model retyping the numbers -- the path 03/CP1 exists
to close.

And it returns **only its own module's entry**. A specialist that came back
holding five entries would be able to overwrite configurations it merely
inherited, which is the same argument `findings_delta` already makes for files.
Here it is stronger, because the entry is not inherited at all: nothing sends
`module_results` inbound, so the guide specialist has no legitimate way to know
what read-in decided, and an entry under another module's name can only be
something it made up.
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import Runnable

from juena_core.agents.delegation import SpecialistDelegate
from vitess_ai.state import SimulationOrderEvent

__all__ = ["ModuleSpecialistDelegate", "with_module_delegation_boundary"]


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
    specialists: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Wrap each compiled module specialist for `SubAgentMiddleware`.

    Each entry carries a ``module`` key naming the catalog row it configures.
    It is removed here, because `SubAgentMiddleware` reads only ``name``,
    ``description`` and ``runnable`` -- the module name lives on in the
    delegate, which is the thing that needs it.
    """

    wrapped: list[dict[str, Any]] = []
    for spec in specialists:
        fields = dict(spec)
        module = fields.pop("module")
        wrapped.append(
            {
                **fields,
                "runnable": ModuleSpecialistDelegate(
                    spec["runnable"], name=spec["name"], module=module
                ),
            }
        )
    return wrapped
