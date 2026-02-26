"""
Read-in module tools as LangChain tools.
Validation and file operations for the read-in module agent.

Blocking file-storage I/O is run in a thread (asyncio.to_thread) so the event loop
stays responsive and request cancellation is handled cleanly.
"""

import asyncio
import json
from typing import Any

from langchain.tools import ToolRuntime, tool
from vitess_ai.core.log import get_logger
from vitess_ai.schema.readin_module import NF_MAX, ReadInParameters
from vitess_ai.schema.base import get_field_flag, VtPrgFormat
from vitess_ai.agents.simulator.tools.runtime_utils import resolve_thread_id

logger = get_logger(__name__)


def readin_params_to_cli(params: dict) -> str:
    cli_params = []
    for key, value in params.items():
        flag = get_field_flag(ReadInParameters, key)
        if value is None:
            continue
        if isinstance(value, (int, float, str)):
            cli_params.append((flag, str(value)))
        elif isinstance(value, list):
            if key in ["sInputFileName", "Weight"]:
                flags = flag.split(" ")
                for i, val in enumerate(value):
                    if i < len(flags):
                        cli_params.append((flags[i], str(val)))
            else:
                for val in value:
                    cli_params.append((flag, str(val)))
        elif hasattr(value, "value"):
            cli_params.append((flag, str(value.value)))
    return " ".join([f"{flag}{param}" for flag, param in cli_params])


def _list_readin_files_for_thread(thread_id: str) -> list[str]:
    """List file paths in {project}/{thread_id}/uploads/readin. Returns existing paths only."""
    try:
        from vitess_ai.server.file_storage import get_file_storage_service
        storage = get_file_storage_service()
        return storage.get_file_paths_for_module(thread_id, "readin")
    except Exception as e:
        logger.error(f"Failed to list readin files for thread {thread_id}: {e}", exc_info=True)
        return []


def _validate_single_readin_parameter_set(
    params: dict[str, Any],
    thread_files: list[str] | None = None,
) -> tuple[dict[str, Any], str]:
    """Validate one ReadIn parameter set and return validated params + CLI string."""
    parsed = params.copy()
    if not parsed.get("sInputFileName"):
        candidate_files = None
        if isinstance(parsed.get("files"), list) and parsed["files"]:
            candidate_files = parsed["files"]
        elif isinstance(parsed.get("existing_files"), list) and parsed["existing_files"]:
            candidate_files = parsed["existing_files"]
        elif thread_files:
            candidate_files = thread_files
        if candidate_files:
            parsed["sInputFileName"] = candidate_files[:NF_MAX]
        else:
            raise ValueError(
                "sInputFileName is required but not provided and no files selected."
            )

    files_list = [p for p in parsed.get("sInputFileName", []) if p is not None]
    weights_list = parsed.get("Weight", [])

    if not isinstance(weights_list, list):
        raise ValueError("Weight must be a list.")
    if len(files_list) == 0:
        raise ValueError("At least one input file is required.")
    if len(weights_list) != len(files_list):
        raise ValueError(
            f"Weight length ({len(weights_list)}) does not match "
            f"sInputFileName count ({len(files_list)})."
        )

    eprg_format = parsed.get("ePrgFormat")
    if eprg_format == VtPrgFormat.VT_KDS_FMT or (
        isinstance(eprg_format, int) and eprg_format == 7
    ):
        raise ValueError(
            "VT_KDS_FMT format is no longer supported in the read_in module. "
            "KDSource functionality has been moved to module 'kdsource'."
        )

    validated = ReadInParameters(**parsed).model_dump()
    cli = readin_params_to_cli(validated)
    return validated, cli


@tool
async def file_status(
    thread_id: str | None = None, runtime: ToolRuntime = None
) -> dict:
    """List files in {thread_id}/uploads/readin. thread_id resolves from runtime config when omitted."""
    resolved_thread_id = resolve_thread_id(thread_id, runtime)
    if not resolved_thread_id:
        return {
            "has_files": False,
            "message": "No thread_id available.",
            "files": [],
            "file_count": 0,
            "sInputFileName": [None] * NF_MAX,
        }
    files = await asyncio.to_thread(_list_readin_files_for_thread, resolved_thread_id)
    files = files[:NF_MAX]
    return {
        "has_files": len(files) > 0,
        "message": (
            f"{len(files)} file(s) in {resolved_thread_id}/uploads/readin."
            if files
            else f"No files in {resolved_thread_id}/uploads/readin."
        ),
        "files": files,
        "file_count": len(files),
        "sInputFileName": files + [None] * (NF_MAX - len(files)),
    }





