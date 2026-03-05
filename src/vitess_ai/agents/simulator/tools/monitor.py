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

from langchain.tools import ToolRuntime, tool
from vitess_ai.schema.monitor1d_module import Monitor1DParameters
from vitess_ai.schema.monitor2d_module import Monitor2DParameters
from vitess_ai.schema.base import get_field_flag
from vitess_ai.agents.simulator.tools.runtime_utils import resolve_thread_id

_monitor1d_file_path: str | None = None
_monitor2d_file_path: str | None = None
_thread_id: str | None = None


def _try_load_monitor1d_path_from_storage(thread_id: str | None = None) -> bool:
    global _monitor1d_file_path, _thread_id
    if not _thread_id and thread_id:
        _thread_id = thread_id
    if not _thread_id:
        _thread_id = os.environ.get("THREAD_ID")
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
        _thread_id = os.environ.get("THREAD_ID")
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
        if not flag:
            continue  # Skip unknown keys so we never emit bare values (e.g. "1 1")
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
        if not flag:
            continue  # Skip unknown keys so we never emit bare values (e.g. "1 1" after -Ofile)
        if isinstance(value, (int, float, str)):
            cli_params.append((flag, str(value)))
        elif hasattr(value, "value"):
            cli_params.append((flag, str(value.value)))
    return " ".join([f"{flag}{param}" for flag, param in cli_params])


def _default_monitor1d_path(parsed: dict, resolved_thread_id: str | None) -> None:
    """Set default fMonitorFilename. Use filename only so -O is resolved relative to -P (run directory)."""
    _ = resolved_thread_id  # Kept for internal call compatibility
    val = parsed.get("fMonitorFilename") or ""
    if not val.strip():
        parsed["fMonitorFilename"] = "monitor1D.dat"
        return
    filename = os.path.basename(val)
    # If already a plain filename (no path), keep as is so CLI gets -Omonitor1D.dat
    if val == filename or "/" not in val and "\\" not in val:
        parsed["fMonitorFilename"] = filename if filename else "monitor1D.dat"
        return
    # User set an explicit path (e.g. via set_monitor1d_file_path); keep as path, CLI will use basename for -O
    parsed["fMonitorFilename"] = val


def _default_monitor2d_path(parsed: dict, resolved_thread_id: str | None) -> None:
    """Set default fMonitorFilename. Use filename only so -O is resolved relative to -P (run directory)."""
    _ = resolved_thread_id  # Kept for internal call compatibility
    val = parsed.get("fMonitorFilename") or ""
    if not val.strip():
        parsed["fMonitorFilename"] = "monitor2D.dat"
        return
    filename = os.path.basename(val)
    # If already a plain filename (no path), keep as is so CLI gets -Omonitor2D.dat
    if val == filename or "/" not in val and "\\" not in val:
        parsed["fMonitorFilename"] = filename if filename else "monitor2D.dat"
        return
    # User set an explicit path (e.g. via set_monitor2d_file_path); keep as path, CLI will use basename for -O
    parsed["fMonitorFilename"] = val


def _validate_single_monitor1d_parameter_set(
    params: dict[str, Any],
    resolved_thread_id: str | None,
) -> tuple[dict[str, Any], str]:
    """Validate one Monitor1D parameter set and return validated params + CLI string."""
    parsed_parameters = params.copy()
    _default_monitor1d_path(parsed_parameters, resolved_thread_id)
    validated = Monitor1DParameters(**parsed_parameters).model_dump()
    cli = monitor1d_params_to_cli(validated)
    return validated, cli


def _validate_single_monitor2d_parameter_set(
    params: dict[str, Any],
    resolved_thread_id: str | None,
) -> tuple[dict[str, Any], str]:
    """Validate one Monitor2D parameter set and return validated params + CLI string."""
    parsed_parameters = params.copy()
    _default_monitor2d_path(parsed_parameters, resolved_thread_id)
    validated = Monitor2DParameters(**parsed_parameters).model_dump()
    cli = monitor2d_params_to_cli(validated)
    return validated, cli


@tool
async def validate_monitor1d_module(
    parameters: Union[str, dict[str, Any], list[dict[str, Any]]],
    runtime: ToolRuntime = None,
) -> dict[str, Any]:
    """Validate one or many Monitor1D parameter sets from JSON/object/list input."""
    try:
        if isinstance(parameters, str):
            try:
                parsed_parameters = json.loads(parameters)
            except json.JSONDecodeError:
                return {"validation_status": False, "errors": "Invalid JSON string format", "message": "Monitor1D validation failed: Invalid JSON string"}
        elif isinstance(parameters, (dict, list)):
            parsed_parameters = parameters
        else:
            return {"validation_status": False, "errors": f"Expected JSON string, dict, or list of dict, got {type(parameters)}", "message": f"Monitor1D validation failed: Invalid parameter type {type(parameters)}"}
        resolved_thread_id = resolve_thread_id(runtime=runtime)
        if isinstance(parsed_parameters, list):
            if not parsed_parameters:
                return {
                    "validation_status": False,
                    "errors": "Received empty parameter set list",
                    "message": "Monitor1D validation failed: No parameter sets provided",
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
                    validated, cli = _validate_single_monitor1d_parameter_set(
                        param_set, resolved_thread_id
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
                        f"Monitor1D batch validation failed for {len(errors)} of "
                        f"{len(parsed_parameters)} parameter set(s)."
                    ),
                }

            return {
                "validation_status": True,
                "validated_params": validated_params,
                "cli_parameters": cli_parameters,
                "total_sets": len(validated_params),
                "message": f"Monitor1D module parameters are valid for {len(validated_params)} set(s)!",
            }

        validated, cli = _validate_single_monitor1d_parameter_set(
            parsed_parameters, resolved_thread_id
        )
        return {"validation_status": True, "validated_params": validated, "cli_parameters": cli, "message": "Monitor1D module parameters are valid!"}
    except Exception as e:
        return {"validation_status": False, "errors": str(e), "message": f"Monitor1D validation failed: {e}"}


