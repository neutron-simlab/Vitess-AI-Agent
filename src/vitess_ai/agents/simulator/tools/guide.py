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
from vitess_ai.core.log import get_logger

logger = get_logger(__name__)


def _list_guide_file_for_thread(thread_id: str) -> str | None:
    """Return the first file path in {project}/{thread_id}/uploads/guide, or None."""
    try:
        from vitess_ai.server.file_storage import get_file_storage_service
        storage = get_file_storage_service()
        paths = storage.get_file_paths_for_module(thread_id, "guide")
        return paths[0] if paths else None
    except Exception as e:
        logger.error(f"Failed to list guide file for thread {thread_id}: {e}", exc_info=True)
        return None


def guide_params_to_cli(params: dict) -> str:
    cli_params = []
    for key, value in params.items():
        flag = get_field_flag(GuideParameters, key)
        if value is None:
            continue
        # Omit -S when ShapeFileName is empty (default: no guide file)
        if key == "ShapeFileName" and (value == "" or (isinstance(value, str) and value.strip() == "")):
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
async def file_status(thread_id: str | None = None) -> dict:
    """List file in {project}/{thread_id}/uploads/guide. Pass thread_id to check that folder."""
    if not thread_id:
        return {
            "has_file": False,
            "message": "No thread_id provided.",
            "files": [],
            "file_count": 0,
        }
    file_path = await asyncio.to_thread(_list_guide_file_for_thread, thread_id)
    if not file_path:
        return {
            "has_file": False,
            "message": f"No file in {thread_id}/uploads/guide.",
            "files": [],
            "file_count": 0,
        }
    return {
        "has_file": True,
        "message": f"1 file in {thread_id}/uploads/guide.",
        "file": file_path,
        "files": [file_path],
        "file_count": 1,
    }


@tool
async def get_file(thread_id: str | None = None) -> dict[str, Any] | str:
    """Get the guide file from {project}/{thread_id}/uploads/guide. Pass thread_id."""
    if not thread_id:
        return "No thread_id provided. Pass thread_id to get the guide file from uploads/guide."
    file_path = await asyncio.to_thread(_list_guide_file_for_thread, thread_id)
    if not file_path:
        return "No guide file in uploads/guide. Use the Streamlit UI to upload a guide file."
    return {
        "file": file_path,
        "file_name": os.path.basename(file_path),
        "file_count": 1,
        "files": [file_path],
        "exists": os.path.exists(file_path),
    }


def get_guide_tools():
    """Return list of LangChain tools for the guide module."""
    return [
        validate_guide_parameters,
        file_status,
        get_file,
    ]
