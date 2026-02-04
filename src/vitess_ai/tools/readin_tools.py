"""
Read-in module tools as LangChain tools.
Validation and file operations for the read-in module agent.

Blocking file-storage I/O is run in a thread (asyncio.to_thread) so the event loop
stays responsive and request cancellation is handled cleanly.
"""

import asyncio
import json
import os
from typing import Any

from langchain.tools import tool
from vitess_ai.core.log import get_logger
from vitess_ai.schema.readin_module import NF_MAX, ReadInParameters
from vitess_ai.schema.base import get_field_flag, VtPrgFormat

logger = get_logger(__name__)

_current_files: list[str] = []
_current_instrument_file: str | None = None
_thread_id: str | None = None


def _try_load_files_from_storage(thread_id: str | None = None) -> bool:
    global _current_files, _thread_id
    if thread_id:
        _thread_id = thread_id
    elif not _thread_id:
        _thread_id = os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")
    if not _thread_id:
        return False
    try:
        from vitess_ai.server.file_storage import get_file_storage_service
        storage_service = get_file_storage_service()
        file_paths = storage_service.get_file_paths_for_module(_thread_id, "readin")
        if file_paths:
            _current_files = file_paths[:NF_MAX]
            return True
    except Exception as e:
        logger.error(f"Exception in _try_load_files_from_storage: {e}", exc_info=True)
    return False


def _try_load_instrument_file_from_storage(thread_id: str | None = None) -> bool:
    global _current_instrument_file, _thread_id
    if thread_id:
        _thread_id = thread_id
    elif not _thread_id:
        _thread_id = os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")
    if not _thread_id:
        return False
    try:
        from vitess_ai.server.file_storage import get_file_storage_service
        storage_service = get_file_storage_service()
        file_paths = storage_service.get_file_paths_for_module(_thread_id, "instrument")
        if file_paths and len(file_paths) > 0:
            _current_instrument_file = file_paths[0]
            return True
    except Exception as e:
        logger.error(f"Failed to load instrument file from storage: {e}", exc_info=True)
    return False


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


@tool
async def upload_file(file_paths: list[str]) -> dict:
    """Upload files for neutron simulation input. Replaces any previously selected files. Max NF_MAX files."""
    global _current_files
    try:
        if not file_paths:
            return {
                "success": False,
                "message": "No file paths provided.",
                "files": [],
                "file_count": 0,
                "existing_files": [],
                "missing_files": [],
                "sInputFileName": [None] * NF_MAX,
            }
        if len(file_paths) > NF_MAX:
            return {
                "success": False,
                "message": f"Too many files. Maximum is {NF_MAX} files.",
                "files": [],
                "file_count": 0,
                "existing_files": [],
                "missing_files": [],
                "sInputFileName": [None] * NF_MAX,
            }
        _current_files = file_paths[:NF_MAX]
        existing_files = []
        missing_files = []
        file_details = []
        for file_path in _current_files:
            if os.path.exists(file_path):
                existing_files.append(file_path)
                file_details.append({"path": file_path, "name": os.path.basename(file_path), "size": os.path.getsize(file_path), "exists": True})
            else:
                missing_files.append(file_path)
                file_details.append({"path": file_path, "name": os.path.basename(file_path), "size": 0, "exists": False})
        message_parts = [f"Successfully selected {len(existing_files)} files"]
        for i, fp in enumerate(existing_files, 1):
            message_parts.append(f"  {i}. {os.path.basename(fp)} ({os.path.getsize(fp):,} bytes)")
        if missing_files:
            message_parts.append(f"Warning: {len(missing_files)} files not found")
        message_parts.append("Files ready for simulation. Use get_files() to retrieve the file list.")
        return {
            "success": True,
            "message": "\n".join(message_parts),
            "files": _current_files,
            "file_count": len(_current_files),
            "existing_files": existing_files,
            "missing_files": missing_files,
            "file_details": file_details,
            "sInputFileName": _current_files + [None] * (NF_MAX - len(_current_files)),
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error uploading files: {str(e)}",
            "files": [],
            "file_count": 0,
            "existing_files": [],
            "missing_files": [],
            "file_details": [],
            "sInputFileName": [None] * NF_MAX,
            "error": str(e),
        }


@tool
async def set_files(file_paths: list[str]) -> dict:
    """Set file paths directly without validation. Useful when paths are already validated."""
    global _current_files
    try:
        _current_files = file_paths[:NF_MAX]
        return {
            "success": True,
            "message": f"Set {len(_current_files)} file(s)",
            "files": _current_files,
            "file_count": len(_current_files),
            "sInputFileName": _current_files + [None] * (NF_MAX - len(_current_files)),
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error setting files: {str(e)}",
            "files": [],
            "file_count": 0,
            "sInputFileName": [None] * NF_MAX,
            "error": str(e),
        }


