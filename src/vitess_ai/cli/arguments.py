"""Turn one validated parameter model into the VITESS arguments it runs as.

The first-generation agent had five of these -- `readin_params_to_cli`,
`guide_params_to_cli`, `writeout_params_to_cli` and one per monitor -- and they
had already drifted apart: only writeout converted booleans to ``1``/``0``,
only the monitors skipped a field whose flag was missing, and only read-in
understood a field that carries one flag per list element. A parameter that
moved between modules would therefore be spelled differently depending on which
copy happened to convert it.

So there is one function, and it handles the three shapes the five schemas
actually contain -- measured, not guessed:

======================  ===========================================
``sInputFileName``      a list whose flag is really three flags,
``Weight``              ``"-A -B -D"``, one per element position
``output_flags``        a nested model whose fields all share ``-c``
``filter_limits``       a nested model whose fields each have their own
everything else         one flag, one value
======================  ===========================================

**A field with no flag raises.** The monitor converters skipped it with a
comment explaining that a bare value would otherwise land in the command; the
result is that a parameter the user asked for is silently absent from the
simulation, which is 03/CP1's defect wearing different clothes. 03/CP0's flag
test means this cannot happen without an edit to the schema, and if someone
makes that edit the failure should be a loud one.
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
        return "1" if value else "0"
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


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