@tool
async def validate_monitor2d_module(
    parameters: Union[str, dict[str, Any], list[dict[str, Any]]],
    runtime: ToolRuntime = None,
) -> dict[str, Any]:
    """Validate one or many Monitor2D parameter sets from JSON/object/list input."""
    try:
        if isinstance(parameters, str):
            try:
                parsed_parameters = json.loads(parameters)
            except json.JSONDecodeError:
                return {"validation_status": False, "errors": "Invalid JSON string format", "message": "Monitor2D validation failed: Invalid JSON string"}
        elif isinstance(parameters, (dict, list)):
            parsed_parameters = parameters
        else:
            return {"validation_status": False, "errors": f"Expected JSON string, dict, or list of dict, got {type(parameters)}", "message": f"Monitor2D validation failed: Invalid parameter type {type(parameters)}"}
        resolved_thread_id = resolve_thread_id(runtime=runtime)
        if isinstance(parsed_parameters, list):
            if not parsed_parameters:
                return {
                    "validation_status": False,
                    "errors": "Received empty parameter set list",
                    "message": "Monitor2D validation failed: No parameter sets provided",
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
                    validated, cli = _validate_single_monitor2d_parameter_set(
                        param_set, resolved_thread_id
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
                        f"Monitor2D batch validation failed for {len(errors)} of "
                        f"{len(parsed_parameters)} parameter set(s)."
                    ),
                }

            return {
                "validation_status": True,
                "validated_params": validated_params,
                "cli_parameters": cli_parameters,
                "total_sets": len(validated_params),
                "message": f"Monitor2D module parameters are valid for {len(validated_params)} set(s)!",
            }

        validated, cli = _validate_single_monitor2d_parameter_set(
            parsed_parameters, resolved_thread_id
        )
        return {"validation_status": True, "validated_params": validated, "cli_parameters": cli, "message": "Monitor2D module parameters are valid!"}
    except Exception as e:
        return {"validation_status": False, "errors": str(e), "message": f"Monitor2D validation failed: {e}"}


@tool
async def set_monitor1d_file_path(
    file_path: str | None = None,
    thread_id: str | None = None,
    runtime: ToolRuntime = None,
) -> dict[str, Any]:
    """Set Monitor1D output path. thread_id resolves from runtime config when omitted."""
    global _monitor1d_file_path, _thread_id
    resolved_thread_id = resolve_thread_id(thread_id, runtime)
    if not file_path and not _monitor1d_file_path:
        if resolved_thread_id:
            _thread_id = resolved_thread_id
        await asyncio.to_thread(
            _try_load_monitor1d_path_from_storage, resolved_thread_id
        )
        if _monitor1d_file_path:
            file_path = _monitor1d_file_path
    resolved_thread_id = resolved_thread_id or _thread_id or os.environ.get("THREAD_ID")
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
async def set_monitor2d_file_path(
    file_path: str | None = None,
    thread_id: str | None = None,
    runtime: ToolRuntime = None,
) -> dict[str, Any]:
    """Set Monitor2D output path. thread_id resolves from runtime config when omitted."""
    global _monitor2d_file_path, _thread_id
    resolved_thread_id = resolve_thread_id(thread_id, runtime)
    if not file_path and not _monitor2d_file_path:
        if resolved_thread_id:
            _thread_id = resolved_thread_id
        await asyncio.to_thread(
            _try_load_monitor2d_path_from_storage, resolved_thread_id
        )
        if _monitor2d_file_path:
            file_path = _monitor2d_file_path
    resolved_thread_id = resolved_thread_id or _thread_id or os.environ.get("THREAD_ID")
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
async def get_monitor1d_file_path(
    thread_id: str | None = None, runtime: ToolRuntime = None
) -> dict[str, Any]:
    """Get Monitor1D output path. thread_id resolves from runtime config when omitted."""
    global _monitor1d_file_path, _thread_id
    resolved_thread_id = resolve_thread_id(thread_id, runtime)
    if not _monitor1d_file_path:
        if resolved_thread_id:
            _thread_id = resolved_thread_id
        await asyncio.to_thread(
            _try_load_monitor1d_path_from_storage, resolved_thread_id
        )
    resolved_thread_id = resolved_thread_id or _thread_id or os.environ.get("THREAD_ID")
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
async def get_monitor2d_file_path(
    thread_id: str | None = None, runtime: ToolRuntime = None
) -> dict[str, Any]:
    """Get Monitor2D output path. thread_id resolves from runtime config when omitted."""
    global _monitor2d_file_path, _thread_id
    resolved_thread_id = resolve_thread_id(thread_id, runtime)
    if not _monitor2d_file_path:
        if resolved_thread_id:
            _thread_id = resolved_thread_id
        await asyncio.to_thread(
            _try_load_monitor2d_path_from_storage, resolved_thread_id
        )
    resolved_thread_id = resolved_thread_id or _thread_id or os.environ.get("THREAD_ID")
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



def get_monitor_tools():
    """Return list of LangChain tools for the monitor module (shared by Monitor1D and Monitor2D agents)."""
    return [
        validate_monitor1d_module,
        validate_monitor2d_module,
        set_monitor1d_file_path,
        set_monitor2d_file_path,
        get_monitor1d_file_path,
        get_monitor2d_file_path,
    ]