@tool
async def upload_instrument_file(instrument_file_path: str) -> dict:
    """Upload instrument file (.inf) for neutron simulation. Replaces any previously selected instrument file."""
    global _current_instrument_file
    try:
        if not instrument_file_path:
            return {
                "success": False,
                "message": "No instrument file path provided.",
                "instrument_file": None,
                "file_name": None,
                "directory": None,
                "file_size": 0,
                "exists": False,
                "sInstrInfIn": None,
            }
        _current_instrument_file = instrument_file_path
        if os.path.exists(_current_instrument_file):
            file_name = os.path.basename(_current_instrument_file)
            file_size = os.path.getsize(_current_instrument_file)
            directory = os.path.dirname(_current_instrument_file)
            return {
                "success": True,
                "message": f"Successfully selected instrument file: {file_name} ({file_size:,} bytes). Path: {directory}",
                "instrument_file": _current_instrument_file,
                "file_name": file_name,
                "directory": directory,
                "file_size": file_size,
                "exists": True,
                "sInstrInfIn": _current_instrument_file,
            }
        return {
            "success": False,
            "message": f"Selected file does not exist: {_current_instrument_file}",
            "instrument_file": _current_instrument_file,
            "file_name": os.path.basename(_current_instrument_file),
            "directory": os.path.dirname(_current_instrument_file),
            "file_size": 0,
            "exists": False,
            "sInstrInfIn": None,
            "error": "File does not exist",
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error uploading instrument file: {str(e)}",
            "instrument_file": None,
            "file_name": None,
            "directory": None,
            "file_size": 0,
            "exists": False,
            "sInstrInfIn": None,
            "error": str(e),
        }


@tool
async def file_status(thread_id: str | None = None) -> dict:
    """Show current file selection status. Pass thread_id to check file storage."""
    global _current_files, _thread_id
    if not _current_files:
        if thread_id:
            _thread_id = thread_id
        elif not _thread_id:
            _thread_id = os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")
        if _thread_id:
            await asyncio.to_thread(_try_load_files_from_storage, _thread_id)
    if not _current_files:
        return {
            "has_files": False,
            "message": "No files selected. Use upload_file() with file paths or check file_status after Streamlit upload.",
            "files": [],
            "file_count": 0,
            "file_details": [],
            "existing_files": [],
            "missing_files": [],
            "sInputFileName": [None] * NF_MAX,
        }
    file_details = []
    existing_files = []
    missing_files = []
    for i, file_path in enumerate(_current_files, 1):
        file_name = os.path.basename(file_path)
        if os.path.exists(file_path):
            existing_files.append(file_path)
            file_details.append({"index": i, "path": file_path, "name": file_name, "size": os.path.getsize(file_path), "exists": True})
        else:
            missing_files.append(file_path)
            file_details.append({"index": i, "path": file_path, "name": file_name, "size": 0, "exists": False})
    message_parts = [f"Current selection: {len(_current_files)} files"]
    for d in file_details:
        msg = f"  {d['index']}. {d['name']}"
        if d["exists"]:
            msg += f" ({d['size']:,} bytes)"
        else:
            msg += " (FILE NOT FOUND)"
        message_parts.append(msg)
    return {
        "has_files": True,
        "message": "\n".join(message_parts),
        "files": _current_files,
        "file_count": len(_current_files),
        "file_details": file_details,
        "existing_files": existing_files,
        "missing_files": missing_files,
        "existing_count": len(existing_files),
        "missing_count": len(missing_files),
        "sInputFileName": _current_files + [None] * (NF_MAX - len(_current_files)),
    }


@tool
async def instrument_file_status(thread_id: str | None = None) -> dict:
    """Show current instrument file selection status. Pass thread_id to check file storage."""
    global _current_instrument_file, _thread_id
    if not _current_instrument_file:
        if thread_id:
            _thread_id = thread_id
        await asyncio.to_thread(_try_load_instrument_file_from_storage, thread_id)
    if not _current_instrument_file:
        return {
            "has_file": False,
            "message": "No instrument file selected. Use upload_instrument_file() with file path.",
            "instrument_file": None,
            "file_name": None,
            "directory": None,
            "file_size": 0,
            "exists": False,
            "modified_date": None,
            "sInstrInfIn": None,
        }
    file_name = os.path.basename(_current_instrument_file)
    directory = os.path.dirname(_current_instrument_file)
    if os.path.exists(_current_instrument_file):
        file_size = os.path.getsize(_current_instrument_file)
        import datetime
        mod_date = datetime.datetime.fromtimestamp(os.path.getmtime(_current_instrument_file)).strftime("%Y-%m-%d %H:%M:%S")
        return {
            "has_file": True,
            "message": f"Current instrument file: {file_name} ({file_size:,} bytes), {directory}, Modified: {mod_date}",
            "instrument_file": _current_instrument_file,
            "file_name": file_name,
            "directory": directory,
            "file_size": file_size,
            "exists": True,
            "modified_date": mod_date,
            "sInstrInfIn": _current_instrument_file,
        }
    return {
        "has_file": True,
        "message": f"Selected instrument file not found: {file_name}",
        "instrument_file": _current_instrument_file,
        "file_name": file_name,
        "directory": directory,
        "file_size": 0,
        "exists": False,
        "modified_date": None,
        "sInstrInfIn": None,
        "error": "File not found",
    }


