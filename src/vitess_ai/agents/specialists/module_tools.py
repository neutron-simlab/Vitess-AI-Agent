"""The tools a module specialist's model calls, and the checks behind them.

Each module package's ``tools.py`` picks which of these builders it needs;
`build_module_specialist` in `module_specialist.py` binds whatever it is given.

**The validation tool writes state; the model does not.** A specialist ends by
calling `validate_<module>_parameters`, which validates the parameters through
the module's own Pydantic model and, only if that succeeds, writes a
`ModuleConfigurationResult` into the `module_results` channel with
`Command(update=...)`. A failed validation writes nothing at all: the
first-generation tool returned `{"validation_status": False, "errors": ...}` as
an ordinary result, and such a payload could travel all the way to execution --
which is why 03/CP3's server still refuses one. Here it cannot reach the
channel in the first place.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, get_args

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, InjectedToolArg
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.json_schema import SkipJsonSchema

from vitess_ai.cli.arguments import ParameterConversionError, parameters_to_arguments
from vitess_ai.schema.module_result import (
    ModuleConfigurationResult,
    module_schema_version,
)
from vitess_ai.schema.simulation_plan import MAX_SWEEP_RUNS

__all__ = [
    "build_defaults_tool",
    "build_staged_files_tool",
    "build_validation_tool",
    "build_variants_tool",
    "omitted_file_value",
    "plain_filename",
    "staged_upload_path",
    "validate_module_parameters",
]


def staged_upload_path(
    value: str,
    *,
    field_name: str,
    project_root: Path,
    thread_id: str,
    upload_module: str,
) -> str:
    """Require a parameter that names a file to name a staged upload.

    VITESS reads real files from disk, and the only files this conversation
    owns are under `{project}/{thread_id}/uploads/`. A bare name such as
    `instrument.inf` -- which is `ReadInParameters.sInstrInfIn`'s schema
    default -- would be resolved by VITESS against the run directory, where it
    does not exist, and the module would fail with an error nobody can read
    back to a cause.
    """
    uploads_root = (project_root / thread_id / "uploads" / upload_module).resolve()
    candidate = Path(value)
    if not candidate.is_absolute():
        raise ValueError(
            f"{field_name} must be the full path of a file staged for this "
            f"conversation, as `list_staged_files` reports it. Got {value!r}."
        )
    resolved = candidate.resolve()
    try:
        resolved.relative_to(uploads_root)
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must name a file beneath {uploads_root}; "
            f"{value!r} is outside this conversation's uploads/{upload_module} slot."
        ) from exc
    if not resolved.is_file():
        raise ValueError(
            f"{field_name} names {resolved}, but that staged upload does not exist."
        )
    return str(resolved)


def omitted_file_value(model: type[BaseModel], field_name: str, value: Any) -> bool:
    """Is this value the field's own way of saying "there is no file here"?

    Derived from the schema rather than from a second table of optional fields,
    because two tables of what is optional is how the prompts and the validator
    came to disagree in the first place. A file field says "no file" with:

    * ``None``, where the annotation admits it -- ``sInstrInfIn``,
      ``sTraceFileName``, ``sOutFileName``; or
    * a blank string, where the field's own default is blank, which is how
      ``GuideParameters.ShapeFileName`` documents "no shape file, omit ``-S``".

    Anything else is a value, and a value gets its shape checked. Before this
    existed the gate was ``if value:``, so a blank name was neither
    staged-path-checked nor filename-checked -- it was simply not looked at, and
    the configuration was recorded as valid. ``sInputFileName=[""]`` came back
    with the weight ``-a1.0`` and no ``-A`` at all, and read_in ran with nothing
    to read.

    **The schema decides whether "no file" is allowed here; this only decides
    whether there is a file to check.** The two must not both hold an opinion:
    ``sOutFileName`` may be blank exactly when ``bActive`` is false, which is a
    rule about another field and belongs in ``WriteoutParameters``, where it is.
    A copy of it here would refuse a configuration the schema accepts.
    """
    field = model.model_fields[field_name]
    admits_none = type(None) in get_args(field.annotation)
    if value is None:
        if not admits_none:
            raise ValueError(f"{field_name} is required and cannot be null")
        return True
    if str(value).strip():
        return False
    default = field.get_default(call_default_factory=False)
    if admits_none or (isinstance(default, str) and not default.strip()):
        return True
    raise ValueError(
        f"{field_name} must name a file; an empty name is not how this "
        f"parameter says there is none"
    )


def plain_filename(value: str, *, field_name: str) -> str:
    """Require an output filename to be a name, not a path.

    Every module runs with `--P<run directory>`, so VITESS writes its outputs
    there and a filename is all it needs. The first-generation prompts told the
    model in capital letters to supply a *full absolute path* instead, while the
    tools quietly took the basename -- so the prompt and the tool disagreed, and
    the plot tools (03/CP3), which accept a plain name only, would have rejected
    what the prompt asked for.
    """
    if (
        not value.strip()
        or len(value) > 240
        or Path(value).name != value
        or "\\" in value
        or any(ord(character) < 32 for character in value)
        or value in {".", ".."}
    ):
        raise ValueError(
            f"{field_name} must be a plain file name such as 'monitor1D.dat', "
            f"not a path. Got {value!r}."
        )
    return value


class _ValidationArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    parameters: dict[str, Any] | str = Field(
        description="The complete parameter object for this module."
    )
    runtime: Annotated[
        ToolRuntime[Any, Any],
        InjectedToolArg,
        SkipJsonSchema(),
    ]


class _StagedFilesArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    runtime: Annotated[
        ToolRuntime[Any, Any],
        InjectedToolArg,
        SkipJsonSchema(),
    ]


class _DefaultsArguments(BaseModel):
    """Only trusted runtime context; default values are deliberately not arguments."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    runtime: Annotated[
        ToolRuntime[Any, Any],
        InjectedToolArg,
        SkipJsonSchema(),
    ]


