# guide_module_tools.py
from mcp.server.fastmcp import FastMCP
import json
import os
from vitess_ai.gui.file_upload_guide import GuideFileListManager
from vitess_ai.schema.guide_module import GuideParameters
from vitess_ai.schema.base import get_field_flag
from typing import Any, Union

mcp = FastMCP("Guide Parameter Validation Server")

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
async def upload_file_gui(
    title: str = "Select Neutron Simulation Guide Input File",
    file_filter: str = "neutron_guide_files"
) -> dict:
    """
    Upload files for neutron simulation guide input using GUI file picker.
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
                "missing_files": []
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
            "file_details": file_details
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
            "error": str(e)
        }

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
        file_picker = GuideFileListManager()
        file_picker.show()
        
        # This blocks until the window is closed
        app.exec()
        
        # Return the file paths that were selected
        return file_picker.file_paths
        
    except ImportError as e:
        print(f"GUI not available: {e}")
        return []
    
if __name__ == "__main__":
    mcp.run(transport="stdio")