"""
writeout_module_tools.py
Main MCP server consisting of tools for Writeout module agent.
"""

import os
import json

from fastmcp import FastMCP
from typing import Any

# Import our modules
from vitess_ai.schema.writeout_module import WriteoutParameters
from vitess_ai.gui.file_save import FileSaveManager


# Initialize FastMCP server
mcp = FastMCP("Writeout MCP Server")

# Global storage for current save path (single session)
_current_save_path: str | None = None

# ============================================================================
# GUI HELPER FUNCTIONS
# ============================================================================

async def launch_save_gui() -> str | None:
    """
    Launch the GUI file save dialog and return selected file path.
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
        file_saver = FileSaveManager()
        file_saver.show()
        
        # This blocks until the window is closed
        app.exec()
        
        # Return the file path that was selected
        return file_saver.save_file_path
        
    except ImportError as e:
        print(f"GUI not available: {e}")
        return None
    except Exception as e:
        print(f"Error launching save GUI: {e}")
        return None

# ============================================================================
# FILE SAVE TOOLS (Primary Operations)
# ============================================================================

@mcp.tool()
async def save_file_gui(
    title: str = "Save Neutron Simulation Output File",
    default_name: str = "neutron_output.out",
    file_filter: str = "output_files"
) -> dict:
    """
    Select save location and filename for neutron simulation output using GUI.
    Replaces any previously selected save path.
    
    Args:
        title: Title for the save dialog (for future use)
        default_name: Default filename to suggest
        file_filter: Type of file filter (for future use)
        
    Returns:
        Dictionary with save path information and status
    """
    global _current_save_path
    
    try:
        # Launch GUI and get save path
        selected_path = await launch_save_gui()
        
        if not selected_path:
            return {
                "success": False,
                "message": "No save location was selected or GUI was cancelled.",
                "save_path": None,
                "file_name": None,
                "directory": None,
                "file_exists": False,
                "can_write": False,
                "sOutFileName": None
            }
        
        # Store the save path (replaces any previous path)
        _current_save_path = selected_path
        
        # Get path information
        file_name = os.path.basename(selected_path)
        directory = os.path.dirname(selected_path)
        file_exists = os.path.exists(selected_path)
        
        # Check if directory exists and is writable
        dir_exists = os.path.exists(directory)
        can_write = os.access(directory, os.W_OK) if dir_exists else False
        
        # Create directory if it doesn't exist
        if not dir_exists:
            try:
                os.makedirs(directory, exist_ok=True)
                can_write = True
                dir_created = True
            except OSError as e:
                return {
                    "success": False,
                    "message": f"❌ Cannot create directory: {directory}\nError: {str(e)}",
                    "save_path": selected_path,
                    "file_name": file_name,
                    "directory": directory,
                    "file_exists": file_exists,
                    "can_write": False,
                    "sOutFileName": None,
                    "error": str(e)
                }
        else:
            dir_created = False
        
        # Create human-readable message
        message_parts = []
        message_parts.append("✅ Successfully selected save location")
        message_parts.append("")
        message_parts.append(f"📄 File: {file_name}")
        message_parts.append(f"📁 Directory: {directory}")
        
        if dir_created:
            message_parts.append("📂 Directory created successfully")
        
        if file_exists:
            message_parts.append("⚠️  File already exists and will be overwritten")
        
        if can_write:
            message_parts.append("✅ Directory is writable")
        else:
            message_parts.append("❌ Directory is not writable")
        
        message_parts.append("")
        message_parts.append("💾 Save location ready for output")
        message_parts.append("📋 Use get_save_path() to retrieve the path")
        
        # Return structured response
        return {
            "success": True,
            "message": "\n".join(message_parts),
            "save_path": selected_path,
            "file_name": file_name,
            "directory": directory,
            "file_exists": file_exists,
            "can_write": can_write,
            "directory_created": dir_created,
            "sOutFileName": selected_path  # Key field for WriteoutParameters
        }
    
    except Exception as e:
        return {
            "success": False,
            "message": f"❌ Error in save GUI: {str(e)}",
            "save_path": None,
            "file_name": None,
            "directory": None,
            "file_exists": False,
            "can_write": False,
            "sOutFileName": None,
            "error": str(e)
        }

# ============================================================================
# FILE SAVE STATUS TOOLS (Information Retrieval)
# ============================================================================

@mcp.tool()
async def save_path_status() -> dict:
    """
    Show current save path selection status.
        
    Returns:
        Dictionary with current save path status and information
    """
    global _current_save_path
    
    if not _current_save_path:
        return {
            "has_save_path": False,
            "message": "📂 No save location currently selected. Use save_file_gui() to select a location.",
            "save_path": None,
            "file_name": None,
            "directory": None,
            "file_exists": False,
            "can_write": False,
            "vitess_sOutFileName": None
        }
    
    file_name = os.path.basename(_current_save_path)
    directory = os.path.dirname(_current_save_path)
    file_exists = os.path.exists(_current_save_path)
    
    # Check directory status
    dir_exists = os.path.exists(directory)
    can_write = os.access(directory, os.W_OK) if dir_exists else False
    
    # Get file size if it exists
    file_size = 0
    if file_exists:
        try:
            file_size = os.path.getsize(_current_save_path)
        except OSError:
            file_size = 0
    
    # Create human-readable message
    message_parts = []
    message_parts.append("📋 Current save location:")
    message_parts.append("")
    message_parts.append(f"📄 File: {file_name}")
    message_parts.append(f"📁 Directory: {directory}")
    
    if file_exists:
        message_parts.append(f"📊 Current size: {file_size:,} bytes")
        message_parts.append("⚠️  File exists and will be overwritten")
    else:
        message_parts.append("📄 New file will be created")
    
    if dir_exists:
        if can_write:
            message_parts.append("✅ Directory is writable")
        else:
            message_parts.append("❌ Directory is not writable")
    else:
        message_parts.append("❌ Directory does not exist")
    
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
                    "sOutFileName": _current_save_path
    }

# ============================================================================
# FILE SAVE RETRIEVAL TOOLS (Data Access)
# ============================================================================

@mcp.tool()
async def get_save_path() -> dict[str, Any] | str:
    """
    Get the current selected save path.
        
    Returns:
        Dictionary with save path information ready for Vitess WriteoutParameters
    """
    global _current_save_path
    
    if not _current_save_path:
        return "❌ No save location selected. Use save_file_gui() first to select a location."
    
    # Create the response with path info
    response = {
        "save_path": _current_save_path,
        "file_name": os.path.basename(_current_save_path),
        "directory": os.path.dirname(_current_save_path),
        "file_exists": os.path.exists(_current_save_path),
        "can_write": os.access(os.path.dirname(_current_save_path), os.W_OK) if os.path.exists(os.path.dirname(_current_save_path)) else False,
        "sOutFileName": _current_save_path  # This is the key field for WriteoutParameters
    }
    
    return response

# ============================================================================
# FILE SAVE CLEANUP TOOLS (Reset Operations)
# ============================================================================

@mcp.tool()
async def clear_save_path() -> dict:
    """
    Clear the current save path selection.
        
    Returns:
        Dictionary with clear operation status
    """
    global _current_save_path
    
    if _current_save_path:
        file_name = os.path.basename(_current_save_path)
        cleared_path = _current_save_path
        _current_save_path = None
        
        return {
            "success": True,
            "message": f"✅ Cleared save location: {file_name}",
            "cleared_path": cleared_path,
            "cleared_file_name": file_name,
            "has_save_path": False,
            "vitess_sOutFileName": None
        }
    else:
        return {
            "success": True,
            "message": "ℹ️ No save location to clear",
            "cleared_path": None,
            "cleared_file_name": None,
            "has_save_path": False,
            "vitess_sOutFileName": None
        }

# ============================================================================
# VALIDATION TOOLS (Parameter Validation)
# ============================================================================

@mcp.tool()  
async def validate_writeout_module(parameters: str) -> dict:
    """
    Validate Writeout module parameters
    
    Args:
        parameters: JSON string containing WriteoutParameters data
        
    Returns:
        Dictionary with validation results
    """
    try:
        params = json.loads(parameters)
        validated = WriteoutParameters(**params)
        return {
            "valid": True,
            "validated_params": validated,
            "message": "Writeout module parameters are valid!"
        }
    except Exception as e:
        return {
            "valid": False,
            "errors": str(e),
            "message": f"Writeout validation failed: {e}"
        }

# ============================================================================
# MAIN SERVER ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    mcp.run(transport="stdio")