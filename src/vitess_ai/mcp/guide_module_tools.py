# guide_module_tools.py
from fastmcp import FastMCP
import json
import os
from vitess_ai.schema.guide_module import GuideParameters
from vitess_ai.schema.base import get_field_flag
from typing import Any, Union

mcp = FastMCP("Guide Parameter Validation Server")

# Global storage for current file list (single session)
_current_files: list[str] = []
_thread_id: str | None = None


def _try_load_files_from_storage() -> bool:
    """
    Try to load files from file storage service if available.
    Returns True if files were loaded, False otherwise.
    """
    global _current_files, _thread_id
    
    # Try to get thread_id from environment variable
    if not _thread_id:
        _thread_id = os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")
    
    if not _thread_id:
        return False
    
    try:
        from vitess_ai.server.file_storage import get_file_storage_service
        
        storage_service = get_file_storage_service()
        file_paths = storage_service.get_file_paths_for_module(_thread_id, "guide")
        
        if file_paths and len(file_paths) > 0:
            _current_files = [file_paths[0]]  # Guide module only allows one file
            return True
    except Exception:
        # If file storage is not available or fails, just continue without it
        pass
    
    return False

def guide_params_to_cli(params:dict) -> str:
    cli_params = list()

    for key, value in params.items():
        flag = get_field_flag(GuideParameters, key)
        
        # Skip None values
        if value is None:
            continue
        
        if isinstance(value, (int, float, str)): 
            cli_params.append((flag, str(value)))

        # Handle enum types (like VtGdeShape)
        elif hasattr(value, 'value'):
            cli_params.append((flag, str(value.value)))

    return ' '.join([f'{flag}{param}' for flag, param in cli_params])

@mcp.tool()  
async def validate_guide_parameters(parameters: Union[str, dict[str, Any]]) -> dict[str, Any]:
    """
    Validate guide parameters from either JSON string or dictionary.
    
    Args:
        parameters: Either a JSON string or dictionary containing guide parameters
        
    Returns:
        Dictionary with validation results
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
        
        # Now use the parsed parameters for validation
        validated = GuideParameters(**parsed_parameters)
        cli = guide_params_to_cli(validated.model_dump())
        return {
            "validation_status": True,
            "validated_params": validated,
            "cli_parameters": cli,
            "message": "Guide module parameters are valid!"
        }
       
    except Exception as e:
        return {
            "validation_status": False,
            "errors": str(e),
            "message": f"Guide validation failed: {e}", 
        }
    
# ============================================================================
# FILE UPLOAD TOOLS (Primary Operations)
# ============================================================================

@mcp.tool()
async def upload_file(file_path: str | None = None, thread_id: str | None = None) -> dict:
    """
    Upload a file for neutron simulation guide input using file path.
    Replaces any previously selected file.
    Automatically checks file storage if no file is currently selected.
    
    Args:
        file_path: Path to the guide file (optional if file is already in storage)
        thread_id: Optional thread ID to check for uploaded files in file storage
    
    Returns:
        Dictionary with file information and status
    """
    global _current_files, _thread_id
    
    # If no file provided and no file in memory, try loading from file storage
    if not file_path and not _current_files:
        # Use provided thread_id or try to get from environment
        if thread_id:
            _thread_id = thread_id
        
        if _try_load_files_from_storage():
            # File loaded from storage, use it
            file_path = _current_files[0] if _current_files else None
    
    try:
        if not file_path:
            return {
                "success": False,
                "message": "No file path provided.",
                "files": [],
                "file_count": 0,
                "existing_files": [],
                "missing_files": []
            }
        
        # Store the file list (replaces any previous files)
        _current_files = [file_path]
        
        # Validate file exists and get info
        if os.path.exists(file_path):
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            
            message_parts = []
            message_parts.append(f"✅ Successfully selected guide file")
            message_parts.append("")
            message_parts.append(f"📄 {file_name} ({file_size:,} bytes)")
            message_parts.append("")
            message_parts.append("💾 File ready for simulation")
            
            return {
                "success": True,
                "message": "\n".join(message_parts),
                "files": [file_path],
                "file_count": 1,
                "existing_files": [file_path],
                "missing_files": [],
                "file_details": [{
                    "path": file_path,
                    "name": file_name,
                    "size": file_size,
                    "exists": True
                }]
            }
        else:
            return {
                "success": False,
                "message": f"⚠️ Selected file does not exist: {file_path}",
                "files": [file_path],
                "file_count": 1,
                "existing_files": [],
                "missing_files": [file_path],
                "file_details": [{
                    "path": file_path,
                    "name": os.path.basename(file_path),
                    "size": 0,
                    "exists": False
                }],
                "error": "File does not exist"
            }
    
    except Exception as e:
        return {
            "success": False,
            "message": f"❌ Error uploading file: {str(e)}",
            "files": [],
            "file_count": 0,
            "existing_files": [],
            "missing_files": [],
            "file_details": [],
            "error": str(e)
        }

@mcp.tool()
async def file_status(thread_id: str | None = None) -> dict:
    """
    Show current guide file selection status.
    Automatically checks file storage if no file is currently selected.
    
    Args:
        thread_id: Optional thread ID to check for uploaded files in file storage
    
    Returns:
        Dictionary with current file status and information
    """
    global _current_files, _thread_id
    
    # If no file in memory, try loading from file storage
    if not _current_files:
        # Use provided thread_id or try to get from environment
        if thread_id:
            _thread_id = thread_id
        
        if _try_load_files_from_storage():
            # File loaded from storage, continue with status check
            pass
    
    if not _current_files:
        return {
            "has_file": False,
            "message": "❌ No guide file selected. Use upload_file() first to select a file.",
            "files": [],
            "file_count": 0,
            "existing_files": [],
            "missing_files": []
        }
    
    # Process file details
    file_path = _current_files[0]
    file_name = os.path.basename(file_path)
    
    if os.path.exists(file_path):
        file_size = os.path.getsize(file_path)
        return {
            "has_file": True,
            "message": f"📋 Current guide file: {file_name} ({file_size:,} bytes)",
            "files": _current_files,
            "file_count": 1,
            "existing_files": _current_files,
            "missing_files": [],
            "file_details": [{
                "path": file_path,
                "name": file_name,
                "size": file_size,
                "exists": True
            }]
        }
    else:
        return {
            "has_file": True,
            "message": f"❌ Selected guide file not found: {file_name}",
            "files": _current_files,
            "file_count": 1,
            "existing_files": [],
            "missing_files": _current_files,
            "file_details": [{
                "path": file_path,
                "name": file_name,
                "size": 0,
                "exists": False
            }],
            "error": "File not found"
        }


@mcp.tool()
async def get_file(thread_id: str | None = None) -> dict[str, Any] | str:
    """
    Get the current selected guide file.
    Automatically checks file storage if no file is currently selected.
    
    Args:
        thread_id: Optional thread ID to check for uploaded files in file storage
        
    Returns:
        Dictionary with file information ready for Vitess
    """
    global _current_files, _thread_id
    
    # If no file in memory, try loading from file storage
    if not _current_files:
        # Use provided thread_id or try to get from environment
        if thread_id:
            _thread_id = thread_id
        
        if _try_load_files_from_storage():
            # File loaded from storage, continue with retrieval
            pass
    
    if not _current_files:
        return "❌ No guide file selected. Use upload_file() first to select a file."
    
    file_path = _current_files[0]
    file_name = os.path.basename(file_path)
    
    return {
        "file": file_path,
        "file_name": file_name,
        "file_count": 1,
        "files": _current_files,
        "exists": os.path.exists(file_path)
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")