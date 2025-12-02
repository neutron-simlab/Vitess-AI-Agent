# monitor_module_tools.py
from fastmcp import FastMCP
import json
import os
from pathlib import Path
from vitess_ai.schema.monitor1d_module import Monitor1DParameters
from vitess_ai.schema.monitor2d_module import Monitor2DParameters
from vitess_ai.schema.base import get_field_flag
from typing import Any, Union

mcp = FastMCP("Monitor Parameter Validation Server")

# Global storage for current monitor file paths (per module type)
_monitor1d_file_path: str | None = None
_monitor2d_file_path: str | None = None
_thread_id: str | None = None


def _try_load_monitor1d_path_from_storage() -> bool:
    """
    Try to load monitor1d file path from file storage service if available.
    Returns True if path was loaded, False otherwise.
    """
    global _monitor1d_file_path, _thread_id
    
    # Try to get thread_id from environment variable
    if not _thread_id:
        _thread_id = os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")
    
    if not _thread_id:
        return False
    
    try:
        from vitess_ai.server.file_storage import get_file_storage_service
        
        storage_service = get_file_storage_service()
        files = storage_service.list_files(_thread_id, "monitor1d")
        
        if files and len(files) > 0:
            # Get the path from file metadata (look for path metadata files)
            for file_meta in files:
                filename = file_meta.get("filename", "")
                if filename.endswith("_path.txt"):
                    # This is a path metadata file, read its content
                    file_path_str = file_meta.get("file_path") or file_meta.get("server_path")
                    if file_path_str:
                        try:
                            # Read the path from the metadata file
                            metadata_file = Path(file_path_str)
                            if metadata_file.exists():
                                path_content = metadata_file.read_text(encoding='utf-8').strip()
                                if path_content:
                                    _monitor1d_file_path = path_content
                                    return True
                        except Exception:
                            pass
    except Exception:
        # If file storage is not available or fails, just continue without it
        pass
    
    return False


def _try_load_monitor2d_path_from_storage() -> bool:
    """
    Try to load monitor2d file path from file storage service if available.
    Returns True if path was loaded, False otherwise.
    """
    global _monitor2d_file_path, _thread_id
    
    # Try to get thread_id from environment variable
    if not _thread_id:
        _thread_id = os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")
    
    if not _thread_id:
        return False
    
    try:
        from vitess_ai.server.file_storage import get_file_storage_service
        
        storage_service = get_file_storage_service()
        files = storage_service.list_files(_thread_id, "monitor2d")
        
        if files and len(files) > 0:
            # Get the path from file metadata (look for path metadata files)
            for file_meta in files:
                filename = file_meta.get("filename", "")
                if filename.endswith("_path.txt"):
                    # This is a path metadata file, read its content
                    file_path_str = file_meta.get("file_path") or file_meta.get("server_path")
                    if file_path_str:
                        try:
                            # Read the path from the metadata file
                            metadata_file = Path(file_path_str)
                            if metadata_file.exists():
                                path_content = metadata_file.read_text(encoding='utf-8').strip()
                                if path_content:
                                    _monitor2d_file_path = path_content
                                    return True
                        except Exception:
                            pass
    except Exception:
        # If file storage is not available or fails, just continue without it
        pass
    
    return False


def monitor1d_params_to_cli(params: dict) -> str:
    """Convert Monitor1D parameters to CLI flags"""
    cli_params = list()

    for key, value in params.items():
        flag = get_field_flag(Monitor1DParameters, key)
        
        # Skip None values
        if value is None:
            continue
        
        if isinstance(value, (int, float, str)): 
            cli_params.append((flag, str(value)))

        # Handle enum types (like VtMonPar, VtFiltComb)
        elif hasattr(value, 'value'):
            cli_params.append((flag, str(value.value)))

    return ' '.join([f'{flag}{param}' for flag, param in cli_params])


def monitor2d_params_to_cli(params: dict) -> str:
    """Convert Monitor2D parameters to CLI flags"""
    cli_params = list()

    for key, value in params.items():
        flag = get_field_flag(Monitor2DParameters, key)
        
        # Skip None values
        if value is None:
            continue
        
        if isinstance(value, (int, float, str)): 
            cli_params.append((flag, str(value)))

        # Handle enum types (like VtMonPar, VtFiltComb, VtFormat2D)
        elif hasattr(value, 'value'):
            cli_params.append((flag, str(value.value)))

    return ' '.join([f'{flag}{param}' for flag, param in cli_params])


