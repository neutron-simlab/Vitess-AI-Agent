"""
readin_module_tools.py
Main MCP server consisting of tools for Read-in module agent.
"""

import os
import json

from fastmcp import FastMCP
from typing import Any

# Import our modules
from vitess_ai.schema.readin_module import NF_MAX, ReadInParameters
from vitess_ai.schema.base import get_field_flag


# Initialize FastMCP server
mcp = FastMCP("Read-in MCP Server")

# Global storage for current file list and instrument file (single session)
_current_files: list[str] = []
_current_instrument_file: str | None = None
_thread_id: str | None = None


def _try_load_files_from_storage(thread_id: str | None = None) -> bool:
    """
    Try to load files from file storage service if available.
    Returns True if files were loaded, False otherwise.
    
    Args:
        thread_id: Optional thread ID to use (takes priority over environment variables)
    """
    global _current_files, _thread_id
    import logging
    logger = logging.getLogger(__name__)
    
    # Use provided thread_id first, then try environment variable, then global
    if thread_id:
        _thread_id = thread_id
    elif not _thread_id:
        _thread_id = os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")
    
    if not _thread_id:
        logger.error("No thread_id available (not provided, not in environment, not in global state)")
        return False
    
    try:
        from vitess_ai.server.file_storage import get_file_storage_service
        
        storage_service = get_file_storage_service()
        file_paths = storage_service.get_file_paths_for_module(_thread_id, "readin")
        
        if file_paths:
            _current_files = file_paths[:NF_MAX]
            logger.debug(f"Loaded {len(_current_files)} files from storage for thread_id={_thread_id}")
            return True
        else:
            logger.debug(f"No files found in storage for thread_id={_thread_id}, module_type=readin")
    except Exception as e:
        logger.error(f"Exception in _try_load_files_from_storage: {e}", exc_info=True)
    
    return False


def _try_load_instrument_file_from_storage(thread_id: str | None = None) -> bool:
    """
    Try to load instrument file from file storage service if available.
    Returns True if file was loaded, False otherwise.
    
    Args:
        thread_id: Optional thread ID to use (takes priority over environment variables)
    """
    global _current_instrument_file, _thread_id
    import logging
    logger = logging.getLogger(__name__)
    
    # Use provided thread_id first, then try environment variable, then global
    if thread_id:
        _thread_id = thread_id
    elif not _thread_id:
        _thread_id = os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")
    
    if not _thread_id:
        logger.debug("No thread_id available for instrument file loading")
        return False
    
    try:
        from vitess_ai.server.file_storage import get_file_storage_service
        
        storage_service = get_file_storage_service()
        file_paths = storage_service.get_file_paths_for_module(_thread_id, "instrument")
        
        if file_paths and len(file_paths) > 0:
            _current_instrument_file = file_paths[0]
            logger.debug(f"Loaded instrument file from storage: {_current_instrument_file}")
            return True
        else:
            logger.debug(f"No instrument file found in storage for thread_id={_thread_id}")
    except Exception as e:
        logger.error(f"Failed to load instrument file from storage for thread_id={_thread_id}: {e}", exc_info=True)
    
    return False

# ============================================================================
# FILE UPLOAD TOOLS (Primary Operations)
# ============================================================================

@mcp.tool()
async def upload_file(
    file_paths: list[str]
) -> dict:
    """
    Upload files for neutron simulation input using file paths.
    Replaces any previously selected files.
    
    Args:
        file_paths: List of file paths to upload
        
    Returns:
        Dictionary with file information and status
    """
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
                "sInputFileName": [None] * NF_MAX
            }
        
        # Validate file count (max NF_MAX)
        if len(file_paths) > NF_MAX:
            return {
                "success": False,
                "message": f"Too many files. Maximum is {NF_MAX} files.",
                "files": [],
                "file_count": 0,
                "existing_files": [],
                "missing_files": [],
                "sInputFileName": [None] * NF_MAX
            }
        
        # Store the file list (replaces any previous files)
        _current_files = file_paths[:NF_MAX]
        
        # Validate files exist and get info
        existing_files = []
        missing_files = []
        file_details = []
        
        for file_path in _current_files:
            if os.path.exists(file_path):
                existing_files.append(file_path)
                file_details.append({
                    "path": file_path,
                    "name": os.path.basename(file_path),
                    "size": os.path.getsize(file_path),
                    "exists": True
                })
            else:
                missing_files.append(file_path)
                file_details.append({
                    "path": file_path,
                    "name": os.path.basename(file_path),
                    "size": 0,
                    "exists": False
                })
        
        # Create human-readable message
        message_parts = []
        message_parts.append(f"✅ Successfully selected {len(existing_files)} files")
        message_parts.append("")
        
        for i, file_path in enumerate(existing_files, 1):
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            message_parts.append(f"  {i}. {file_name} ({file_size:,} bytes)")
        
        if missing_files:
            message_parts.append(f"\n⚠️  Warning: {len(missing_files)} files not found:")
            for file_path in missing_files:
                message_parts.append(f"  ❌ {os.path.basename(file_path)}")
        
        message_parts.append("\n💾 Files ready for simulation")
        message_parts.append("📋 Use get_files() to retrieve the file list")
        
        # Return structured response
        return {
            "success": True,
            "message": "\n".join(message_parts),
            "files": _current_files,
            "file_count": len(_current_files),
            "existing_files": existing_files,
            "missing_files": missing_files,
            "file_details": file_details,
            "sInputFileName": _current_files + [None] * (NF_MAX - len(_current_files))
        }
    
    except Exception as e:
        return {
            "success": False,
            "message": f"❌ Error uploading files: {str(e)}",
            "files": [],
            "file_count": 0,
            "existing_files": [],
            "missing_files": [],
            "file_details": [],
            "sInputFileName": [None] * NF_MAX,
            "error": str(e)
        }

