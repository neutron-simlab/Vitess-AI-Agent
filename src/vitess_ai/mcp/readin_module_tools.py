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
from vitess_ai.gui.file_upload import FileListManager
from vitess_ai.gui.inst_file_upload import InstrumentFileManager


# Initialize FastMCP server
mcp = FastMCP("Read-in MCP Server")

# Global storage for current file list and instrument file (single session)
_current_files: list[str] = []
_current_instrument_file: str | None = None

# ============================================================================
# GUI HELPER FUNCTIONS
# ============================================================================

async def launch_picker_gui() -> list[str]: # type: ignore
    """
    Launch the GUI file picker and return selected file paths.
    Uses the standard PyQt6 app pattern.
    """
    try:
        # Import PyQt6 here to avoid issues if not available
        from PyQt6.QtWidgets import QApplication
        import sys
        
        # Create QApplication if it doesn't exist
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        
        # Standard PyQt6 pattern
        file_picker = FileListManager()
        file_picker.show()
        
        # This blocks until the window is closed
        app.exec()
        
        # Return the file paths that were selected
        return file_picker.file_paths
        
    except ImportError as e:
        print(f"GUI not available: {e}")
        return []

async def launch_instrument_gui() -> str | None:
    """
    Launch the instrument file GUI and return selected file path.
    Uses the standard PyQt6 app pattern.
    """
    try:
        # Import PyQt6 here to avoid issues if not available
        from PyQt6.QtWidgets import QApplication
        import sys
        
        # Create QApplication if it doesn't exist
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        
        # Standard PyQt6 pattern
        instrument_picker = InstrumentFileManager()
        instrument_picker.show()
        
        # This blocks until the window is closed
        app.exec()
        
        # Return the instrument file path that was selected
        return instrument_picker.instrument_file_path
        
    except ImportError as e:
        print(f"GUI not available: {e}")
        return None
    except Exception as e:
        print(f"Error launching instrument GUI: {e}")
        return None

# ============================================================================
# FILE UPLOAD TOOLS (Primary Operations)
# ============================================================================

@mcp.tool()
async def upload_file_gui(
    title: str = "Select Neutron Simulation Input File(s)",
    file_filter: str = "neutron_files"
) -> dict:
    """
    Upload files for neutron simulation input using GUI file picker.
    Replaces any previously selected files.
    
    Args:
        title: Title for the file picker dialog (for future use)
        file_filter: Type of file filter (for future use)
        
    Returns:
        Dictionary with file information and status
    """
    global _current_files
    
    try:
        # Launch GUI and get file paths
        selected_files = await launch_picker_gui()
        
        if not selected_files:
            return {
                "success": False,
                "message": "No files were selected or GUI was cancelled.",
                "files": [],
                "file_count": 0,
                "existing_files": [],
                "missing_files": [],
                "vitess_sInputFileName": [None] * NF_MAX
            }
        
        # Store the file list (replaces any previous files)
        _current_files = selected_files
        
        # Validate files exist and get info
        existing_files = []
        missing_files = []
        file_details = []
        
        for file_path in selected_files:
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
            "files": selected_files,
            "file_count": len(selected_files),
            "existing_files": existing_files,
            "missing_files": missing_files,
            "file_details": file_details,
            "vitess_sInputFileName": _current_files + [None] * (NF_MAX - len(_current_files))
        }
    
    except Exception as e:
        return {
            "success": False,
            "message": f"❌ Error in file GUI: {str(e)}",
            "files": [],
            "file_count": 0,
            "existing_files": [],
            "missing_files": [],
            "file_details": [],
            "vitess_sInputFileName": [None] * NF_MAX,
            "error": str(e)
        }