@mcp.tool()  
async def validate_monitor1d_module(parameters: Union[str, dict[str, Any]]) -> dict[str, Any]:
    """
    Validate Monitor1D parameters from either JSON string or dictionary.
    
    Args:
        parameters: Either a JSON string or dictionary containing Monitor1D parameters
        
    Returns:
        Dictionary with validation results including validation_status, validated_params, cli_parameters, and message
    """
    try:
        # Handle both JSON string and dict inputs
        if isinstance(parameters, str):
            try:
                parsed_parameters = json.loads(parameters)
            except json.JSONDecodeError:
                return {
                    "validation_status": False,
                    "errors": "Invalid JSON string format",
                    "message": "Monitor1D validation failed: Invalid JSON string",
                }
        elif isinstance(parameters, dict):
            parsed_parameters = parameters
        else:
            return {
                "validation_status": False,
                "errors": f"Expected JSON string or dict, got {type(parameters)}",
                "message": f"Monitor1D validation failed: Invalid parameter type {type(parameters)}",
            }
        
        # Before validation, ensure fMonitorFilename is set to outputs/ directory if not already set
        # Get thread_id for default path
        resolved_thread_id = os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")
        
        # If fMonitorFilename is not set or doesn't include outputs/, set default
        if "fMonitorFilename" not in parsed_parameters or not parsed_parameters.get("fMonitorFilename"):
            if resolved_thread_id:
                from vitess_ai.core.config import global_config
                default_directory = Path(global_config.VITESS_PROJECT_PATH) / resolved_thread_id / "outputs"
                default_directory.mkdir(parents=True, exist_ok=True)
                parsed_parameters["fMonitorFilename"] = str(default_directory / "monitor1D.dat")
            else:
                # Fallback to relative path
                parsed_parameters["fMonitorFilename"] = "outputs/monitor1D.dat"
        elif parsed_parameters.get("fMonitorFilename") and "outputs/" not in parsed_parameters["fMonitorFilename"]:
            # If filename doesn't include outputs/, prepend it
            filename = os.path.basename(parsed_parameters["fMonitorFilename"])
            if resolved_thread_id:
                from vitess_ai.core.config import global_config
                default_directory = Path(global_config.VITESS_PROJECT_PATH) / resolved_thread_id / "outputs"
                default_directory.mkdir(parents=True, exist_ok=True)
                parsed_parameters["fMonitorFilename"] = str(default_directory / filename)
            else:
                parsed_parameters["fMonitorFilename"] = f"outputs/{filename}"
        
        # Now use the parsed parameters for validation
        validated = Monitor1DParameters(**parsed_parameters)
        cli = monitor1d_params_to_cli(validated.model_dump())
        return {
            "validation_status": True,
            "validated_params": validated.model_dump(),
            "cli_parameters": cli,
            "message": "Monitor1D module parameters are valid!"
        }
       
    except Exception as e:
        return {
            "validation_status": False,
            "errors": str(e),
            "message": f"Monitor1D validation failed: {e}", 
        }