@tool
async def get_files(
    thread_id: str | None = None, runtime: ToolRuntime = None
) -> dict[str, Any] | str:
    """Get files in {project}/{thread_id}/uploads/readin. thread_id resolves from runtime config when omitted."""
    resolved_thread_id = resolve_thread_id(thread_id, runtime)
    if not resolved_thread_id:
        return "No thread_id available. Provide thread_id or ensure it exists in runtime config."
    files = await asyncio.to_thread(_list_readin_files_for_thread, resolved_thread_id)
    files = files[:NF_MAX]
    if not files:
        return "No files in uploads/readin. Use the Streamlit UI to upload files."
    return {
        "file_count": len(files),
        "files": files,
        "sInputFileName": files + [None] * (NF_MAX - len(files)),
    }


@tool
async def validate_readin_module(
    parameters: str | dict[str, Any] | list[dict[str, Any]],
    thread_id: str | None = None,
    runtime: ToolRuntime = None,
) -> dict:
    """Validate one or many ReadIn parameter sets from JSON/object/list input."""
    try:
        resolved_thread_id = resolve_thread_id(thread_id, runtime)
        if isinstance(parameters, str):
            try:
                parsed_parameters = json.loads(parameters)
            except json.JSONDecodeError:
                return {
                    "validation_status": False,
                    "errors": "Invalid JSON string format",
                    "message": "Read-in validation failed: Invalid JSON string",
                }
        elif isinstance(parameters, (dict, list)):
            parsed_parameters = parameters
        else:
            return {
                "validation_status": False,
                "errors": f"Expected JSON string, dict, or list of dict, got {type(parameters)}",
                "message": f"Read-in validation failed: Invalid parameter type {type(parameters)}",
            }

        thread_files_cache: list[str] | None = None

        async def _get_thread_files() -> list[str]:
            nonlocal thread_files_cache
            if thread_files_cache is not None:
                return thread_files_cache
            if not resolved_thread_id:
                thread_files_cache = []
                return thread_files_cache
            files = await asyncio.to_thread(
                _list_readin_files_for_thread, resolved_thread_id
            )
            thread_files_cache = (files or [])[:NF_MAX]
            return thread_files_cache

        def _needs_thread_lookup(param_set: dict[str, Any]) -> bool:
            return (
                not param_set.get("sInputFileName")
                and not (isinstance(param_set.get("files"), list) and param_set["files"])
                and not (
                    isinstance(param_set.get("existing_files"), list)
                    and param_set["existing_files"]
                )
            )

        if isinstance(parsed_parameters, list):
            if not parsed_parameters:
                return {
                    "validation_status": False,
                    "errors": "Received empty parameter set list",
                    "message": "Read-in validation failed: No parameter sets provided",
                }

            validated_params: list[dict[str, Any]] = []
            cli_parameters: list[str] = []
            errors: list[dict[str, Any]] = []

            for idx, param_set in enumerate(parsed_parameters):
                if not isinstance(param_set, dict):
                    errors.append(
                        {
                            "index": idx,
                            "errors": f"Expected dict for parameter set, got {type(param_set)}",
                        }
                    )
                    continue

                try:
                    thread_files = (
                        await _get_thread_files() if _needs_thread_lookup(param_set) else None
                    )
                    validated, cli = _validate_single_readin_parameter_set(
                        param_set,
                        thread_files=thread_files,
                    )
                    validated_params.append(validated)
                    cli_parameters.append(cli)
                except Exception as exc:
                    errors.append({"index": idx, "errors": str(exc)})

            if errors:
                return {
                    "validation_status": False,
                    "errors": errors,
                    "validated_params": validated_params,
                    "cli_parameters": cli_parameters,
                    "total_sets": len(parsed_parameters),
                    "valid_sets": len(validated_params),
                    "invalid_sets": len(errors),
                    "message": (
                        f"Read-in batch validation failed for {len(errors)} of "
                        f"{len(parsed_parameters)} parameter set(s)."
                    ),
                }

            return {
                "validation_status": True,
                "validated_params": validated_params,
                "cli_parameters": cli_parameters,
                "total_sets": len(validated_params),
                "message": f"Read-in module parameters are valid for {len(validated_params)} set(s)!",
            }

        single_thread_files = (
            await _get_thread_files() if _needs_thread_lookup(parsed_parameters) else None
        )
        validated, cli = _validate_single_readin_parameter_set(
            parsed_parameters,
            thread_files=single_thread_files,
        )
        return {
            "validation_status": True,
            "validated_params": validated,
            "cli_parameters": cli,
            "message": "Read-in module parameters are valid!",
        }
    except Exception as e:
        return {"validation_status": False, "errors": str(e), "message": f"Read-in validation failed: {e}"}


def get_readin_tools():
    """Return list of LangChain tools for the read-in module."""
    return [
        file_status,
        get_files,
        validate_readin_module,
    ]