@mcp.tool()
async def set_files(file_paths: list[str]) -> dict:
    """
    Set file paths directly without validation.
    Useful when file paths are already validated.
    
    Args:
        file_paths: List of file paths to set
        
    Returns:
        Dictionary with operation status
    """
    global _current_files
    
    try:
        # Limit to NF_MAX
        _current_files = file_paths[:NF_MAX]
        
        return {
            "success": True,
            "message": f"✅ Set {len(_current_files)} file(s)",
            "files": _current_files,
            "file_count": len(_current_files),
            "sInputFileName": _current_files + [None] * (NF_MAX - len(_current_files))
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"❌ Error setting files: {str(e)}",
            "files": [],
            "file_count": 0,
            "sInputFileName": [None] * NF_MAX,
            "error": str(e)
        }

@mcp.tool()
async def upload_instrument_file(instrument_file_path: str) -> dict:
    """
    Upload instrument file (.inf) for neutron simulation using file path.
    Replaces any previously selected instrument file.
    
    Args:
        instrument_file_path: Path to the instrument file
        
    Returns:
        Dictionary with instrument file information and status
    """
    global _current_instrument_file
    
    try:
        if not instrument_file_path:
            return {
                "success": False,
                "message": "❌ No instrument file path provided.",
                "instrument_file": None,
                "file_name": None,
                "directory": None,
                "file_size": 0,
                "exists": False,
                "sInstrInfIn": None
            }
        
        # Store the instrument file (replaces any previous file)
        _current_instrument_file = instrument_file_path
        
        # Validate file exists and get info
        if os.path.exists(_current_instrument_file):
            file_name = os.path.basename(_current_instrument_file)
            file_size = os.path.getsize(_current_instrument_file)
            directory = os.path.dirname(_current_instrument_file)
            
            # Get modification time
            import datetime
            mod_time = os.path.getmtime(_current_instrument_file)
            mod_date = datetime.datetime.fromtimestamp(mod_time).strftime("%Y-%m-%d %H:%M:%S")
            
            # Create human-readable message
            message_parts = []
            message_parts.append("✅ Successfully selected instrument file")
            message_parts.append("")
            message_parts.append(f"📄 {file_name} ({file_size:,} bytes)")
            message_parts.append(f"📁 {directory}")
            message_parts.append(f"🕒 Modified: {mod_date}")
            message_parts.append("")
            message_parts.append("💾 Instrument file ready for simulation")
            message_parts.append("📋 Use get_instrument_file() to retrieve the file path")
            
            return {
                "success": True,
                "message": "\n".join(message_parts),
                "instrument_file": _current_instrument_file,
                "file_name": file_name,
                "directory": directory,
                "file_size": file_size,
                "modified_date": mod_date,
                "exists": True,
                "sInstrInfIn": _current_instrument_file
            }
        else:
            return {
                "success": False,
                "message": f"⚠️ Selected file does not exist: {_current_instrument_file}",
                "instrument_file": _current_instrument_file,
                "file_name": os.path.basename(_current_instrument_file),
                "directory": os.path.dirname(_current_instrument_file),
                "file_size": 0,
                "exists": False,
                "sInstrInfIn": None,
                "error": "File does not exist"
            }
        
    except Exception as e:
        return {
            "success": False,
            "message": f"❌ Error uploading instrument file: {str(e)}",
            "instrument_file": None,
            "file_name": None,
            "directory": None,
            "file_size": 0,
            "exists": False,
            "sInstrInfIn": None,
            "error": str(e)
        }

