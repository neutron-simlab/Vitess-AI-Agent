"""Turn one module's checked settings into the options VITESS runs with.

The first version had five of these converters, one per module, and they had
already drifted apart: only writeout wrote true/false as ``1``/``0``, only the
monitors skipped a setting that had no flag (its command-line option), and only
read-in handled a setting that needs one flag per list item. So the same setting
could come out spelled differently, depending on which copy converted it.

Now there is one function. It handles the three shapes the module settings
schemas actually contain (checked against the schemas, not guessed):

======================  ===========================================
``sInputFileName``      a list whose flag is really three flags,
``Weight``              ``"-A -B -D"``, one per position in the list
``output_flags``        a group of settings that all share ``-c``
``filter_limits``       a group of settings, each with its own flag
everything else         one flag, one value
======================  ===========================================

**A setting with no flag is an error.** The old monitor converters quietly
skipped it, so a setting the user asked for was simply missing from the
simulation. A test already checks that every setting in the schemas has a flag,
so this can only happen after someone edits a schema -- and then it should fail
loudly.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from vitess_ai.schema.base import get_field_flag

__all__ = ["ParameterConversionError", "parameters_to_arguments"]


class ParameterConversionError(ValueError):
    """A validated model could not be expressed as VITESS arguments."""


def _scalar(value: object) -> str:
    """Render one value the way the VITESS command line expects it."""
    if isinstance(value, bool):
        # Checked before int, because bool is a subclass of int in Python and
        # `str(True)` would otherwise put the word "True" on the command line.
        rendered = "1" if value else "0"
    elif isinstance(value, Enum):
        rendered = str(value.value)
    else:
        rendered = str(value)
    if "\x00" in rendered:
        raise ParameterConversionError("VITESS arguments cannot contain a NUL byte")
    return rendered


def _require_flag(model: type[BaseModel] | BaseModel, field_name: str) -> str:
    owner = model if isinstance(model, type) else type(model)
    flag = get_field_flag(owner, field_name)
    if not flag:
        raise ParameterConversionError(
            f"{owner.__name__}.{field_name} declares no CLI flag, so it cannot "
            "be put on a VITESS command line. Give it one in the schema."
        )
    return flag


def _nested_arguments(nested: BaseModel) -> list[str]:
    """Convert a nested model, which is one of two shapes.

    ``output_flags`` is nine booleans that all carry ``-c``: VITESS wants them
    as a single ``-c111111111`` bit string, in field order. ``filter_limits``
    is twelve numbers with twelve different flags, so each becomes its own
    argument. Told apart by counting the distinct flags rather than by naming
    the field, because the rule is about the shape and not about the name.
    """
    flags = [_require_flag(nested, name) for name in type(nested).model_fields]
    values = [getattr(nested, name) for name in type(nested).model_fields]

    if len(set(flags)) == 1 and all(isinstance(value, bool) for value in values):
        return [flags[0] + "".join(_scalar(value) for value in values)]

    return [
        flag + _scalar(value)
        for flag, value in zip(flags, values, strict=True)
        if value is not None and value != ""
    ]


def _list_arguments(field_name: str, flag: str, values: list[object]) -> list[str]:
    """Spread a list over the several flags its field declares.

    ``sInputFileName`` declares ``"-A -B -D"``: the first input file is ``-A``,
    the second ``-B``, the third ``-D``. More files than flags is not something
    to truncate quietly -- the missing file would simply not be read, and the
    run would succeed with less beam than the user asked for.
    """
    per_element = flag.split()
    if len(values) > len(per_element):
        raise ParameterConversionError(
            f"{field_name} has {len(values)} values but only {len(per_element)} "
            f"flags ({flag}); VITESS cannot be given the rest."
        )
    return [
        per_element[index] + _scalar(value)
        for index, value in enumerate(values)
        if value is not None and value != ""
    ]


def parameters_to_arguments(parameters: BaseModel) -> list[str]:
    """Return the ``cli_parameters`` list for one validated module model.

    The result is what `generate_cli_command` (03/CP1) appends to a module's
    argument vector: each element is a single ``flag+value`` token, never a
    flag and a value as two elements, and never a string to be split by a
    shell that is not there.
    """
    arguments: list[str] = []
    for field_name in type(parameters).model_fields:
        value = getattr(parameters, field_name)
        if value is None:
            continue
        if isinstance(value, BaseModel):
            arguments.extend(_nested_arguments(value))
            continue
        if isinstance(value, (list, tuple)):
            arguments.extend(
                _list_arguments(
                    field_name,
                    _require_flag(parameters, field_name),
                    list(value),
                )
            )
            continue
        if isinstance(value, str) and not value.strip():
            # An empty string is "not set", not "set to nothing". The guide's
            # `ShapeFileName` is the case that matters: empty means no guide
            # file, and emitting a bare `-S` would make VITESS read the next
            # argument as the filename.
            continue
        arguments.append(_require_flag(parameters, field_name) + _scalar(value))
    return arguments
