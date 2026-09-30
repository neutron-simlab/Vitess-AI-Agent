"""Which settings model belongs to which VITESS module.

This is kept out of `catalog.py` on purpose. The catalog imports pydantic and
nothing else, and a test checks that, because the first version ended up with
two copies of the module-to-program list precisely because its catalog imported
an agent class. This mapping has to import the settings models, so it lives
next to the catalog rather than inside it.

It is a second table keyed by module name, and two such tables drift apart when
nobody compares them. So `test_every_executable_module_has_a_parameter_model`
compares them, against `execution_order(include_optional=True)`.
"""

from __future__ import annotations

from pydantic import BaseModel

from vitess_ai.schema import (
    CaptureFluxParameters,
    EvalElastParameters,
    GuideParameters,
    Monitor1DParameters,
    Monitor2DParameters,
    ReadInParameters,
    SampleElasticIsotrParameters,
    ScreenParameters,
    WriteoutParameters,
)

__all__ = ["PARAMETER_MODELS", "parameter_model"]

PARAMETER_MODELS: dict[str, type[BaseModel]] = {
    "readin": ReadInParameters,
    "guide": GuideParameters,
    "sample_elasticisotr": SampleElasticIsotrParameters,
    "writeout": WriteoutParameters,
    "monitor1d": Monitor1DParameters,
    "monitor2d": Monitor2DParameters,
    "capture_flux": CaptureFluxParameters,
    "screen": ScreenParameters,
    "eval_elast": EvalElastParameters,
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