@tool
async def get_files(thread_id: str | None = None) -> dict[str, Any] | str:
    """Get the current list of selected files. Pass thread_id to load from storage."""
    global _current_files, _thread_id
    if not _current_files:
        if thread_id:
            _thread_id = thread_id
        await asyncio.to_thread(_try_load_files_from_storage, thread_id)
    if not _current_files:
        return "No files selected. Use upload_file() with file paths or check file_status."
    return {
        "file_count": len(_current_files),
        "files": _current_files,
        "sInputFileName": _current_files + [None] * (NF_MAX - len(_current_files)),
    }


@tool
async def get_instrument_file(thread_id: str | None = None) -> dict[str, str] | str:
    """Get the current selected instrument file. Pass thread_id to load from storage."""
    global _current_instrument_file, _thread_id
    if not _current_instrument_file:
        if thread_id:
            _thread_id = thread_id
        await asyncio.to_thread(_try_load_instrument_file_from_storage, thread_id)
    if not _current_instrument_file:
        return "No instrument file selected. Use upload_instrument_file() with file path."
    return {
        "instrument_file": _current_instrument_file,
        "file_name": os.path.basename(_current_instrument_file),
        "directory": os.path.dirname(_current_instrument_file),
        "exists": os.path.exists(_current_instrument_file),
        "sInstrInfIn": _current_instrument_file,
    }


@tool
async def clear_files() -> dict:
    """Clear the current file selection."""
    global _current_files
    if _current_files:
        file_count = len(_current_files)
        cleared_files = _current_files.copy()
        _current_files = []
        return {
            "success": True,
            "message": f"Cleared {file_count} files",
            "cleared_count": file_count,
            "cleared_files": cleared_files,
            "remaining_files": [],
            "has_files": False,
        }
    return {
        "success": True,
        "message": "No files to clear",
        "cleared_count": 0,
        "cleared_files": [],
        "remaining_files": [],
        "has_files": False,
    }


@tool
async def clear_instrument_file() -> dict:
    """Clear the current instrument file selection."""
    global _current_instrument_file
    if _current_instrument_file:
        file_name = os.path.basename(_current_instrument_file)
        cleared_file = _current_instrument_file
        _current_instrument_file = None
        return {
            "success": True,
            "message": f"Cleared instrument file: {file_name}",
            "cleared_file": cleared_file,
            "cleared_file_name": file_name,
            "has_instrument_file": False,
            "sInstrInfIn": None,
        }
    return {
        "success": True,
        "message": "No instrument file to clear",
        "cleared_file": None,
        "cleared_file_name": None,
        "has_instrument_file": False,
        "sInstrInfIn": None,
    }


@tool
async def validate_readin_module(parameters: str) -> dict:
    """Validate Read-in module parameters. Pass JSON string containing ReadInParameters. sInputFileName can be filled from uploaded files."""
    try:
        params = json.loads(parameters)
        global _current_files
        if not params.get("sInputFileName"):
            candidate_files = None
            if isinstance(params.get("files"), list) and params["files"]:
                candidate_files = params["files"]
            elif isinstance(params.get("existing_files"), list) and params["existing_files"]:
                candidate_files = params["existing_files"]
            elif _current_files:
                candidate_files = _current_files
            if candidate_files:
                params["sInputFileName"] = candidate_files + [None] * (NF_MAX - len(candidate_files))
            else:
                return {
                    "validation_status": False,
                    "errors": "sInputFileName is required but not provided and no files selected.",
                    "message": "Please select input files via upload_file() or provide sInputFileName.",
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
        upload_file,
        set_files,
        upload_instrument_file,
        file_status,
        instrument_file_status,
        get_files,
        get_instrument_file,
        clear_files,
        clear_instrument_file,
        validate_readin_module,
    ]