# ============================================================================
# FILE STATUS TOOLS (Information Retrieval)
# ============================================================================

@mcp.tool()
async def file_status(thread_id: str | None = None) -> dict:
    """
    Show current file selection status.
    Automatically checks file storage if no files are currently selected.
    
    IMPORTANT: Always pass the thread_id parameter when calling this tool. 
    The thread_id is available from the conversation context or state.
    If thread_id is not provided, the tool will attempt to find it from environment variables,
    but this may fail if the environment variables are not set in the MCP subprocess.
    
    Args:
        thread_id: REQUIRED thread ID to check for uploaded files in file storage.
                   This should be the current conversation/thread ID from the system state.
    
    Returns:
        Dictionary with current file status and information
    """
    global _current_files, _thread_id
    import logging
    logger = logging.getLogger(__name__)
    
    # If no files in memory, try loading from file storage
    if not _current_files:
        # Use provided thread_id first, then try to get from environment, then try global
        if thread_id:
            _thread_id = thread_id
        elif not _thread_id:
            env_thread_id = os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")
            if env_thread_id:
                _thread_id = env_thread_id
            else:
                logger.warning("No thread_id found in environment variables. Pass thread_id as a parameter when calling this tool.")
        
        if _thread_id:
            if _try_load_files_from_storage(_thread_id):
                logger.debug(f"Loaded {len(_current_files)} files from storage")
            else:
                logger.debug(f"Failed to load files from storage for thread_id={_thread_id}")
        else:
            logger.warning("Cannot load files - no thread_id available!")
    
    if not _current_files:
        logger.debug(f"No files found after all attempts (thread_id={_thread_id})")
        return {
            "has_files": False,
            "message": "❌ No files selected. Use file_status() to check if files are uploaded via Streamlit UI, or use upload_file() with file paths.",
            "files": [],
            "file_count": 0,
            "file_details": [],
            "existing_files": [],
            "missing_files": [],
            "sInputFileName": [None] * NF_MAX,
            "debug_info": {
                "thread_id": _thread_id,
                "env_thread_id": os.environ.get("THREAD_ID"),
                "env_vitess_thread_id": os.environ.get("VITESS_THREAD_ID")
            }
        }
    
    # Process file details
    file_details = []
    existing_files = []
    missing_files = []
    
    for i, file_path in enumerate(_current_files, 1):
        file_name = os.path.basename(file_path)
        if os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
            existing_files.append(file_path)
            file_details.append({
                "index": i,
                "path": file_path,
                "name": file_name,
                "size": file_size,
                "exists": True
            })
        else:
            missing_files.append(file_path)
            file_details.append({
                "index": i,
                "path": file_path,
                "name": file_name,
                "size": 0,
                "exists": False
            })
    
    # Create human-readable message
    message_parts = [f"📋 Current selection: {len(_current_files)} files"]
    message_parts.append("")
    
    for detail in file_details:
        if detail["exists"]:
            message_parts.append(f"  ✅ {detail['index']}. {detail['name']} ({detail['size']:,} bytes)")
        else:
            message_parts.append(f"  ❌ {detail['index']}. {detail['name']} (FILE NOT FOUND)")
    
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
        "sInputFileName": _current_files + [None] * (NF_MAX - len(_current_files))
    }

