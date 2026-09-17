"""Which parameter model belongs to which VITESS module.

Kept out of `catalog.py` on purpose: the catalog imports pydantic and nothing
else, and a test asserts it, because the whole reason the first-generation
agent grew two copies of the executable mapping was that its catalog imported
an agent class. This mapping imports the five parameter models, so it lives
beside the catalog rather than inside it.

It is a second table keyed by module name, and the way two such tables drift is
that nobody compares them. So `test_every_executable_module_has_a_parameter_model`
does, against `execution_order()`.
"""

from __future__ import annotations

from pydantic import BaseModel

from vitess_ai.schema import (
    GuideParameters,
    Monitor1DParameters,
    Monitor2DParameters,
    ReadInParameters,
    WriteoutParameters,
)

__all__ = ["PARAMETER_MODELS", "parameter_model"]

PARAMETER_MODELS: dict[str, type[BaseModel]] = {
    "readin": ReadInParameters,
    "guide": GuideParameters,
    "writeout": WriteoutParameters,
    "monitor1d": Monitor1DParameters,
    "monitor2d": Monitor2DParameters,
}


def parameter_model(module: str) -> type[BaseModel]:
    """Return one module's parameter model, or raise naming what is known."""
    try:
        return PARAMETER_MODELS[module]
    except KeyError:
        known = ", ".join(sorted(PARAMETER_MODELS))
        raise KeyError(
            f"No VITESS parameter model for {module!r}. Known modules: {known}"
        ) from None