@mcp.tool()  
async def validate_monitor2d_module(parameters: Union[str, dict[str, Any]]) -> dict[str, Any]:
    """
    Validate Monitor2D parameters from either JSON string or dictionary.
    
    Args:
        parameters: Either a JSON string or dictionary containing Monitor2D parameters
        
    Returns:
        Dictionary with validation results including validation_status, validated_params, cli_parameters, and message
    """
    try:
        # Handle both JSON string and dict inputs
        if isinstance(parameters, str):
            try:
                parsed_parameters = json.loads(parameters)
            except json.JSONDecodeError:
                return {
                    "validation_status": False,
                    "errors": "Invalid JSON string format",
                    "message": "Monitor2D validation failed: Invalid JSON string",
                }
        elif isinstance(parameters, dict):
            parsed_parameters = parameters
        else:
            return {
                "validation_status": False,
                "errors": f"Expected JSON string or dict, got {type(parameters)}",
                "message": f"Monitor2D validation failed: Invalid parameter type {type(parameters)}",
            }
        
        # Before validation, ensure fMonitorFilename is set to outputs/ directory if not already set
        # Get thread_id for default path
        resolved_thread_id = os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")
        
        # If fMonitorFilename is not set or doesn't include outputs/, set default
        if "fMonitorFilename" not in parsed_parameters or not parsed_parameters.get("fMonitorFilename"):
            if resolved_thread_id:
                from vitess_ai.core.config import global_config
                default_directory = Path(global_config.VITESS_PROJECT_PATH) / resolved_thread_id / "outputs"
                default_directory.mkdir(parents=True, exist_ok=True)
                parsed_parameters["fMonitorFilename"] = str(default_directory / "monitor2D.dat")
            else:
                # Fallback to relative path
                parsed_parameters["fMonitorFilename"] = "outputs/monitor2D.dat"
        elif parsed_parameters.get("fMonitorFilename") and "outputs/" not in parsed_parameters["fMonitorFilename"]:
            # If filename doesn't include outputs/, prepend it
            filename = os.path.basename(parsed_parameters["fMonitorFilename"])
            if resolved_thread_id:
                from vitess_ai.core.config import global_config
                default_directory = Path(global_config.VITESS_PROJECT_PATH) / resolved_thread_id / "outputs"
                default_directory.mkdir(parents=True, exist_ok=True)
                parsed_parameters["fMonitorFilename"] = str(default_directory / filename)
            else:
                parsed_parameters["fMonitorFilename"] = f"outputs/{filename}"
        
        # Now use the parsed parameters for validation
        validated = Monitor2DParameters(**parsed_parameters)
        cli = monitor2d_params_to_cli(validated.model_dump())
        return {
            "validation_status": True,
            "validated_params": validated.model_dump(),
            "cli_parameters": cli,
            "message": "Monitor2D module parameters are valid!"
        }
       
    except Exception as e:
        return {
            "validation_status": False,
            "errors": str(e),
            "message": f"Monitor2D validation failed: {e}", 
        }


# ============================================================================
# FILE PATH MANAGEMENT TOOLS (Following writeout pattern)
# ============================================================================

@mcp.tool()
async def set_monitor1d_file_path(file_path: str | None = None, thread_id: str | None = None) -> dict[str, Any]:
    """
    Set the output file path for Monitor1D module.
    If no path is provided, automatically sets default to outputs/monitor1D.dat in thread directory.
    Automatically checks file storage if no path is currently selected.
    
    Args:
        file_path: Full path where monitor1D output should be saved (optional, defaults to outputs/monitor1D.dat)
        thread_id: Optional thread ID to construct default path
        
    Returns:
        Dictionary with file path information and status
    """
    global _monitor1d_file_path, _thread_id
    
    # If no file_path provided and no path in memory, try loading from file storage
    if not file_path and not _monitor1d_file_path:
        # Use provided thread_id or try to get from environment
        if thread_id:
            _thread_id = thread_id
        
        if _try_load_monitor1d_path_from_storage():
            # Path loaded from storage, use it
            file_path = _monitor1d_file_path
    
    # Get thread_id from parameter, global, or environment
    resolved_thread_id = thread_id or _thread_id or os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")
    if resolved_thread_id:
        _thread_id = resolved_thread_id
    
    # If no file_path provided, use default: outputs/monitor1D.dat
    if not file_path:
        if resolved_thread_id:
            from vitess_ai.core.config import global_config
            default_directory = Path(global_config.VITESS_PROJECT_PATH) / resolved_thread_id / "outputs"
            default_directory.mkdir(parents=True, exist_ok=True)
            file_path = str(default_directory / "monitor1D.dat")
        else:
            return {
                "success": False,
                "message": "No file path provided and no thread_id available. Please provide either a file_path or thread_id.",
                "file_path": None,
                "fMonitorFilename": None
            }
    
    # Store the file path
    _monitor1d_file_path = file_path
    
    # Get path information
    file_name = os.path.basename(_monitor1d_file_path)
    directory = os.path.dirname(_monitor1d_file_path)
    
    # Ensure directory exists
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as e:
        return {
            "success": False,
            "message": f"❌ Cannot create directory: {directory}\nError: {str(e)}",
            "file_path": _monitor1d_file_path,
            "fMonitorFilename": None,
            "error": str(e)
        }
    
    return {
        "success": True,
        "message": f"✅ Monitor1D output file path set: {file_name}\n📁 Directory: {directory}",
        "file_path": _monitor1d_file_path,
        "file_name": file_name,
        "directory": directory,
        "fMonitorFilename": _monitor1d_file_path  # Key field for Monitor1DParameters
    }


