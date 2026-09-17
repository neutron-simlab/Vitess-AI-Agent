"""What a module specialist hands back when it has validated its parameters.

`SpecialistReport` is prose -- status, finding, evidence, actions, limitations
-- and core's delegation boundary carries only `messages` and `files`. So once a
guide specialist has validated a `GuideParameters`, there is no typed route for
that object to reach the command builder, and the only remaining route would be
the model retyping the numbers into `run_simulation`'s arguments. That is the
model-authored path 03/CP1 exists to close, so this is the object that closes
it: the validation *tool* writes one of these into state, and the execution
façade reads the channel rather than an argument.

Deliberately absent: the CLI arguments. They are derived from `parameters` at
execution time by :func:`vitess_ai.cli.arguments.parameters_to_arguments`, so
there is only ever one answer to "what does this configuration run as". A
stored copy is a second answer, and two answers drift -- which is the first
lesson of this rebuild (02/CP2's two executable tables) applied to one module's
own parameters.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vitess_ai.schema.base import get_field_flag

__all__ = ["ModuleConfigurationResult", "module_schema_version"]


def module_schema_version(model: type[BaseModel]) -> str:
    """A short fingerprint of one parameter model's fields and CLI flags.

    Recorded with each validated configuration so that a result checkpointed
    days ago can be recognised as belonging to a schema that has since changed.
    It is computed rather than hand-maintained because a hand-maintained
    version number is one nobody remembers to raise.
    """

    material = "\n".join(
        f"{name}={get_field_flag(model, name)}" for name in model.model_fields
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return digest[:12]


class ModuleConfigurationResult(BaseModel):
    """One module's validated parameters, written by a tool and never by a model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    module: str = Field(min_length=1, max_length=64)
    validated_at: datetime
    #: Dumped from the module's own parameter model, in JSON mode, so the whole
    #: object survives a checkpoint round trip unchanged.
    parameters: dict[str, Any]
    schema_version: str = Field(min_length=1, max_length=64)