def _thread_id(runtime: ToolRuntime[Any, Any]) -> str:
    """The conversation, from the trusted invocation and from nowhere else."""
    execution_info = getattr(runtime, "execution_info", None)
    thread_id = getattr(execution_info, "thread_id", None)
    context = getattr(runtime, "context", None)
    if not thread_id:
        thread_id = getattr(context, "thread_id", None)
    if not thread_id:
        raise ValueError("This tool requires a trusted thread_id")
    return str(thread_id)


def _message(runtime: ToolRuntime[Any, Any], text: str, *, error: bool = False) -> ToolMessage:
    return ToolMessage(
        content=text,
        tool_call_id=runtime.tool_call_id,
        status="error" if error else "success",
    )


def validate_module_parameters(
    parameters: Mapping[str, Any],
    *,
    module: str,
    model: type[BaseModel],
    schema_version: str,
    project_root: Path,
    thread_id: str,
    upload_fields: Mapping[str, str] | None = None,
    output_filename_fields: tuple[str, ...] = (),
) -> ModuleConfigurationResult:
    """Validate one parameter object, or raise saying why.

    Shared by the guided agent's validation tool and the sweep's variants tool
    so that a value the sweep accepts is one the guided path would accept too.
    Two copies of this would be two definitions of "valid", and the sweep's
    would be the one nobody watches.
    """

    validated = model(**parameters)
    for field_name, upload_module in (upload_fields or {}).items():
        value = getattr(validated, field_name, None)
        values = value if isinstance(value, list) else [value]
        for item in values:
            if omitted_file_value(model, field_name, item):
                continue
            staged_upload_path(
                str(item),
                field_name=field_name,
                project_root=project_root,
                thread_id=thread_id,
                upload_module=upload_module,
            )
    for field_name in output_filename_fields:
        value = getattr(validated, field_name, None)
        if omitted_file_value(model, field_name, value):
            continue
        plain_filename(str(value), field_name=field_name)
    # Built and thrown away: a configuration that cannot be expressed as VITESS
    # arguments must fail here, not at execution time with the user gone.
    parameters_to_arguments(validated)
    return ModuleConfigurationResult(
        module=module,
        validated_at=datetime.now(timezone.utc),
        parameters=validated.model_dump(mode="json"),
        schema_version=schema_version,
    )


