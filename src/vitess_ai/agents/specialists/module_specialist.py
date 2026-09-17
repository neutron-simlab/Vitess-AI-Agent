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
from typing import Annotated, Any

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
    UNATTENDED_NOTICE,
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
    "SWEEP_NOTICE",
    "FILESYSTEM_TOOLS",
    "FILESYSTEM_TOOL_DESCRIPTIONS",
    "build_module_prompt",
    "build_module_specialist",
    "build_staged_files_tool",
    "build_validation_tool",
    "build_variants_tool",
    "validate_module_parameters",
    "plain_filename",
    "staged_upload_path",
]

#: Pinned, like juena's specialists. The user's model choice is the
#: supervisor's; turning a conversation into validated parameters is the
#: application's job and should not change under it.
SPECIALIST_PROVIDER = Provider.BLABLADOR.value
SPECIALIST_MODEL = BlabladorModelName.GPT_OSS.value

#: A module specialist's whole job is a conversation and one validation call.
#: `FilesystemMiddleware` otherwise binds eight tools -- `ls`, `read_file`,
#: `write_file`, `edit_file`, `delete`, `glob`, `grep` and **`execute`** -- and
#: a specialist bound to ten tools it will never use spends context on them and,
#: on a weaker model, reaches for them. `read_file` is the one the middleware
#: requires in any allowlist, and it is the one that earns its place: the
#: delegation boundary carries `/findings/` in, so a later module can read what
#: an earlier one recorded.
FILESYSTEM_TOOLS = ("read_file",)

FILESYSTEM_TOOL_DESCRIPTIONS = {
    "read_file": (
        "Read a finding an earlier module specialist recorded under `/findings/`. "
        "There is nothing else to read; the parameters you need come from the "
        "user, and the files the user uploaded are listed by `list_staged_files`."
    ),
}


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
            if item:
                staged_upload_path(
                    str(item),
                    field_name=field_name,
                    project_root=project_root,
                    thread_id=thread_id,
                    upload_module=upload_module,
                )
    for field_name in output_filename_fields:
        value = getattr(validated, field_name, None)
        if value:
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
            "this conversation. Call it once you have every value; a validation "
            "error is returned to you to fix, and nothing is recorded until it "
            "passes."
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


class _VariantsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    parameter_sets: list[dict[str, Any]] | str = Field(
        description=(
            "Every parameter object this module should sweep over, as a list. "
            "Give one object per value of the parameter being varied; give a "
            "single-element list when this module does not vary."
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
    max_variants: int = 64,
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
            f"Validate every {module} parameter object this sweep should run and "
            "record them together. Give a single-element list when this module "
            "does not vary. Nothing is recorded unless every set is valid."
        ),
    )
    def validate_variants(
        runtime: ToolRuntime[Any, Any],
        parameter_sets: list[dict[str, Any]] | str,
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
        if len(parameter_sets) > max_variants:
            return Command(
                update={
                    "messages": [
                        _message(
                            runtime,
                            f"{len(parameter_sets)} variants for {module} exceeds "
                            f"the limit of {max_variants}. A sweep this wide is "
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
    unattended: bool = False,
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
        system_prompt=build_module_prompt(
            prompt_package, model, unattended=unattended
        ),
        middleware=build_specialist_middleware(
            backend=build_specialist_backend(),
            summarizer_model=summarizer_model,
            fallback_models=fallback_models,
            filesystem_tool_descriptions=FILESYSTEM_TOOL_DESCRIPTIONS,
            specialist_name=name,
            filesystem_tools=FILESYSTEM_TOOLS,
            unattended=unattended,
        ),
        response_format=ToolStrategy(SpecialistReport),
        context_schema=RuntimeModelContext,
        state_schema=VitessBridgeState,
        name=f"vitess_{module}_{'sweep' if unattended else 'specialist'}",
    )
    return {
        "name": name,
        "description": description,
        "runnable": runnable,
        "module": module,
    }


SWEEP_NOTICE = """
This run is part of a **parameter sweep**, not a guided conversation. Everything above
about *what the values mean* -- the ranges, the units, the file rules, the physics, the
defaults -- applies unchanged. What changes is how you are asked and how you answer.

**There is no user to ask.** You have no `ask_user` tool, and nobody is watching this
run. Every instruction above that says "ask the user", "offer the choice" or "wait for
the user to provide" becomes, here: **use the schema default**, unless the objective
you were given says otherwise. If the objective does not mention a parameter, it keeps
its default. Do not stop to ask; there is nothing to stop for.

**You own parameter interpretation and generation.** The objective gives you intent --
"vary FactInt with values [0.1, 0.5, 1, 2]", "the guide's eGuideShapeY should be
linear" -- and it is your job to turn that into complete, valid parameter objects. Do
not expect the orchestrator to fill anything in; it does not know this module's fields
and must not guess at them. If the objective is genuinely ambiguous, choose the reading
the schema supports, say which reading you chose in your report, and record it under
`limitations`.

**You validate a list, not one object.** Your validation tool is
`validate_{module}_variants` and it takes `parameter_sets` -- every configuration this
module should sweep over.

- If the objective names values to vary, produce **one complete parameter object per
  value**. The objects are identical apart from the field being varied: build the full
  object once, then repeat it with each value substituted.
- If the objective names no variation for this module, send a **single-element list**
  holding the defaults. A module that does not vary still has to be validated; a module
  with no variation is not a module with no configuration.

**Either every set is valid or none are recorded.** A partly validated list would run
the sets that happened to pass while the objective asked for more, and the missing runs
would be invisible in the results. So if one set fails, fix it and call the tool again
with the whole list. Do not drop the failing set and continue.

**Your report is the deliverable.** Say how many configurations you recorded and what
varies between them. Put anything you could not settle in `limitations` -- an honest gap
there is worth far more than a guess, because the orchestrator can act on a gap and
cannot act on a guess.
"""


def build_module_prompt(
    prompt_package: str,
    model: type[BaseModel],
    *,
    unattended: bool = False,
) -> str:
    """The authored prompt, followed by the module's own parameter schema.

    The first-generation prompts interpolated `model_json_schema()` into a
    Python f-string, which is why they could not be read as prose and why the
    schema and the instructions drifted apart. The prose is `AGENT.md` now and
    the schema is appended at build time, so the schema is by construction the
    one the validation tool will enforce.
    """
    authored = load_markdown(prompt_package, "AGENT.md")
    if unattended:
        module = prompt_package.rsplit(".", 1)[-1]
        authored = (
            f"{authored}\n## Running unattended\n\n{UNATTENDED_NOTICE}\n"
            f"\n## This run is a sweep\n{SWEEP_NOTICE.format(module=module)}"
        )
    schema = json.dumps(model.model_json_schema(), indent=2)
    return (
        f"{authored}\n## The parameter schema you must satisfy\n\n"
        f"This is `{model.__name__}`, and it is what your validation tool "
        "checks against. Field descriptions begin with the VITESS command-line "
        "flag the value becomes.\n\n"
        f"```json\n{schema}\n```\n"
    )
