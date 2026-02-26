"""
Read-in module tools as LangChain tools.
Validation and file operations for the read-in module agent.

Blocking file-storage I/O is run in a thread (asyncio.to_thread) so the event loop
stays responsive and request cancellation is handled cleanly.
"""

import asyncio
import json
from typing import Any

from langchain.tools import tool
from vitess_ai.core.log import get_logger
from vitess_ai.schema.readin_module import NF_MAX, ReadInParameters
from vitess_ai.schema.base import get_field_flag, VtPrgFormat

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


@tool
async def file_status(thread_id: str | None = None) -> dict:
    """List files in  {thread_id}/uploads/readin. Pass thread_id to check that folder."""
    if not thread_id:
        return {
            "has_files": False,
            "message": "No thread_id provided.",
            "files": [],
            "file_count": 0,
            "sInputFileName": [None] * NF_MAX,
        }
    files = await asyncio.to_thread(_list_readin_files_for_thread, thread_id)
    files = files[:NF_MAX]
    return {
        "has_files": len(files) > 0,
        "message": f"{len(files)} file(s) in {thread_id}/uploads/readin." if files else f"No files in {thread_id}/uploads/readin.",
        "files": files,
        "file_count": len(files),
        "sInputFileName": files + [None] * (NF_MAX - len(files)),
    }





@tool
async def get_files(thread_id: str | None = None) -> dict[str, Any] | str:
    """Get the list of files in {project}/{thread_id}/uploads/readin. Pass thread_id."""
    if not thread_id:
        return "No thread_id provided. Pass thread_id to get files from uploads/readin."
    files = await asyncio.to_thread(_list_readin_files_for_thread, thread_id)
    files = files[:NF_MAX]
    if not files:
        return "No files in uploads/readin. Use the Streamlit UI to upload files."
    return {
        "file_count": len(files),
        "files": files,
        "sInputFileName": files + [None] * (NF_MAX - len(files)),
    }


@tool
async def validate_readin_module(parameters: str, thread_id: str | None = None) -> dict:
    """Validate Read-in module parameters. Pass JSON string containing ReadInParameters. sInputFileName can be filled from params (files/existing_files) or from uploads when thread_id is provided."""
    try:
        params = json.loads(parameters)
        if not params.get("sInputFileName"):
            candidate_files = None
            if isinstance(params.get("files"), list) and params["files"]:
                candidate_files = params["files"]
            elif isinstance(params.get("existing_files"), list) and params["existing_files"]:
                candidate_files = params["existing_files"]
            elif thread_id:
                candidate_files = await asyncio.to_thread(_list_readin_files_for_thread, thread_id)
                candidate_files = (candidate_files or [])[:NF_MAX]
            if candidate_files:
                params["sInputFileName"] = candidate_files[:NF_MAX]
            else:
                return {
                    "validation_status": False,
                    "errors": "sInputFileName is required but not provided and no files selected.",
                    "message": "Provide sInputFileName or pass files in the JSON, or provide thread_id to use files from uploads.",
                }
        files_list = [p for p in params.get("sInputFileName", []) if p is not None]
        weights_list = params.get("Weight", [])
        if not isinstance(weights_list, list):
            return {"validation_status": False, "errors": "Weight must be a list.", "message": "Weight must be a list."}
        if len(files_list) == 0:
            return {"validation_status": False, "errors": "At least one input file is required.", "message": "Please select at least one input file."}
        if len(weights_list) != len(files_list):
            return {
                "validation_status": False,
                "errors": f"Weight length ({len(weights_list)}) does not match sInputFileName count ({len(files_list)}).",
                "message": "Provide a weight for each input file.",
            }
        eprg_format = params.get("ePrgFormat")
        if eprg_format == VtPrgFormat.VT_KDS_FMT or (isinstance(eprg_format, int) and eprg_format == 7):
            return {
                "validation_status": False,
                "errors": "VT_KDS_FMT format is no longer supported in the read_in module.",
                "message": "KDSource functionality has been moved to module 'kdsource'. Use the separate 'kdsource' module.",
            }
        validated = ReadInParameters(**params)
        validated = validated.model_dump()
        cli = readin_params_to_cli(validated)
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