@mcp.tool()
async def set_monitor2d_file_path(file_path: str | None = None, thread_id: str | None = None) -> dict[str, Any]:
    """
    Set the output file path for Monitor2D module.
    If no path is provided, automatically sets default to outputs/monitor2D.dat in thread directory.
    Automatically checks file storage if no path is currently selected.
    
    Args:
        file_path: Full path where monitor2D output should be saved (optional, defaults to outputs/monitor2D.dat)
        thread_id: Optional thread ID to construct default path
        
    Returns:
        Dictionary with file path information and status
    """
    global _monitor2d_file_path, _thread_id
    
    # If no file_path provided and no path in memory, try loading from file storage
    if not file_path and not _monitor2d_file_path:
        # Use provided thread_id or try to get from environment
        if thread_id:
            _thread_id = thread_id
        
        if _try_load_monitor2d_path_from_storage():
            # Path loaded from storage, use it
            file_path = _monitor2d_file_path
    
    # Get thread_id from parameter, global, or environment
    resolved_thread_id = thread_id or _thread_id or os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")
    if resolved_thread_id:
        _thread_id = resolved_thread_id
    
    # If no file_path provided, use default: outputs/monitor2D.dat
    if not file_path:
        if resolved_thread_id:
            from vitess_ai.core.config import global_config
            default_directory = Path(global_config.VITESS_PROJECT_PATH) / resolved_thread_id / "outputs"
            default_directory.mkdir(parents=True, exist_ok=True)
            file_path = str(default_directory / "monitor2D.dat")
        else:
            return {
                "success": False,
                "message": "No file path provided and no thread_id available. Please provide either a file_path or thread_id.",
                "file_path": None,
                "fMonitorFilename": None
            }
    
    # Store the file path
    _monitor2d_file_path = file_path
    
    # Get path information
    file_name = os.path.basename(_monitor2d_file_path)
    directory = os.path.dirname(_monitor2d_file_path)
    
    # Ensure directory exists
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as e:
        return {
            "success": False,
            "message": f"❌ Cannot create directory: {directory}\nError: {str(e)}",
            "file_path": _monitor2d_file_path,
            "fMonitorFilename": None,
            "error": str(e)
        }
    
    return {
        "success": True,
        "message": f"✅ Monitor2D output file path set: {file_name}\n📁 Directory: {directory}",
        "file_path": _monitor2d_file_path,
        "file_name": file_name,
        "directory": directory,
        "fMonitorFilename": _monitor2d_file_path  # Key field for Monitor2DParameters
    }


@mcp.tool()
async def get_monitor1d_file_path(thread_id: str | None = None) -> dict[str, Any]:
    """
    Get the current Monitor1D output file path.
    If no path is set, automatically sets default to outputs/monitor1D.dat in thread directory.
    Automatically checks file storage if no path is currently selected.
    
    Args:
        thread_id: Optional thread ID to construct default path if none is set
        
    Returns:
        Dictionary with file path information ready for Monitor1DParameters
    """
    global _monitor1d_file_path, _thread_id
    
    # If no path in memory, try loading from file storage
    if not _monitor1d_file_path:
        # Use provided thread_id or try to get from environment
        if thread_id:
            _thread_id = thread_id
        
        if _try_load_monitor1d_path_from_storage():
            # Path loaded from storage, continue with retrieval
            pass
    
    # Get thread_id from parameter, global, or environment
    resolved_thread_id = thread_id or _thread_id or os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")
    if resolved_thread_id:
        _thread_id = resolved_thread_id
    
    # If no path set, set default
    if not _monitor1d_file_path:
        if resolved_thread_id:
            from vitess_ai.core.config import global_config
            default_directory = Path(global_config.VITESS_PROJECT_PATH) / resolved_thread_id / "outputs"
            default_directory.mkdir(parents=True, exist_ok=True)
            _monitor1d_file_path = str(default_directory / "monitor1D.dat")
        else:
            return {
                "error": "No file path set",
                "message": "No Monitor1D file path set and no thread_id available. Please provide a thread_id.",
                "fMonitorFilename": None
            }
    
    return {
        "file_path": _monitor1d_file_path,
        "file_name": os.path.basename(_monitor1d_file_path),
        "directory": os.path.dirname(_monitor1d_file_path),
        "fMonitorFilename": _monitor1d_file_path  # Key field for Monitor1DParameters
    }