@mcp.tool()
async def instrument_file_status(thread_id: str | None = None) -> dict:
    """
    Show current instrument file selection status.
    Automatically checks file storage if no file is currently selected.
    
    Args:
        thread_id: Optional thread ID to check for uploaded files in file storage
        
    Returns:
        Dictionary with current instrument file status and information
    """
    global _current_instrument_file, _thread_id
    
    # If no file in memory, try loading from file storage
    if not _current_instrument_file:
        # Use provided thread_id or try to get from environment
        if thread_id:
            _thread_id = thread_id
        
        if _try_load_instrument_file_from_storage():
            # File loaded from storage, continue with status check
            pass
    
    if not _current_instrument_file:
        return {
            "has_file": False,
            "message": "📂 No instrument file currently selected. Use instrument_file_status() to check if a file is uploaded via Streamlit UI, or use upload_instrument_file() with file path.",
            "instrument_file": None,
            "file_name": None,
            "directory": None,
            "file_size": 0,
            "exists": False,
            "modified_date": None,
            "sInstrInfIn": None
        }
    
    file_name = os.path.basename(_current_instrument_file)
    directory = os.path.dirname(_current_instrument_file)
    
    if os.path.exists(_current_instrument_file):
        file_size = os.path.getsize(_current_instrument_file)
        
        # Get modification time
        import datetime
        mod_time = os.path.getmtime(_current_instrument_file)
        mod_date = datetime.datetime.fromtimestamp(mod_time).strftime("%Y-%m-%d %H:%M:%S")
        
        # Create human-readable message
        message_parts = []
        message_parts.append("📋 Current instrument file:")
        message_parts.append("")
        message_parts.append(f"  ✅ {file_name} ({file_size:,} bytes)")
        message_parts.append(f"  📁 {directory}")
        message_parts.append(f"  🕒 Modified: {mod_date}")
        
        return {
            "has_file": True,
            "message": "\n".join(message_parts),
            "instrument_file": _current_instrument_file,
            "file_name": file_name,
            "directory": directory,
            "file_size": file_size,
            "exists": True,
            "modified_date": mod_date,
            "sInstrInfIn": _current_instrument_file
        }
    else:
        return {
            "has_file": True,
            "message": f"❌ Selected instrument file not found: {file_name}",
            "instrument_file": _current_instrument_file,
            "file_name": file_name,
            "directory": directory,
            "file_size": 0,
            "exists": False,
            "modified_date": None,
            "sInstrInfIn": None,
            "error": "File not found"
        }

# ============================================================================
# FILE RETRIEVAL TOOLS (Data Access)
# ============================================================================

@mcp.tool()
async def get_files(thread_id: str | None = None) -> dict[str, Any] | str:
    """
    Get the current list of selected files.
    Automatically checks file storage if no files are currently selected.
    
    Args:
        thread_id: Optional thread ID to check for uploaded files in file storage
        
    Returns:
        JSON string with file information ready for Vitess
    """
    global _current_files, _thread_id
    
    # If no files in memory, try loading from file storage
    if not _current_files:
        # Use provided thread_id or try to get from environment
        if thread_id:
            _thread_id = thread_id
        
        if _try_load_files_from_storage():
            # Files loaded from storage, continue with retrieval
            pass
    
    if not _current_files:
        return "❌ No files selected. Use file_status() to check if files are uploaded via Streamlit UI, or use upload_file() with file paths."
    
    # Create the response with file info
    response = {
        "file_count": len(_current_files),
        "files": _current_files,
        "sInputFileName": _current_files + [None] * (NF_MAX - len(_current_files))
    }

    return response

@mcp.tool()
async def get_instrument_file(thread_id: str | None = None) -> dict[str, str] | str:
    """
    Get the current selected instrument file.
    Automatically checks file storage if no file is currently selected.
    
    Args:
        thread_id: Optional thread ID to check for uploaded files in file storage
        
    Returns:
        dict with instrument file information ready for Vitess
    """
    global _current_instrument_file, _thread_id
    
    # If no file in memory, try loading from file storage
    if not _current_instrument_file:
        # Use provided thread_id or try to get from environment
        if thread_id:
            _thread_id = thread_id
        
        if _try_load_instrument_file_from_storage():
            # File loaded from storage, continue with retrieval
            pass
    
    if not _current_instrument_file:
        return "❌ No instrument file selected. Use instrument_file_status() to check if a file is uploaded via Streamlit UI, or use upload_instrument_file() with file path."
    
    # Create the response with file info
    response = {
        "instrument_file": _current_instrument_file,
        "file_name": os.path.basename(_current_instrument_file),
        "directory": os.path.dirname(_current_instrument_file),
        "exists": os.path.exists(_current_instrument_file),
        "sInstrInfIn": _current_instrument_file
    }
    
    return response

# ============================================================================
# FILE CLEANUP TOOLS (Reset Operations)
# ============================================================================

@mcp.tool()
async def clear_files() -> dict:
    """
    Clear the current file selection.
        
    Returns:
        Dictionary with clear operation status
    """
    global _current_files
    
    if _current_files:
        file_count = len(_current_files)
        cleared_files = _current_files.copy()  # Store for response
        _current_files = []
        
        return {
            "success": True,
            "message": f"✅ Cleared {file_count} files",
            "cleared_count": file_count,
            "cleared_files": cleared_files,
            "remaining_files": [],
            "has_files": False
        }
    else:
        return {
            "success": True,
            "message": "ℹ️ No files to clear",
            "cleared_count": 0,
            "cleared_files": [],
            "remaining_files": [],
            "has_files": False
        }

