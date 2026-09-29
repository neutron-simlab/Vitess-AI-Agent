"""What a module's specialist agent hands back once its settings are checked.

A specialist's normal report (`SpecialistReport`) is written text -- status,
finding, evidence, actions, limitations -- and core only passes `messages` and
`files` back from a specialist. So once, say, the guide specialist has checked a
`GuideParameters`, there is no typed way for that object to reach the command
builder. The only way left would be for the model to retype the numbers into
`run_simulation`'s arguments, which is exactly what must not happen: the model
must never be the one typing the values that run. So the checking *tool* writes
one of these objects into the conversation state, and the code that runs VITESS
reads it from there, not from an argument.

The command-line options are deliberately not stored here. They are worked out
from `parameters` at run time by
:func:`vitess_ai.cli.arguments.parameters_to_arguments`, so there is only ever
one answer to "what command does this configuration run as". A stored copy
would be a second answer, and two answers drift apart -- the first lesson of
this rebuild, applied to one module's own settings.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["ModuleConfigurationResult", "module_schema_version"]


def module_schema_version(model: type[BaseModel]) -> str:
    """A short fingerprint of one parameter model's complete JSON schema.

    Recorded with each validated configuration so that a result checkpointed
    days ago can be recognised as belonging to a schema that has since changed.
    It is computed rather than hand-maintained because a hand-maintained
    version number is one nobody remembers to raise.  Hashing only names and
    flags is insufficient: changing a type, constraint, nested field or default
    changes what "validated" means even when the command-line flag stays put.
    """

    material = json.dumps(
        model.model_json_schema(),
        sort_keys=True,
        separators=(",", ":"),
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