@mcp.tool()
async def upload_instrument_file_gui() -> dict:
    """
    Upload instrument file (.inf) for neutron simulation using GUI file picker.
    Replaces any previously selected instrument file.
        
    Returns:
        Dictionary with instrument file information and status
    """
    global _current_instrument_file
    
    try:
        # Launch instrument GUI and get file path
        selected_file = await launch_instrument_gui()
        
        if not selected_file:
            return {
                "success": False,
                "message": "❌ No instrument file was selected or GUI was cancelled.",
                "instrument_file": None,
                "file_name": None,
                "directory": None,
                "file_size": 0,
                "exists": False,
                "vitess_sInstrInfIn": None
            }
        
        # Store the instrument file (replaces any previous file)
        _current_instrument_file = selected_file
        
        # Validate file exists and get info
        if os.path.exists(selected_file):
            file_name = os.path.basename(selected_file)
            file_size = os.path.getsize(selected_file)
            directory = os.path.dirname(selected_file)
            
            # Get modification time
            import datetime
            mod_time = os.path.getmtime(selected_file)
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
                "instrument_file": selected_file,
                "file_name": file_name,
                "directory": directory,
                "file_size": file_size,
                "modified_date": mod_date,
                "exists": True,
                "vitess_sInstrInfIn": selected_file
            }
        else:
            return {
                "success": False,
                "message": f"⚠️ Selected file does not exist: {selected_file}",
                "instrument_file": selected_file,
                "file_name": os.path.basename(selected_file),
                "directory": os.path.dirname(selected_file),
                "file_size": 0,
                "exists": False,
                "vitess_sInstrInfIn": None,
                "error": "File does not exist"
            }
        
    except Exception as e:
        return {
            "success": False,
            "message": f"❌ Error in instrument file GUI: {str(e)}",
            "instrument_file": None,
            "file_name": None,
            "directory": None,
            "file_size": 0,
            "exists": False,
            "vitess_sInstrInfIn": None,
            "error": str(e)
        }

# ============================================================================
# FILE STATUS TOOLS (Information Retrieval)
# ============================================================================

@mcp.tool()
async def file_status() -> dict:
    """
    Show current file selection status.
        
    Returns:
        Dictionary with current file status and information
    """
    global _current_files
    
    if not _current_files:
        return {
            "has_files": False,
            "message": "📂 No files currently selected. Use upload_file_gui() to select files.",
            "files": [],
            "file_count": 0,
            "file_details": [],
            "existing_files": [],
            "missing_files": [],
            "vitess_sInputFileName": [None] * NF_MAX
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
        "vitess_sInputFileName": _current_files + [None] * (NF_MAX - len(_current_files))
    }

@mcp.tool()
async def instrument_file_status() -> dict:
    """
    Show current instrument file selection status.
        
    Returns:
        Dictionary with current instrument file status and information
    """
    global _current_instrument_file
    
    if not _current_instrument_file:
        return {
            "has_file": False,
            "message": "📂 No instrument file currently selected. Use upload_instrument_file_gui() to select a file.",
            "instrument_file": None,
            "file_name": None,
            "directory": None,
            "file_size": 0,
            "exists": False,
            "modified_date": None,
            "vitess_sInstrInfIn": None
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
            "vitess_sInstrInfIn": _current_instrument_file
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
            "vitess_sInstrInfIn": None,
            "error": "File not found"
        }

# ============================================================================
# FILE RETRIEVAL TOOLS (Data Access)
# ============================================================================

@mcp.tool()
async def get_files() -> dict[str, Any] | str:
    """
    Get the current list of selected files.
        
    Returns:
        JSON string with file information ready for Vitess
    """
    global _current_files
    
    if not _current_files:
        return "❌ No files selected. Use upload_file_gui() first to select files."
    
    # Create the response with file info
    response = {
        "file_count": len(_current_files),
        "files": _current_files,
        "vitess_sInputFileName": _current_files + [None] * (NF_MAX - len(_current_files))
    }

    return response

@mcp.tool()
async def get_instrument_file() -> dict[str, str] | str:
    """
    Get the current selected instrument file.
        
    Returns:
        dict with instrument file information ready for Vitess
    """
    global _current_instrument_file
    
    if not _current_instrument_file:
        return "❌ No instrument file selected. Use upload_instrument_file_gui() first to select a file."
    
    # Create the response with file info
    response = {
        "instrument_file": _current_instrument_file,
        "file_name": os.path.basename(_current_instrument_file),
        "directory": os.path.dirname(_current_instrument_file),
        "exists": os.path.exists(_current_instrument_file),
        "vitess_sInstrInfIn": _current_instrument_file
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
            "vitess_sInstrInfIn": None
        }
    else:
        return {
            "success": True,
            "message": "ℹ️ No instrument file to clear",
            "cleared_file": None,
            "cleared_file_name": None,
            "has_instrument_file": False,
            "vitess_sInstrInfIn": None
        }

# ============================================================================
# VALIDATION TOOLS (Parameter Validation)
# ============================================================================

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
        validated = ReadInParameters(**params)
        return {
            "valid": True,
            "validated_params": validated,
            "message": "Read-in module parameters are valid!"
        }
    except Exception as e:
        return {
            "valid": False,
            "errors": str(e),
            "message": f"Read-in validation failed: {e}"
        }

# ============================================================================
# MAIN SERVER ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    mcp.run(transport="stdio")