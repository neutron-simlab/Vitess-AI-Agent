"""
Guide module tools as LangChain tools.
Validation and file operations for the guide (neutron simulation) agent.

Blocking file-storage I/O is run in a thread (asyncio.to_thread) so the event loop
stays responsive and request cancellation is handled cleanly (unlike when tools
ran in a separate MCP process).
"""

import asyncio
import json
import os
from typing import Any, Union

from langchain.tools import tool
from vitess_ai.schema.guide_module import GuideParameters
from vitess_ai.schema.base import get_field_flag

# Module-level state (same session semantics as before)
_current_files: list[str] = []
_thread_id: str | None = None


def _try_load_files_from_storage(thread_id: str | None = None) -> bool:
    global _current_files, _thread_id
    if not _thread_id and thread_id:
        _thread_id = thread_id
    if not _thread_id:
        _thread_id = os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")
    if not _thread_id:
        return False
    try:
        from vitess_ai.server.file_storage import get_file_storage_service
        storage_service = get_file_storage_service()
        file_paths = storage_service.get_file_paths_for_module(_thread_id, "guide")
        if file_paths and len(file_paths) > 0:
            _current_files = [file_paths[0]]
            return True
    except Exception:
        pass
    return False


def guide_params_to_cli(params: dict) -> str:
    cli_params = []
    for key, value in params.items():
        flag = get_field_flag(GuideParameters, key)
        if value is None:
            continue
        if isinstance(value, (int, float, str)):
            cli_params.append((flag, str(value)))
        elif hasattr(value, "value"):
            cli_params.append((flag, str(value.value)))
    return " ".join([f"{flag}{param}" for flag, param in cli_params])


@tool
async def validate_guide_parameters(parameters: Union[str, dict[str, Any]]) -> dict[str, Any]:
    """Validate guide parameters from either JSON string or dictionary. Returns validation result and CLI string if valid."""
    try:
        if isinstance(parameters, str):
            try:
                parsed_parameters = json.loads(parameters)
            except json.JSONDecodeError:
                return {
                    "validation_status": False,
                    "errors": "Invalid JSON string format",
                    "message": "Guide validation failed: Invalid JSON string",
                }
        elif isinstance(parameters, dict):
            parsed_parameters = parameters
        else:
            return {
                "validation_status": False,
                "errors": f"Expected JSON string or dict, got {type(parameters)}",
                "message": f"Guide validation failed: Invalid parameter type {type(parameters)}",
            }
        validated = GuideParameters(**parsed_parameters)
        cli = guide_params_to_cli(validated.model_dump())
        return {
            "validation_status": True,
            "validated_params": validated.model_dump(),
            "cli_parameters": cli,
            "message": "Guide module parameters are valid!",
        }
    except Exception as e:
        return {
            "validation_status": False,
            "errors": str(e),
            "message": f"Guide validation failed: {e}",
        }


@tool
async def upload_file(file_path: str | None = None, thread_id: str | None = None) -> dict:
    """Upload a file for neutron simulation guide input. Replaces any previously selected file. Pass file_path or thread_id to load from storage."""
    global _current_files, _thread_id
    if not file_path and not _current_files:
        if thread_id:
            _thread_id = thread_id
        # Run blocking file-storage I/O in a thread to avoid blocking the event loop
        await asyncio.to_thread(_try_load_files_from_storage, thread_id)
        if _current_files:
            file_path = _current_files[0]
    try:
        if not file_path:
            return {
                "success": False,
                "message": "No file path provided.",
                "files": [],
                "file_count": 0,
                "existing_files": [],
                "missing_files": [],
            }
        _current_files = [file_path]
        if os.path.exists(file_path):
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            return {
                "success": True,
                "message": f"Successfully selected guide file: {file_name} ({file_size:,} bytes). File ready for simulation.",
                "files": [file_path],
                "file_count": 1,
                "existing_files": [file_path],
                "missing_files": [],
                "file_details": [{"path": file_path, "name": file_name, "size": file_size, "exists": True}],
            }
        return {
            "success": False,
            "message": f"Selected file does not exist: {file_path}",
            "files": [file_path],
            "file_count": 1,
            "existing_files": [],
            "missing_files": [file_path],
            "file_details": [{"path": file_path, "name": os.path.basename(file_path), "size": 0, "exists": False}],
            "error": "File does not exist",
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error uploading file: {str(e)}",
            "files": [],
            "file_count": 0,
            "existing_files": [],
            "missing_files": [],
            "file_details": [],
            "error": str(e),
        }


@tool
async def file_status(thread_id: str | None = None) -> dict:
    """Show current guide file selection status. Optionally pass thread_id to check file storage."""
    global _current_files, _thread_id
    if not _current_files:
        if thread_id:
            _thread_id = thread_id
        await asyncio.to_thread(_try_load_files_from_storage, thread_id)
    if not _current_files:
        return {
            "has_file": False,
            "message": "No guide file selected. Use upload_file() first to select a file.",
            "files": [],
            "file_count": 0,
            "existing_files": [],
            "missing_files": [],
        }
    file_path = _current_files[0]
    file_name = os.path.basename(file_path)
    if os.path.exists(file_path):
        file_size = os.path.getsize(file_path)
        return {
            "has_file": True,
            "message": f"Current guide file: {file_name} ({file_size:,} bytes)",
            "files": _current_files,
            "file_count": 1,
            "existing_files": _current_files,
            "missing_files": [],
            "file_details": [{"path": file_path, "name": file_name, "size": file_size, "exists": True}],
        }
    return {
        "has_file": True,
        "message": f"Selected guide file not found: {file_name}",
        "files": _current_files,
        "file_count": 1,
        "existing_files": [],
        "missing_files": _current_files,
        "file_details": [{"path": file_path, "name": file_name, "size": 0, "exists": False}],
        "error": "File not found",
    }


@tool
async def get_file(thread_id: str | None = None) -> dict[str, Any] | str:
    """Get the current selected guide file. Optionally pass thread_id to load from storage."""
    global _current_files, _thread_id
    if not _current_files:
        if thread_id:
            _thread_id = thread_id
        await asyncio.to_thread(_try_load_files_from_storage, thread_id)
    if not _current_files:
        return "No guide file selected. Use upload_file() first to select a file."
    file_path = _current_files[0]
    return {
        "file": file_path,
        "file_name": os.path.basename(file_path),
        "file_count": 1,
        "files": _current_files,
        "exists": os.path.exists(file_path),
    }


def get_guide_tools():
    """Return list of LangChain tools for the guide module."""
    return [
        validate_guide_parameters,
        upload_file,
        file_status,
        get_file,
    ]