def build_validation_tool(
    *,
    module: str,
    model: type[BaseModel],
    project_root: Path,
    upload_fields: Mapping[str, str] | None = None,
    output_filename_fields: tuple[str, ...] = (),
) -> BaseTool:
    """Build the one tool that may write this module's configuration.

    Args:
        module: The catalog row this specialist configures.
        model: That module's parameter model, which does the real validating.
        project_root: Where uploads live, so a file parameter can be checked.
        upload_fields: Mapping from each file field to its catalog upload slot.
        output_filename_fields: Fields whose value must be a plain file name.
    """

    version = module_schema_version(model)

    @tool(
        f"validate_{module}_parameters",
        args_schema=_ValidationArguments,
        description=(
            f"Validate the complete {module} parameter object and record it for "
            "this conversation. Call it only after you have displayed the complete "
            "object and `ask_user` has returned the user's affirmative confirmation. "
            "A validation error is returned to you to fix, and nothing is recorded "
            "until it passes."
        ),
    )
    def validate(
        runtime: ToolRuntime[Any, Any],
        parameters: dict[str, Any] | str,
    ) -> Command:
        if isinstance(parameters, str):
            # Models emit an object as a JSON string often enough that refusing
            # it would cost a turn for nothing.
            try:
                parameters = json.loads(parameters)
            except json.JSONDecodeError as exc:
                return Command(
                    update={
                        "messages": [
                            _message(runtime, f"Not valid JSON: {exc}", error=True)
                        ]
                    }
                )
        if not isinstance(parameters, dict):
            return Command(
                update={
                    "messages": [
                        _message(
                            runtime,
                            f"Expected one {module} parameter object, got "
                            f"{type(parameters).__name__}.",
                            error=True,
                        )
                    ]
                }
            )

        try:
            result = validate_module_parameters(
                parameters,
                module=module,
                model=model,
                schema_version=version,
                project_root=project_root,
                thread_id=_thread_id(runtime),
                upload_fields=upload_fields,
                output_filename_fields=output_filename_fields,
            )
            arguments = parameters_to_arguments(model(**result.parameters))
        except (ValidationError, ValueError, ParameterConversionError) as exc:
            return Command(
                update={
                    "messages": [
                        _message(
                            runtime,
                            f"{module} parameters are not valid:\n{exc}",
                            error=True,
                        )
                    ]
                }
            )

        return Command(
            update={
                "messages": [
                    _message(
                        runtime,
                        f"{module} parameters are valid and recorded. VITESS will "
                        f"run them as: {' '.join(arguments)}",
                    )
                ],
                "module_results": {module: result.model_dump(mode="json")},
            }
        )

    return validate


def build_defaults_tool(
    *,
    module: str,
    model: type[BaseModel],
    project_root: Path,
    upload_fields: Mapping[str, str] | None = None,
    output_filename_fields: tuple[str, ...] = (),
) -> BaseTool:
    """Build a no-argument writer for the module's exact schema defaults.

    The guided default path used to ask the model to copy a large JSON object.
    That made "use defaults" model-authored configuration: one silently changed
    field was still a valid object and therefore indistinguishable from an
    intentional customization.  This tool accepts no parameter object at all;
    trusted code constructs and validates ``model()``.
    """

    version = module_schema_version(model)

    @tool(
        f"use_{module}_defaults",
        args_schema=_DefaultsArguments,
        description=(
            f"Record the exact {module} schema defaults. This tool accepts no "
            "parameter object, so none of the defaults can be replaced. Call it "
            "only after `ask_user` has returned affirmative confirmation of the "
            "displayed default configuration."
        ),
    )
    def use_defaults(runtime: ToolRuntime[Any, Any]) -> Command:
        try:
            result = validate_module_parameters(
                {},
                module=module,
                model=model,
                schema_version=version,
                project_root=project_root,
                thread_id=_thread_id(runtime),
                upload_fields=upload_fields,
                output_filename_fields=output_filename_fields,
            )
            arguments = parameters_to_arguments(model(**result.parameters))
        except (ValidationError, ValueError, ParameterConversionError) as exc:
            return Command(
                update={
                    "messages": [
                        _message(
                            runtime,
                            f"{module} schema defaults are not valid:\n{exc}",
                            error=True,
                        )
                    ]
                }
            )

        return Command(
            update={
                "messages": [
                    _message(
                        runtime,
                        f"Exact {module} schema defaults are valid and recorded. "
                        f"VITESS will run them as: {' '.join(arguments)}",
                    )
                ],
                "module_results": {module: result.model_dump(mode="json")},
            }
        )

    return use_defaults


class _VariantsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    parameter_sets: list[dict[str, Any]] | dict[str, Any] | str = Field(
        description=(
            "The explicit parameter overrides this module should sweep over, as "
            "a list. Omitted fields keep their schema defaults. Give one object "
            "per requested value; use [{}] for exact defaults."
        )
    )
    runtime: Annotated[
        ToolRuntime[Any, Any],
        InjectedToolArg,
        SkipJsonSchema(),
    ]


