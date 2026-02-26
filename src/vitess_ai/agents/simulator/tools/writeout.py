"""
Writeout module tools as LangChain tools.
Validation and save-path operations for the writeout module agent.

Blocking file-storage I/O is run in a thread (asyncio.to_thread) so the event loop
stays responsive and request cancellation is handled cleanly.
"""

import asyncio
import json
import os
from pathlib import Path

from langchain.tools import tool
from vitess_ai.schema.writeout_module import WriteoutParameters, VtFilterLimits, VtOutputFlags
from vitess_ai.schema.base import get_field_flag

_current_save_path: str | None = None
_thread_id: str | None = None


def _try_load_save_path_from_storage(thread_id: str | None = None) -> bool:
    global _current_save_path, _thread_id
    if not _thread_id and thread_id:
        _thread_id = thread_id
    if not _thread_id:
        _thread_id = os.environ.get("THREAD_ID")
    if not _thread_id:
        return False
    try:
        from vitess_ai.server.file_storage import get_file_storage_service
        storage_service = get_file_storage_service()
        files = storage_service.list_files(_thread_id, "writeout")
        if files and len(files) > 0:
            file_meta = files[0]
            save_path = file_meta.get("file_path") or file_meta.get("server_path") or file_meta.get("filename")
            if save_path:
                _current_save_path = save_path
                return True
    except Exception:
        pass
    return False


def writeout_params_to_cli(params: dict) -> str:
    cli_params = []
    for key, value in params.items():
        if key == "output_flags":
            if value is not None:
                flags_dict = value.model_dump() if hasattr(value, "model_dump") else value
                flag_values = ["1" if v else "0" for _, v in flags_dict.items()]
                cli_params.append(("-c", "".join(flag_values)))
            continue
        if key == "filter_limits":
            if value is not None:
                limits_dict = value.model_dump() if hasattr(value, "model_dump") else value
                for limit_key, limit_val in limits_dict.items():
                    if limit_val is not None:
                        limit_flag = get_field_flag(VtFilterLimits, limit_key)
                        cli_params.append((limit_flag, str(limit_val)))
            continue
        flag = get_field_flag(WriteoutParameters, key)
        if value is None:
            continue
        if isinstance(value, bool):
            cli_params.append((flag, "1" if value else "0"))
        elif isinstance(value, str) and value.lower() in ("true", "false"):
            cli_params.append((flag, "1" if value.lower() == "true" else "0"))
        elif isinstance(value, (int, float, str)):
            cli_params.append((flag, str(value)))
        elif hasattr(value, "value"):
            cli_params.append((flag, str(value.value)))
    return " ".join([f"{flag}{param}" for flag, param in cli_params])


@tool
async def save_file(save_path: str | None = None, thread_id: str | None = None) -> dict:
    """Select save location and filename for neutron simulation output. Pass save_path or thread_id to load from storage."""
    global _current_save_path, _thread_id
    if not save_path and not _current_save_path:
        if thread_id:
            _thread_id = thread_id
        await asyncio.to_thread(_try_load_save_path_from_storage, thread_id)
        if _current_save_path:
            save_path = _current_save_path
    try:
        if not save_path:
            from vitess_ai.core.config import global_config
            root = global_config.VITESS_PROJECT_PATH
            return {
                "success": False,
                "message": f"No save path provided. Provide a full path. Default directory is {{root}}/{{thread_id}}/outputs/ with a filename.",
                "save_path": None,
                "file_name": None,
                "directory": None,
                "file_exists": False,
                "can_write": False,
                "sOutFileName": None,
            }
        _current_save_path = save_path
        file_name = os.path.basename(_current_save_path)
        directory = os.path.dirname(_current_save_path)
        file_exists = os.path.exists(_current_save_path)
        dir_exists = os.path.exists(directory)
        can_write = os.access(directory, os.W_OK) if dir_exists else False
        dir_created = False
        if not dir_exists:
            try:
                os.makedirs(directory, exist_ok=True)
                can_write = True
                dir_created = True
            except OSError as e:
                return {
                    "success": False,
                    "message": f"Cannot create directory: {directory}. Error: {str(e)}",
                    "save_path": _current_save_path,
                    "file_name": file_name,
                    "directory": directory,
                    "file_exists": file_exists,
                    "can_write": False,
                    "sOutFileName": None,
                    "error": str(e),
                }
        message_parts = ["Successfully selected save location", f"File: {file_name}", f"Directory: {directory}"]
        if dir_created:
            message_parts.append("Directory created successfully")
        if file_exists:
            message_parts.append("File already exists and will be overwritten")
        message_parts.append("Save location ready. Use get_save_path() to retrieve the path.")
        return {
            "success": True,
            "message": "\n".join(message_parts),
            "save_path": _current_save_path,
            "file_name": file_name,
            "directory": directory,
            "file_exists": file_exists,
            "can_write": can_write,
            "directory_created": dir_created,
            "sOutFileName": _current_save_path,
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error saving file path: {str(e)}",
            "save_path": None,
            "file_name": None,
            "directory": None,
            "file_exists": False,
            "can_write": False,
            "sOutFileName": None,
            "error": str(e),
        }