@mcp.tool()
async def clear_instrument_file() -> dict:
    """
    Clear the current instrument file selection.
        
    Returns:
        Dictionary with clear operation status
    """
    global _current_instrument_file
    
    if _current_instrument_file:
        file_name = os.path.basename(_current_instrument_file)
        cleared_file = _current_instrument_file
        _current_instrument_file = None
        
        return {
            "success": True,
            "message": f"✅ Cleared instrument file: {file_name}",
            "cleared_file": cleared_file,
            "cleared_file_name": file_name,
            "has_instrument_file": False,
            "sInstrInfIn": None
        }
    else:
        return {
            "success": True,
            "message": "ℹ️ No instrument file to clear",
            "cleared_file": None,
            "cleared_file_name": None,
            "has_instrument_file": False,
            "sInstrInfIn": None
        }

# ============================================================================
# VALIDATION and CLI TOOLS (Parameter Validation)
# ============================================================================

def readin_params_to_cli(params: dict)-> str:
    cli_params = list()

    for key, value in params.items():
        flag = get_field_flag(ReadInParameters, key)
        
        # Skip None values
        if value is None:
            continue
        
        if isinstance(value, (int, float, str)): 
            cli_params.append((flag, str(value)))
        
        elif isinstance(value, list):
            if key in ['sInputFileName', 'Weight']: 
                flags = flag.split(" ")
                for i, val in enumerate(value):
                    if i < len(flags):  # Safety check to avoid index errors
                        cli_params.append((flags[i], str(val)))
            else:
                # Handle other list types if needed
                for val in value:
                    cli_params.append((flag, str(val)))
        
        # Handle enum types (like VtPrgFormat, VtDataFormat, VtTrace)
        elif hasattr(value, 'value'):
            cli_params.append((flag, str(value.value)))

    # Build the CLI string properly
    # This wil make e.g., "-f2 -F1 -Afile1.dat -Bfile2.dat -a1.0"
    return ' '.join([f'{flag}{param}' for flag, param in cli_params])

@mcp.tool()  
async def validate_readin_module(parameters: str) -> dict:
    """
    Validate Read-in module parameters
    
    Args:
        parameters: JSON string containing ReadInParameters data
        
    Returns:
        Dictionary with validation results
    """
    try:
        params = json.loads(parameters)

        # Backfill sInputFileName from multiple possible sources if missing/empty
        global _current_files
        if not params.get("sInputFileName"):
            candidate_files = None
            # 1) Provided inline as 'files' from upload_file response
            if isinstance(params.get("files"), list) and params["files"]:
                candidate_files = params["files"]
            # 2) Provided inline as 'existing_files'
            elif isinstance(params.get("existing_files"), list) and params["existing_files"]:
                candidate_files = params["existing_files"]
            # 3) Use persisted selection if same MCP process
            elif _current_files:
                candidate_files = _current_files

            if candidate_files:
                # Pad to NF_MAX with None
                params["sInputFileName"] = candidate_files + [None] * (NF_MAX - len(candidate_files))
            else:
                return {
                    "validation_status": False,
                    "errors": "sInputFileName is required but not provided and no files selected.",
                    "message": "Please select input files via Streamlit UI or use upload_file() with file paths, or provide sInputFileName."
                }

        # Enforce Weight presence and matching length to non-None files
        files_list = [p for p in params.get("sInputFileName", []) if p is not None]
        weights_list = params.get("Weight", [])
        if not isinstance(weights_list, list):
            return {
                "validation_status": False,
                "errors": "Weight must be a list of numbers matching sInputFileName.",
                "message": "Weight must be a list."
            }
        if len(files_list) == 0:
            return {
                "validation_status": False,
                "errors": "At least one input file is required.",
                "message": "Please select at least one input file."
            }
        if len(weights_list) != len(files_list):
            return {
                "validation_status": False,
                "errors": f"Weight length ({len(weights_list)}) does not match sInputFileName count ({len(files_list)}).",
                "message": "Provide a weight for each input file."
            }

        validated = ReadInParameters(**params)
        validated = validated.model_dump()
        cli = readin_params_to_cli(validated) # function to parse the flag and value for Vitess CLI
        return {
            "validation_status": True,
            "validated_params": validated,
            "cli_parameters": cli,
            "message": "Read-in module parameters are valid!"
        }
    except Exception as e:
        return {
            "validation_status": False,
            "errors": str(e),
            "message": f"Read-in validation failed: {e}"
        }

# ============================================================================
# MAIN SERVER ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    mcp.run(transport="stdio")