@mcp.tool()
async def get_monitor2d_file_path(thread_id: str | None = None) -> dict[str, Any]:
    """
    Get the current Monitor2D output file path.
    If no path is set, automatically sets default to outputs/monitor2D.dat in thread directory.
    Automatically checks file storage if no path is currently selected.
    
    Args:
        thread_id: Optional thread ID to construct default path if none is set
        
    Returns:
        Dictionary with file path information ready for Monitor2DParameters
    """
    global _monitor2d_file_path, _thread_id
    
    # If no path in memory, try loading from file storage
    if not _monitor2d_file_path:
        # Use provided thread_id or try to get from environment
        if thread_id:
            _thread_id = thread_id
        
        if _try_load_monitor2d_path_from_storage():
            # Path loaded from storage, continue with retrieval
            pass
    
    # Get thread_id from parameter, global, or environment
    resolved_thread_id = thread_id or _thread_id or os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")
    if resolved_thread_id:
        _thread_id = resolved_thread_id
    
    # If no path set, set default
    if not _monitor2d_file_path:
        if resolved_thread_id:
            from vitess_ai.core.config import global_config
            default_directory = Path(global_config.VITESS_PROJECT_PATH) / resolved_thread_id / "outputs"
            default_directory.mkdir(parents=True, exist_ok=True)
            _monitor2d_file_path = str(default_directory / "monitor2D.dat")
        else:
            return {
                "error": "No file path set",
                "message": "No Monitor2D file path set and no thread_id available. Please provide a thread_id.",
                "fMonitorFilename": None
            }
    
    return {
        "file_path": _monitor2d_file_path,
        "file_name": os.path.basename(_monitor2d_file_path),
        "directory": os.path.dirname(_monitor2d_file_path),
        "fMonitorFilename": _monitor2d_file_path  # Key field for Monitor2DParameters
    }


# ============================================================================
# PLOT GENERATION TOOLS (Optional Visualization)
# ============================================================================

@mcp.tool()
async def generate_plot_1d(monitor_file_path: str) -> dict[str, Any]:
    """
    Generate a 1D plot from monitor data file (optional visualization).
    
    Args:
        monitor_file_path: Path to the monitor1D output file
        
    Returns:
        Dictionary with plot generation status and information
    """
    # TODO: Implement actual plot generation when visualization infrastructure is available
    return {
        "success": False,
        "message": "Plot generation not yet implemented. This feature will be available in a future update.",
        "file_path": monitor_file_path
    }


@mcp.tool()
async def generate_plot_2d(monitor_file_path: str) -> dict[str, Any]:
    """
    Generate a 2D plot from monitor data file (optional visualization).
    
    Args:
        monitor_file_path: Path to the monitor2D output file
        
    Returns:
        Dictionary with plot generation status and information
    """
    # TODO: Implement actual plot generation when visualization infrastructure is available
    return {
        "success": False,
        "message": "Plot generation not yet implemented. This feature will be available in a future update.",
        "file_path": monitor_file_path
    }


if __name__ == "__main__":
    # Support both stdio (development) and http (production) transports
    transport_mode = os.getenv("MCP_TRANSPORT_MODE", "http").lower()
    
    if transport_mode == "http":
        port = int(os.getenv("MCP_MONITOR_PORT", "9004"))
        host = os.getenv("MCP_HOST", "0.0.0.0")
        mcp.run(transport="http", host=host, port=port)
    else:
        mcp.run(transport="stdio")

