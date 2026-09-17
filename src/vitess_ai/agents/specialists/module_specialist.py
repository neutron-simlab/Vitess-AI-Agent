"""What the five VITESS module specialists have in common.

Each of the five is an explicit builder in its own package, listing its own
module, its own parameter model and its own `AGENT.md`. What they share is
assembly, and it is shared rather than copied because the first-generation
agent copied it: five `*_params_to_cli` functions that had already drifted, and
five prompts that repeated the same paragraph with one word changed. Sharing
the assembly is the opposite of a registry -- nothing here discovers anything,
and adding a sixth module still means writing a package and adding one line to
`compile_module_specialists`.

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

from deepagents.middleware.subagents import CompiledSubAgent
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, InjectedToolArg
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.json_schema import SkipJsonSchema

from juena_core.agents.specialist_runtime import (
    build_specialist_backend,
    build_specialist_middleware,
    load_markdown,
)
from juena_core.llms_providers import build_chat_model
from juena_core.schema.agents import SpecialistReport
from juena_core.schema.llm_models import BlabladorModelName, Provider
from juena_core.server.agent.runtime_model_middleware import RuntimeModelContext
from vitess_ai.cli.arguments import ParameterConversionError, parameters_to_arguments
from vitess_ai.schema.module_result import (
    ModuleConfigurationResult,
    module_schema_version,
)
from vitess_ai.state import VitessBridgeState

__all__ = [
    "SPECIALIST_PROVIDER",
    "SPECIALIST_MODEL",
    "FILESYSTEM_TOOLS",
    "FILESYSTEM_TOOL_DESCRIPTIONS",
    "build_module_prompt",
    "build_module_specialist",
    "build_staged_files_tool",
    "build_validation_tool",
    "omitted_file_value",
    "plain_filename",
    "staged_upload_path",
]

#: Pinned, like juena's specialists. The user's model choice is the
#: supervisor's; turning a conversation into validated parameters is the
#: application's job and should not change under it.
SPECIALIST_PROVIDER = Provider.BLABLADOR.value
SPECIALIST_MODEL = BlabladorModelName.GPT_OSS.value

#: No filesystem at all. A module specialist's whole job is a conversation and
#: one validation call, and `FilesystemMiddleware` otherwise binds eight tools
#: -- `ls`, `read_file`, `write_file`, `edit_file`, `delete`, `glob`, `grep` and
#: **`execute`** -- which is context spent on tools it will never use and, on a
#: weaker model, an invitation to use them.
#:
#: The allowlist was `("read_file",)` for one checkpoint, on the theory that a
#: later module could read a finding an earlier one recorded. It could not. A
#: `/findings/` file only exists because some specialist called `write_file`,
#: none of these five has it, and without `ls` or `glob` there is no way to
#: discover a path to read either. **These specialists hand off through
#: `module_results`, a typed state channel, not through files** -- so the tool
#: was dead, and the prompt paragraph describing it was teaching the model about
#: something that does not happen. `read_file` is mandatory in any allowlist the
#: middleware accepts, so `None` -- mount the middleware not at all -- is the
#: only way to bind none of them.
FILESYSTEM_TOOLS = None

FILESYSTEM_TOOL_DESCRIPTIONS: dict[str, str] = {}


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
            thread_id = _thread_id(runtime)
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
            arguments = parameters_to_arguments(validated)
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

        result = ModuleConfigurationResult(
            module=module,
            validated_at=datetime.now(timezone.utc),
            parameters=validated.model_dump(mode="json"),
            schema_version=version,
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


def build_module_specialist(
    *,
    module: str,
    name: str,
    description: str,
    prompt_package: str,
    model: type[BaseModel],
    tools: list[BaseTool],
    summarizer_model: Any,
    fallback_models: list[Any],
) -> CompiledSubAgent:
    """Compile one module specialist from the pieces its own package chose.

    `tools` comes from that package's ``tools.py``, which is where the decision
    of what this module needs belongs -- read-in has staged files to look at,
    monitor2D has none. This function only assembles.

    The returned dictionary carries a ``module`` key beyond the three
    `SubAgentMiddleware` reads. `with_module_delegation_boundary` takes it off
    again; it is what tells the boundary whose configuration this specialist is
    allowed to hand back.
    """

    runnable = create_agent(
        model=build_chat_model(
            provider=SPECIALIST_PROVIDER, model=SPECIALIST_MODEL, temperature=0.0
        ),
        tools=tools,
        system_prompt=build_module_prompt(prompt_package, model),
        middleware=build_specialist_middleware(
            backend=build_specialist_backend(),
            summarizer_model=summarizer_model,
            fallback_models=fallback_models,
            filesystem_tool_descriptions=FILESYSTEM_TOOL_DESCRIPTIONS,
            specialist_name=name,
            filesystem_tools=FILESYSTEM_TOOLS,
        ),
        response_format=ToolStrategy(SpecialistReport),
        context_schema=RuntimeModelContext,
        state_schema=VitessBridgeState,
        name=f"vitess_{module}_specialist",
    )
    return {
        "name": name,
        "description": description,
        "runnable": runnable,
        "module": module,
    }


def build_module_prompt(prompt_package: str, model: type[BaseModel]) -> str:
    """The authored prompt, followed by the module's own parameter schema.

    The first-generation prompts interpolated `model_json_schema()` into a
    Python f-string, which is why they could not be read as prose and why the
    schema and the instructions drifted apart. The prose is `AGENT.md` now and
    the schema is appended at build time, so the schema is by construction the
    one the validation tool will enforce.
    """
    authored = load_markdown(prompt_package, "AGENT.md")
    schema = json.dumps(model.model_json_schema(), indent=2)
    return (
        f"{authored}\n## The parameter schema you must satisfy\n\n"
        f"This is `{model.__name__}`, and it is what your validation tool "
        "checks against. Field descriptions begin with the VITESS command-line "
        "flag the value becomes.\n\n"
        f"```json\n{schema}\n```\n"
    )
