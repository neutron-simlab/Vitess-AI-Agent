"""
Monitor module tools as LangChain tools.
Validation and file path operations for Monitor1D and Monitor2D agents.

Blocking file-storage I/O is run in a thread (asyncio.to_thread) so the event loop
stays responsive and request cancellation is handled cleanly.
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Union

from langchain.tools import tool
from vitess_ai.schema.monitor1d_module import Monitor1DParameters
from vitess_ai.schema.monitor2d_module import Monitor2DParameters
from vitess_ai.schema.base import get_field_flag

_monitor1d_file_path: str | None = None
_monitor2d_file_path: str | None = None
_thread_id: str | None = None


def _try_load_monitor1d_path_from_storage(thread_id: str | None = None) -> bool:
    global _monitor1d_file_path, _thread_id
    if not _thread_id and thread_id:
        _thread_id = thread_id
    if not _thread_id:
        _thread_id = os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")
    if not _thread_id:
        return False
    try:
        from vitess_ai.server.file_storage import get_file_storage_service
        storage_service = get_file_storage_service()
        files = storage_service.list_files(_thread_id, "monitor1d")
        if files:
            for file_meta in files:
                filename = file_meta.get("filename", "")
                if filename.endswith("_path.txt"):
                    file_path_str = file_meta.get("file_path") or file_meta.get("server_path")
                    if file_path_str:
                        try:
                            metadata_file = Path(file_path_str)
                            if metadata_file.exists():
                                path_content = metadata_file.read_text(encoding="utf-8").strip()
                                if path_content:
                                    _monitor1d_file_path = path_content
                                    return True
                        except Exception:
                            pass
    except Exception:
        pass
    return False


def _try_load_monitor2d_path_from_storage(thread_id: str | None = None) -> bool:
    global _monitor2d_file_path, _thread_id
    if not _thread_id and thread_id:
        _thread_id = thread_id
    if not _thread_id:
        _thread_id = os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")
    if not _thread_id:
        return False
    try:
        from vitess_ai.server.file_storage import get_file_storage_service
        storage_service = get_file_storage_service()
        files = storage_service.list_files(_thread_id, "monitor2d")
        if files:
            for file_meta in files:
                filename = file_meta.get("filename", "")
                if filename.endswith("_path.txt"):
                    file_path_str = file_meta.get("file_path") or file_meta.get("server_path")
                    if file_path_str:
                        try:
                            metadata_file = Path(file_path_str)
                            if metadata_file.exists():
                                path_content = metadata_file.read_text(encoding="utf-8").strip()
                                if path_content:
                                    _monitor2d_file_path = path_content
                                    return True
                        except Exception:
                            pass
    except Exception:
        pass
    return False


def monitor1d_params_to_cli(params: dict) -> str:
    cli_params = []
    for key, value in params.items():
        if value is None:
            continue
        flag = get_field_flag(Monitor1DParameters, key)
        if isinstance(value, (int, float, str)):
            cli_params.append((flag, str(value)))
        elif hasattr(value, "value"):
            cli_params.append((flag, str(value.value)))
    return " ".join([f"{flag}{param}" for flag, param in cli_params])


def monitor2d_params_to_cli(params: dict) -> str:
    cli_params = []
    for key, value in params.items():
        if value is None:
            continue
        flag = get_field_flag(Monitor2DParameters, key)
        if isinstance(value, (int, float, str)):
            cli_params.append((flag, str(value)))
        elif hasattr(value, "value"):
            cli_params.append((flag, str(value.value)))
    return " ".join([f"{flag}{param}" for flag, param in cli_params])


def _default_monitor1d_path(parsed: dict, resolved_thread_id: str | None) -> None:
    from vitess_ai.core.config import global_config
    if "fMonitorFilename" not in parsed or not parsed.get("fMonitorFilename"):
        if resolved_thread_id:
            default_directory = Path(global_config.VITESS_PROJECT_PATH) / resolved_thread_id / "outputs"
            default_directory.mkdir(parents=True, exist_ok=True)
            parsed["fMonitorFilename"] = str(default_directory / "monitor1D.dat")
        else:
            parsed["fMonitorFilename"] = "outputs/monitor1D.dat"
    elif parsed.get("fMonitorFilename") and "outputs/" not in parsed["fMonitorFilename"]:
        filename = os.path.basename(parsed["fMonitorFilename"])
        if resolved_thread_id:
            default_directory = Path(global_config.VITESS_PROJECT_PATH) / resolved_thread_id / "outputs"
            default_directory.mkdir(parents=True, exist_ok=True)
            parsed["fMonitorFilename"] = str(default_directory / filename)
        else:
            parsed["fMonitorFilename"] = f"outputs/{filename}"


def _default_monitor2d_path(parsed: dict, resolved_thread_id: str | None) -> None:
    from vitess_ai.core.config import global_config
    if "fMonitorFilename" not in parsed or not parsed.get("fMonitorFilename"):
        if resolved_thread_id:
            default_directory = Path(global_config.VITESS_PROJECT_PATH) / resolved_thread_id / "outputs"
            default_directory.mkdir(parents=True, exist_ok=True)
            parsed["fMonitorFilename"] = str(default_directory / "monitor2D.dat")
        else:
            parsed["fMonitorFilename"] = "outputs/monitor2D.dat"
    elif parsed.get("fMonitorFilename") and "outputs/" not in str(parsed["fMonitorFilename"]):
        filename = os.path.basename(parsed["fMonitorFilename"])
        if resolved_thread_id:
            default_directory = Path(global_config.VITESS_PROJECT_PATH) / resolved_thread_id / "outputs"
            default_directory.mkdir(parents=True, exist_ok=True)
            parsed["fMonitorFilename"] = str(default_directory / filename)
        else:
            parsed["fMonitorFilename"] = f"outputs/{filename}"


@tool
async def validate_monitor1d_module(parameters: Union[str, dict[str, Any]]) -> dict[str, Any]:
    """Validate Monitor1D parameters from JSON string or dictionary. Returns validation result and CLI string if valid."""
    try:
        if isinstance(parameters, str):
            try:
                parsed_parameters = json.loads(parameters)
            except json.JSONDecodeError:
                return {"validation_status": False, "errors": "Invalid JSON string format", "message": "Monitor1D validation failed: Invalid JSON string"}
        elif isinstance(parameters, dict):
            parsed_parameters = parameters
        else:
            return {"validation_status": False, "errors": f"Expected JSON string or dict, got {type(parameters)}", "message": f"Monitor1D validation failed: Invalid parameter type {type(parameters)}"}
        resolved_thread_id = os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")
        _default_monitor1d_path(parsed_parameters, resolved_thread_id)
        validated = Monitor1DParameters(**parsed_parameters)
        cli = monitor1d_params_to_cli(validated.model_dump())
        return {"validation_status": True, "validated_params": validated.model_dump(), "cli_parameters": cli, "message": "Monitor1D module parameters are valid!"}
    except Exception as e:
        return {"validation_status": False, "errors": str(e), "message": f"Monitor1D validation failed: {e}"}


@tool
async def validate_monitor2d_module(parameters: Union[str, dict[str, Any]]) -> dict[str, Any]:
    """Validate Monitor2D parameters from JSON string or dictionary. Returns validation result and CLI string if valid."""
    try:
        if isinstance(parameters, str):
            try:
                parsed_parameters = json.loads(parameters)
            except json.JSONDecodeError:
                return {"validation_status": False, "errors": "Invalid JSON string format", "message": "Monitor2D validation failed: Invalid JSON string"}
        elif isinstance(parameters, dict):
            parsed_parameters = parameters
        else:
            return {"validation_status": False, "errors": f"Expected JSON string or dict, got {type(parameters)}", "message": f"Monitor2D validation failed: Invalid parameter type {type(parameters)}"}
        resolved_thread_id = os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")
        _default_monitor2d_path(parsed_parameters, resolved_thread_id)
        validated = Monitor2DParameters(**parsed_parameters)
        cli = monitor2d_params_to_cli(validated.model_dump())
        return {"validation_status": True, "validated_params": validated.model_dump(), "cli_parameters": cli, "message": "Monitor2D module parameters are valid!"}
    except Exception as e:
        return {"validation_status": False, "errors": str(e), "message": f"Monitor2D validation failed: {e}"}


@tool
async def set_monitor1d_file_path(file_path: str | None = None, thread_id: str | None = None) -> dict[str, Any]:
    """Set the output file path for Monitor1D. If no path given, defaults to outputs/monitor1D.dat in thread directory. Pass thread_id to load from storage."""
    global _monitor1d_file_path, _thread_id
    if not file_path and not _monitor1d_file_path:
        if thread_id:
            _thread_id = thread_id
        await asyncio.to_thread(_try_load_monitor1d_path_from_storage, thread_id)
        if _monitor1d_file_path:
            file_path = _monitor1d_file_path
    resolved_thread_id = thread_id or _thread_id or os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")
    if resolved_thread_id:
        _thread_id = resolved_thread_id
    if not file_path:
        if resolved_thread_id:
            from vitess_ai.core.config import global_config
            default_directory = Path(global_config.VITESS_PROJECT_PATH) / resolved_thread_id / "outputs"
            default_directory.mkdir(parents=True, exist_ok=True)
            file_path = str(default_directory / "monitor1D.dat")
        else:
            return {"success": False, "message": "No file path and no thread_id. Provide file_path or thread_id.", "file_path": None, "fMonitorFilename": None}
    _monitor1d_file_path = file_path
    file_name = os.path.basename(_monitor1d_file_path)
    directory = os.path.dirname(_monitor1d_file_path)
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as e:
        return {"success": False, "message": f"Cannot create directory: {directory}. Error: {str(e)}", "file_path": _monitor1d_file_path, "fMonitorFilename": None, "error": str(e)}
    return {"success": True, "message": f"Monitor1D output file path set: {file_name}, Directory: {directory}", "file_path": _monitor1d_file_path, "file_name": file_name, "directory": directory, "fMonitorFilename": _monitor1d_file_path}


@tool
async def set_monitor2d_file_path(file_path: str | None = None, thread_id: str | None = None) -> dict[str, Any]:
    """Set the output file path for Monitor2D. If no path given, defaults to outputs/monitor2D.dat in thread directory. Pass thread_id to load from storage."""
    global _monitor2d_file_path, _thread_id
    if not file_path and not _monitor2d_file_path:
        if thread_id:
            _thread_id = thread_id
        await asyncio.to_thread(_try_load_monitor2d_path_from_storage, thread_id)
        if _monitor2d_file_path:
            file_path = _monitor2d_file_path
    resolved_thread_id = thread_id or _thread_id or os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")
    if resolved_thread_id:
        _thread_id = resolved_thread_id
    if not file_path:
        if resolved_thread_id:
            from vitess_ai.core.config import global_config
            default_directory = Path(global_config.VITESS_PROJECT_PATH) / resolved_thread_id / "outputs"
            default_directory.mkdir(parents=True, exist_ok=True)
            file_path = str(default_directory / "monitor2D.dat")
        else:
            return {"success": False, "message": "No file path and no thread_id. Provide file_path or thread_id.", "file_path": None, "fMonitorFilename": None}
    _monitor2d_file_path = file_path
    file_name = os.path.basename(_monitor2d_file_path)
    directory = os.path.dirname(_monitor2d_file_path)
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as e:
        return {"success": False, "message": f"Cannot create directory: {directory}. Error: {str(e)}", "file_path": _monitor2d_file_path, "fMonitorFilename": None, "error": str(e)}
    return {"success": True, "message": f"Monitor2D output file path set: {file_name}, Directory: {directory}", "file_path": _monitor2d_file_path, "file_name": file_name, "directory": directory, "fMonitorFilename": _monitor2d_file_path}


@tool
async def get_monitor1d_file_path(thread_id: str | None = None) -> dict[str, Any]:
    """Get the current Monitor1D output file path. If none set, defaults to outputs/monitor1D.dat. Pass thread_id to load from storage."""
    global _monitor1d_file_path, _thread_id
    if not _monitor1d_file_path:
        if thread_id:
            _thread_id = thread_id
        await asyncio.to_thread(_try_load_monitor1d_path_from_storage, thread_id)
    resolved_thread_id = thread_id or _thread_id or os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")
    if resolved_thread_id:
        _thread_id = resolved_thread_id
    if not _monitor1d_file_path:
        if resolved_thread_id:
            from vitess_ai.core.config import global_config
            default_directory = Path(global_config.VITESS_PROJECT_PATH) / resolved_thread_id / "outputs"
            default_directory.mkdir(parents=True, exist_ok=True)
            _monitor1d_file_path = str(default_directory / "monitor1D.dat")
        else:
            return {"error": "No file path set", "message": "No Monitor1D file path set and no thread_id. Provide a thread_id.", "fMonitorFilename": None}
    return {"file_path": _monitor1d_file_path, "file_name": os.path.basename(_monitor1d_file_path), "directory": os.path.dirname(_monitor1d_file_path), "fMonitorFilename": _monitor1d_file_path}


@tool
async def get_monitor2d_file_path(thread_id: str | None = None) -> dict[str, Any]:
    """Get the current Monitor2D output file path. If none set, defaults to outputs/monitor2D.dat. Pass thread_id to load from storage."""
    global _monitor2d_file_path, _thread_id
    if not _monitor2d_file_path:
        if thread_id:
            _thread_id = thread_id
        await asyncio.to_thread(_try_load_monitor2d_path_from_storage, thread_id)
    resolved_thread_id = thread_id or _thread_id or os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")
    if resolved_thread_id:
        _thread_id = resolved_thread_id
    if not _monitor2d_file_path:
        if resolved_thread_id:
            from vitess_ai.core.config import global_config
            default_directory = Path(global_config.VITESS_PROJECT_PATH) / resolved_thread_id / "outputs"
            default_directory.mkdir(parents=True, exist_ok=True)
            _monitor2d_file_path = str(default_directory / "monitor2D.dat")
        else:
            return {"error": "No file path set", "message": "No Monitor2D file path set and no thread_id. Provide a thread_id.", "fMonitorFilename": None}
    return {"file_path": _monitor2d_file_path, "file_name": os.path.basename(_monitor2d_file_path), "directory": os.path.dirname(_monitor2d_file_path), "fMonitorFilename": _monitor2d_file_path}


@tool
async def generate_plot_1d(monitor_file_path: str) -> dict[str, Any]:
    """Generate a 1D plot from monitor data file (optional visualization). Not yet implemented."""
    return {"success": False, "message": "Plot generation not yet implemented.", "file_path": monitor_file_path}


@tool
async def generate_plot_2d(monitor_file_path: str) -> dict[str, Any]:
    """Generate a 2D plot from monitor data file (optional visualization). Not yet implemented."""
    return {"success": False, "message": "Plot generation not yet implemented.", "file_path": monitor_file_path}


def get_monitor_tools():
    """Return list of LangChain tools for the monitor module (shared by Monitor1D and Monitor2D agents)."""
    return [
        validate_monitor1d_module,
        validate_monitor2d_module,
        set_monitor1d_file_path,
        set_monitor2d_file_path,
        get_monitor1d_file_path,
        get_monitor2d_file_path,
        generate_plot_1d,
        generate_plot_2d,
    ]