@tool
async def save_path_status(thread_id: str | None = None) -> dict:
    """Show current save path selection status. Pass thread_id to check file storage."""
    global _current_save_path, _thread_id
    if not _current_save_path:
        if thread_id:
            _thread_id = thread_id
        await asyncio.to_thread(_try_load_save_path_from_storage, thread_id)
    if not _current_save_path:
        from vitess_ai.core.config import global_config
        resolved_thread_id = thread_id or _thread_id or os.environ.get("THREAD_ID")
        if resolved_thread_id:
            _thread_id = resolved_thread_id
            default_directory = Path(global_config.VITESS_PROJECT_PATH) / resolved_thread_id / "outputs"
            default_directory.mkdir(parents=True, exist_ok=True)
            return {
                "has_save_path": False,
                "message": f"Default output directory: {default_directory}/\nProvide a filename for the output file (e.g. neutron_output.out, results.dat).",
                "save_path": None,
                "file_name": None,
                "directory": str(default_directory),
                "file_exists": False,
                "can_write": True,
                "vitess_sOutFileName": None,
                "default_directory": str(default_directory),
                "needs_filename": True,
            }
        return {
            "has_save_path": False,
            "message": "No save location selected and no thread_id available. Provide a thread_id.",
            "save_path": None,
            "file_name": None,
            "directory": None,
            "file_exists": False,
            "can_write": False,
            "vitess_sOutFileName": None,
        }
    file_name = os.path.basename(_current_save_path)
    directory = os.path.dirname(_current_save_path)
    file_exists = os.path.exists(_current_save_path)
    dir_exists = os.path.exists(directory)
    can_write = os.access(directory, os.W_OK) if dir_exists else False
    file_size = os.path.getsize(_current_save_path) if file_exists else 0
    message_parts = ["Current save location:", f"File: {file_name}", f"Directory: {directory}"]
    if file_exists:
        message_parts.append(f"Current size: {file_size:,} bytes. File exists and will be overwritten.")
    else:
        message_parts.append("New file will be created.")
    if dir_exists:
        message_parts.append("Directory is writable" if can_write else "Directory is not writable")
    return {
        "has_save_path": True,
        "message": "\n".join(message_parts),
        "save_path": _current_save_path,
        "file_name": file_name,
        "directory": directory,
        "file_exists": file_exists,
        "file_size": file_size,
        "directory_exists": dir_exists,
        "can_write": can_write,
        "sOutFileName": _current_save_path,
    }


@tool
async def get_save_path(thread_id: str | None = None) -> dict | str:
    """Get the current selected save path. Pass thread_id to load from storage."""
    global _current_save_path, _thread_id
    if not _current_save_path:
        if thread_id:
            _thread_id = thread_id
        await asyncio.to_thread(_try_load_save_path_from_storage, thread_id)
    if not _current_save_path:
        from vitess_ai.core.config import global_config
        resolved_thread_id = thread_id or _thread_id or os.environ.get("THREAD_ID")
        if resolved_thread_id:
            _thread_id = resolved_thread_id
            default_directory = Path(global_config.VITESS_PROJECT_PATH) / resolved_thread_id / "outputs"
            default_directory.mkdir(parents=True, exist_ok=True)
            return {
                "error": "No save path selected",
                "message": f"Default output directory: {default_directory}/\nProvide a filename for the output file.",
                "default_directory": str(default_directory),
                "needs_filename": True,
            }
        return "No save location selected and no thread_id available. Provide a thread_id."
    return {
        "save_path": _current_save_path,
        "file_name": os.path.basename(_current_save_path),
        "directory": os.path.dirname(_current_save_path),
        "file_exists": os.path.exists(_current_save_path),
        "can_write": os.access(os.path.dirname(_current_save_path), os.W_OK) if os.path.exists(os.path.dirname(_current_save_path)) else False,
        "sOutFileName": _current_save_path,
    }


@tool
async def clear_save_path() -> dict:
    """Clear the current save path selection."""
    global _current_save_path
    if _current_save_path:
        file_name = os.path.basename(_current_save_path)
        cleared_path = _current_save_path
        _current_save_path = None
        return {
            "success": True,
            "message": f"Cleared save location: {file_name}",
            "cleared_path": cleared_path,
            "cleared_file_name": file_name,
            "has_save_path": False,
            "vitess_sOutFileName": None,
        }
    return {
        "success": True,
        "message": "No save location to clear",
        "cleared_path": None,
        "cleared_file_name": None,
        "has_save_path": False,
        "vitess_sOutFileName": None,
    }


@tool
async def validate_writeout_module(parameters: str) -> dict:
    """Validate Writeout module parameters. Pass JSON string containing WriteoutParameters data."""
    try:
        params = json.loads(parameters)
        validated = WriteoutParameters(**params)
        cli = writeout_params_to_cli(validated.model_dump())
        return {
            "validation_status": True,
            "validated_params": validated.model_dump(),
            "cli_parameters": cli,
            "message": "Writeout module parameters are valid!",
        }
    except Exception as e:
        return {"validation_status": False, "errors": str(e), "message": f"Writeout validation failed: {e}"}


def get_writeout_tools():
    """Return list of LangChain tools for the writeout module."""
    return [
        save_file,
        save_path_status,
        get_save_path,
        clear_save_path,
        validate_writeout_module,
    ]