def build_variants_tool(
    *,
    module: str,
    model: type[BaseModel],
    project_root: Path,
    upload_fields: Mapping[str, str] | None = None,
    output_filename_fields: tuple[str, ...] = (),
) -> BaseTool:
    """Build the sweep's writer: N validated configurations for one module.

    The guided agent's tool records one configuration per module. A sweep needs
    several -- that is what a sweep is -- so this records a list, and
    `write_simulation_matrix` combines the lists into runs.

    **Every set is validated by the same function the guided path uses**, and
    **all or none are recorded**: a partially validated list would let a sweep
    run the sets that happened to pass while the model believed it had asked for
    more, and the missing runs are invisible in the results.
    """

    version = module_schema_version(model)

    @tool(
        f"validate_{module}_variants",
        args_schema=_VariantsArguments,
        description=(
            f"Validate every explicit {module} override set this sweep should run "
            "and record them together. Omitted fields retain schema defaults; "
            "[{{}}] means exact defaults. Nothing is recorded unless every set "
            "is valid."
        ),
    )
    def validate_variants(
        runtime: ToolRuntime[Any, Any],
        parameter_sets: list[dict[str, Any]] | dict[str, Any] | str,
    ) -> Command:
        if isinstance(parameter_sets, str):
            try:
                parameter_sets = json.loads(parameter_sets)
            except json.JSONDecodeError as exc:
                return Command(
                    update={"messages": [_message(runtime, f"Not valid JSON: {exc}", error=True)]}
                )
        if isinstance(parameter_sets, dict):
            # One object where a list was asked for is a near miss, not a bug.
            parameter_sets = [parameter_sets]
        if not isinstance(parameter_sets, list) or not parameter_sets:
            return Command(
                update={
                    "messages": [
                        _message(
                            runtime,
                            f"Expected a non-empty list of {module} parameter "
                            f"objects, got {type(parameter_sets).__name__}.",
                            error=True,
                        )
                    ]
                }
            )
        if len(parameter_sets) > MAX_SWEEP_RUNS:
            return Command(
                update={
                    "messages": [
                        _message(
                            runtime,
                            f"{len(parameter_sets)} variants for {module} exceeds "
                            f"the limit of {MAX_SWEEP_RUNS}. A sweep this wide is "
                            "almost always a mistake in how the values were "
                            "expanded; check with the user before growing it.",
                            error=True,
                        )
                    ]
                }
            )

        validated: list[ModuleConfigurationResult] = []
        for index, parameters in enumerate(parameter_sets):
            if not isinstance(parameters, dict):
                return Command(
                    update={
                        "messages": [
                            _message(
                                runtime,
                                f"{module} variant {index + 1} is a "
                                f"{type(parameters).__name__}, not a parameter object.",
                                error=True,
                            )
                        ]
                    }
                )
            try:
                validated.append(
                    validate_module_parameters(
                        parameters,
                        module=module,
                        model=model,
                        schema_version=version,
                        project_root=project_root,
                        thread_id=_thread_id(runtime),
                        upload_fields=upload_fields,
                        output_filename_fields=output_filename_fields,
                    )
                )
            except (ValidationError, ValueError, ParameterConversionError) as exc:
                return Command(
                    update={
                        "messages": [
                            _message(
                                runtime,
                                f"{module} variant {index + 1} of "
                                f"{len(parameter_sets)} is not valid, so none were "
                                f"recorded:\n{exc}",
                                error=True,
                            )
                        ]
                    }
                )

        return Command(
            update={
                "messages": [
                    _message(
                        runtime,
                        f"Recorded {len(validated)} validated {module} "
                        f"configuration(s) for this sweep.",
                    )
                ],
                "module_variants": {
                    module: [item.model_dump(mode="json") for item in validated]
                },
            }
        )

    return validate_variants


def build_staged_files_tool(
    *,
    module: str,
    gateway: Any,
    project_root: Path,
    upload_modules: tuple[str, ...] | None = None,
) -> BaseTool:
    """Build a read-only view of what the user has staged for one module.

    The store is the authority, not the transcript: a file can be uploaded or
    replaced between turns, and a specialist that remembers the last answer
    will build a command against a file that is no longer there.
    """

    visible_modules = upload_modules or (module,)

    @tool(
        "list_staged_files",
        args_schema=_StagedFilesArguments,
        description=(
            f"List the files the user has uploaded for the {module} configuration "
            f"in this conversation ({', '.join(visible_modules)} slots), with "
            "the full path each parameter needs."
        ),
    )
    async def list_staged_files(runtime: ToolRuntime[Any, Any]) -> ToolMessage:
        try:
            thread_id = _thread_id(runtime)
        except ValueError as exc:
            return _message(runtime, str(exc), error=True)
        response = await gateway.inspect_thread(thread_id)
        if response.failure is not None:
            return _message(
                runtime,
                f"The VITESS file service is unavailable: {response.failure.message}",
                error=True,
            )
        staged = [
            upload
            for upload in response.value.uploads
            if upload.module in visible_modules
        ]
        files = [
            {
                "module": upload.module,
                "path": str(project_root / thread_id / item.path),
                "size_bytes": item.size_bytes,
            }
            for upload in staged
            for item in upload.files
        ]
        if not files:
            return _message(
                runtime,
                f"No files are staged for {module} in this conversation.",
            )
        return _message(runtime, json.dumps(files, separators=(",", ":")))

    return list_staged_files
