"""
supervisor_mcp_tools.py - MCP Tools for Supervisor Agent CLI Generation
FastMCP tools for converting collected module parameters to CLI commands
"""
from fastmcp import FastMCP
from typing import Any, Dict, List, Optional
from vitess_ai.core.config import global_config
from vitess_ai.core.log import get_logger
from datetime import datetime
import json
import os
import re

mcp = FastMCP("Supervisor CLI Generation Server")
logger = get_logger(__name__)

def coerce_json_to_dict(value: Any) -> Optional[dict]:
    """Coerce value to dict, parsing JSON strings if needed."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return None

def coerce_json_to_list(value: Any) -> Optional[List[str]]:
    """Coerce value to list, parsing JSON strings if needed."""
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
    return None


# Module to executable mapping (configurable)
MODULE_EXECUTABLES = {
    "readin": "$V/read_in",
    "guide": "$V/guide_parallel",
    "writeout": "$V/writeout",
    "monitor1d": "$V/monitor1D",
    "monitor2d": "$V/monitor2D",
}

# Common parameters that appear in all modules (base, without --P)
COMMON_PARAMS_BASE = " ".join([
    "--Z1",
    "--U1.0e-25",
    "--G1", 
    "--T0",
    "--B10000",
])

def generate_cli_command(
   module_results: Optional[dict] = None,
   execution_order: Optional[List[str]] = None,
   thread_id: Optional[str] = None,
) -> Dict[str, Any]:
   """
   Generate CLI command from collected module results.
   
   Args:
       module_results: Dictionary with module names as keys and ModuleResult objects as values
       execution_order: List of module names in execution order
       thread_id: Optional thread ID to include in project path. If not provided, will try to get from environment.
       
   Returns:
       Dictionary with CLI command and metadata
   """
   try:
       # If no thread_id provided (should be auto-injected by tool wrapper), try to extract it from file paths
       # WARNING: This is a fallback and may extract an old thread_id from previous sessions
       # Only use this if thread_id is not available from parameter
       extracted_thread_id = None
       if not thread_id and module_results:
           # Look for UUID pattern in file paths (thread_id is typically a UUID)
           # Pattern: {VITESS_PROJECT_PATH}/{thread_id}/uploads/... or .../outputs/...
           uuid_pattern = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
           project_path_escaped = re.escape(global_config.VITESS_PROJECT_PATH)
           thread_id_pattern = rf'{project_path_escaped}/({uuid_pattern})/'
           
           for module_name, module_result in module_results.items():
               cli_params = module_result.get('cli_parameters', '')
               if cli_params:
                   match = re.search(thread_id_pattern, cli_params)
                   if match:
                       extracted_thread_id = match.group(1)
                       logger.warning(
                           f"⚠️ Extracted thread_id from file paths (fallback): {extracted_thread_id}. "
                           f"This may be an old thread_id from a previous session."
                       )
                       break
       
       # Use extracted thread_id only if we still don't have one from parameter
       if not thread_id and extracted_thread_id:
           thread_id = extracted_thread_id
           logger.warning(f"Using extracted thread_id from file paths: {thread_id}")
       
       # Build project path with thread_id if available
       if thread_id:
           project_path = f"{global_config.VITESS_PROJECT_PATH}/{thread_id}"
       else:
           project_path = global_config.VITESS_PROJECT_PATH
       
       # Build COMMON_PARAMS with dynamic project path
       common_params = f"{COMMON_PARAMS_BASE} --P{project_path}"
       
       if module_results is None:
           module_results = {}
       if execution_order is None or not execution_order:
           # Fallback: use module_results keys as execution order
           execution_order = list(module_results.keys())
           logger.warning(f"No execution_order provided, using module order: {execution_order}")
           
       cli_command_lines = []
       
       for i, module in enumerate(execution_order, 1):  # Start from 1 for ordering
           # Get module result (could be dict or object)
           if module not in module_results:
               logger.error(f"Module '{module}' not found in module_results: {list(module_results.keys())}")
               continue
               
           module_result = module_results[module]
           # Extract cli_parameters (handle both dict and object formats)
           cli_params = module_result.get('cli_parameters', '')
           
           if not cli_params:
               logger.warning(f"No CLI parameters found for module '{module}'")
               continue

           # Check if module executable is defined
           if module not in MODULE_EXECUTABLES:
               logger.error(f"Module '{module}' not found in MODULE_EXECUTABLES. Available modules: {list(MODULE_EXECUTABLES.keys())}")
               continue
           
           # Build module-specific ordering parameter
           module_order_param = f"--N{i} --L${{L}}0{i}"
               
           # Build module command parts
           cli_module = [
               MODULE_EXECUTABLES[module], 
               common_params,
               module_order_param, 
               cli_params
           ]
           
           # Join module command parts with spaces
           cli_module_str = " ".join(cli_module)
           
           # Add pipe and backslash continuation except for last module
           if module != execution_order[-1]:
               cli_module_str += " | \\"
           
           cli_command_lines.append(cli_module_str)
       
       # Join all pipeline commands with newlines
       pipeline_command = "\n".join(cli_command_lines)
       
       # Add post-processing commands on separate lines
       # Use error suppression for cat/rm commands in case log files don't exist
       post_processing_lines = [
           f"rm -f {project_path}/result.txt",
           f"cat ${{L}}?? >> {project_path}/result.txt 2>/dev/null || true",
           f"echo {project_path}",
           f"rm -f ${{L}}*"
       ]
       post_processing = "\n".join(post_processing_lines)
       
       # Combine pipeline and post-processing with blank line separator
       final_command = pipeline_command + "\n\n" + post_processing

       return {
           "success": True,
           "cli_command": final_command,
           "modules_included": [m for m in execution_order],
           "command_parts": len(cli_command_lines),
           "message": f"Generated CLI command for {len(cli_command_lines)} modules",
           "thread_id": thread_id,
           "project_path": project_path,
           "debug_info": {
               "execution_order": execution_order,
               "module_results_keys": list(module_results.keys()),
               "modules_with_cli": [m for m in execution_order if m in module_results and module_results[m].get('cli_parameters')]
           }
       }
   
   except Exception as e:
       return {
           "success": False,
           "error": str(e),
           "message": f"Failed to generate Vitess CLI command: {e}"
       }
   
@mcp.tool()
async def run_simulation(
    module_results: Optional[Any] = None,
    execution_order: Optional[Any] = None,
    execute: bool = False,
    thread_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate and optionally execute simulation using CLI parameters from agent state.
    
    Args:
        module_results: Dictionary with module names as keys and their ModuleResult objects as values
            (can be passed as dict or JSON string)
        execution_order: List of module names in execution order
            (can be passed as list or JSON string)
        execute: Whether to actually run the command
        thread_id: Optional thread ID to use for project path. If not provided, will try to get from environment.
        
    Returns:
        Dictionary with command, execution results, and status
    """
    def safe_decode(data):
        """Safely decode bytes to string with fallback options"""
        if isinstance(data, str):
            return data
        if isinstance(data, bytes):
            # Try multiple encodings
            for encoding in ['utf-8', 'latin-1', 'ascii']:
                try:
                    return data.decode(encoding)
                except UnicodeDecodeError:
                    continue
            # If all fail, decode with replacement characters
            return data.decode('utf-8', errors='replace')
        return str(data)
    
    try:
        # Parse inputs if they're JSON strings (common when LLM passes complex data)
        # Use coercion functions that handle both dict/list and JSON strings
        parsed_module_results = coerce_json_to_dict(module_results) or {}
        parsed_execution_order = coerce_json_to_list(execution_order) or []
        
        logger.info(f"Parsed module_results: {len(parsed_module_results)} modules")
        logger.info(f"Parsed execution_order: {parsed_execution_order}")
        logger.info(f"Initial thread_id: {thread_id}")
        
        cli_result = generate_cli_command(parsed_module_results, parsed_execution_order, thread_id=thread_id)
        if not cli_result.get('success', False):
            return cli_result  # Return error immediately
        
        # Use thread_id from cli_result (may have been extracted from file paths)
        thread_id = cli_result.get('thread_id') or thread_id
        logger.info(f"Final thread_id: {thread_id}")
            
        cli_command = cli_result['cli_command']  # Extract the actual command
        result = {
            "executed": False,
            "cli_command": cli_result['cli_command'],
            "success": True,
            "message": "CLI command generated (not executed)"
        }


        # Execute if requested
        if execute:
            import subprocess
            import tempfile
            
            # Build project path with thread_id for $P variable in script
            if thread_id:
                project_path_for_script = f"{global_config.VITESS_PROJECT_PATH}/{thread_id}"
            else:
                project_path_for_script = global_config.VITESS_PROJECT_PATH
            
            # Create a temporary script file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
                script_content = f"""#!/bin/sh
# Auto-generated simulation script
# Generated at: {datetime.now()}

# Set variables (following your environment pattern)
unset V
unset P  
unset L

[ -z "$V" ] && V={global_config.VITESS_MODULES_PATH}
[ -z "$P" ] && P={project_path_for_script}
[ -z "$L" ] && L={global_config.VITESS_LOG_PATH}

# Execute simulation pipeline (includes post-processing)
{cli_command}
"""
                f.write(script_content)
                script_path = f.name
            
            try:
                # Make script executable
                os.chmod(script_path, 0o755)
                
                # Execute the script with binary output handling
                process = subprocess.run(
                    ['/bin/bash', script_path],
                    capture_output=True,
                    text=False,  # ✅ Get raw bytes to avoid UTF-8 errors
                    timeout=3600  # 1 hour timeout
                )
                
                result.update({
                    "executed": True,
                    "exit_code": process.returncode,
                    "stderr": safe_decode(process.stderr),
                    "success": process.returncode == 0,
                    "script_path": script_path
                })
                
                if process.returncode == 0:
                    result["message"] = "Simulation executed successfully!"
                    result["simulation_finish"] = True
                else:
                    result["message"] = f"Simulation failed with exit code {process.returncode}"
                    result["simulation_finish"] = False
                    
            except subprocess.TimeoutExpired:
                result.update({
                    "executed": True,
                    "success": False,
                    "error": "Simulation timed out after 1 hour",
                    "message": "Simulation execution timed out"
                })
            except Exception as e:
                result.update({
                    "executed": True, 
                    "success": False,
                    "error": str(e),
                    "message": f"Simulation execution failed: {e}"
                })
            finally:
                # Move script to $P (thread-specific project path) for reference
                try:
                    import shutil
                    # Use thread_id from cli_result (may have been extracted from file paths)
                    # thread_id is already available from earlier in the function
                    script_name = f"simulation_script_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sh"
                    
                    if thread_id:
                        # Save to $P (thread-specific project path)
                        project_dir = os.path.join(global_config.VITESS_PROJECT_PATH, thread_id)
                        os.makedirs(project_dir, exist_ok=True)
                        final_script_path = os.path.join(project_dir, script_name)
                    else:
                        # Fallback to root project path
                        final_script_path = os.path.join(global_config.VITESS_PROJECT_PATH, script_name)
                    
                    shutil.move(script_path, final_script_path)
                    result["saved_script_path"] = final_script_path
                except Exception as e:
                    # If moving fails, try to clean up the temp file
                    try:
                        os.unlink(script_path)
                    except:
                        pass
        
        return result
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": f"Failed to prepare simulation: {e}"
        }

@mcp.tool()
async def inspect_thread_folders(thread_id: str | None = None) -> dict[str, Any]:
    """
    Inspect the complete folder structure for a thread including uploads and outputs.
    
    Args:
        thread_id: Optional thread ID to inspect. If not provided, will try to get from environment variables.
        
    Returns:
        Dictionary with complete folder structure
    """
    from pathlib import Path
    
    # Get thread_id
    if not thread_id:
        thread_id = os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")
    
    if not thread_id:
        return {
            "success": False,
            "message": "❌ No thread_id available. Cannot inspect thread folders.",
            "thread_id": None,
            "folder_structure": {}
        }
    
    try:
        from vitess_ai.core.config import global_config
        from vitess_ai.server.file_storage import get_file_storage_service
        
        storage_service = get_file_storage_service()
        root_path = Path(global_config.VITESS_PROJECT_PATH)
        thread_path = root_path / thread_id
        
        folder_structure = {
            "root_path": str(root_path),
            "thread_id": thread_id,
            "thread_path": str(thread_path),
            "exists": thread_path.exists(),
            "uploads": {},
            "outputs": {}
        }
        
        # Inspect uploads directory
        uploads_path = thread_path / "uploads"
        if uploads_path.exists():
            folder_structure["uploads"]["path"] = str(uploads_path)
            folder_structure["uploads"]["exists"] = True
            folder_structure["uploads"]["modules"] = {}
            
            # Check each module type
            for module_type in ["readin", "guide", "instrument", "writeout"]:
                module_path = uploads_path / module_type
                if module_path.exists():
                    files = []
                    for file_path in module_path.iterdir():
                        if file_path.is_file():
                            try:
                                file_stat = file_path.stat()
                                files.append({
                                    "filename": file_path.name,
                                    "file_size": file_stat.st_size,
                                    "modified_at": datetime.fromtimestamp(file_stat.st_mtime).isoformat()
                                })
                            except OSError:
                                pass
                    folder_structure["uploads"]["modules"][module_type] = {
                        "path": str(module_path),
                        "file_count": len(files),
                        "files": files
                    }
        
        # Inspect outputs directory
        outputs_path = thread_path / "outputs"
        if outputs_path.exists():
            folder_structure["outputs"]["path"] = str(outputs_path)
            folder_structure["outputs"]["exists"] = True
            folder_structure["outputs"]["files"] = []
            
            for file_path in outputs_path.iterdir():
                if file_path.is_file():
                    try:
                        file_stat = file_path.stat()
                        folder_structure["outputs"]["files"].append({
                            "filename": file_path.name,
                            "file_size": file_stat.st_size,
                            "modified_at": datetime.fromtimestamp(file_stat.st_mtime).isoformat()
                        })
                    except OSError:
                        pass
            
            folder_structure["outputs"]["file_count"] = len(folder_structure["outputs"]["files"])
        
        return {
            "success": True,
            "message": f"📁 Complete folder structure for thread {thread_id[:8]}...",
            "thread_id": thread_id,
            "folder_structure": folder_structure
        }
    except Exception as e:
        logger.error(f"Error inspecting thread folders: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"❌ Error inspecting thread folders: {str(e)}",
            "thread_id": thread_id,
            "folder_structure": {},
            "error": str(e)
        }


@mcp.tool()
async def generate_monitor1d_plot(thread_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Generate an interactive Plotly plot from monitor1d.dat file.
    
    Args:
        thread_id: Optional thread ID to locate the monitor1d.dat file.
                   If not provided, will try to get from environment.
    
    Returns:
        Dictionary with plot JSON and metadata, or error information
    """
    try:
        # Get thread_id from parameter or environment
        if not thread_id:
            thread_id = os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")
        
        if not thread_id:
            return {
                "success": False,
                "error": "No thread_id provided and not available in environment",
                "plot_json": None,
            }
        
        # Construct file path
        from pathlib import Path
        monitor_file = Path(global_config.VITESS_PROJECT_PATH) / thread_id / "outputs" / "monitor1D.dat"
        
        if not monitor_file.exists():
            return {
                "success": False,
                "error": f"Monitor1D file not found: {monitor_file}",
                "plot_json": None,
                "file_path": str(monitor_file),
            }
        
        # Import and use the plotly reading function
        from vitess_ai.plots.vitess_plot import read_mfile_plotly
        
        result = read_mfile_plotly(str(monitor_file))
        
        if result.get("success"):
            return {
                "success": True,
                "plot_type": "monitor1d",
                "plot_json": result["plot_json"],
                "title": result.get("title", "Monitor1D Results"),
                "xaxis": result.get("xaxis", "x"),
                "yaxis": result.get("yaxis", "Intensity [n/s]"),
                "file_path": str(monitor_file),
                "message": f"✅ Successfully generated Monitor1D plot from {monitor_file.name}",
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Unknown error generating plot"),
                "plot_json": None,
                "file_path": str(monitor_file),
            }
            
    except Exception as e:
        logger.error(f"Error generating Monitor1D plot: {e}", exc_info=True)
        return {
            "success": False,
            "error": f"Error generating Monitor1D plot: {str(e)}",
            "plot_json": None,
        }


@mcp.tool()
async def generate_monitor2d_plot(thread_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Generate an interactive Plotly plot from monitor2d.dat file.
    
    Args:
        thread_id: Optional thread ID to locate the monitor2d.dat file.
                   If not provided, will try to get from environment.
    
    Returns:
        Dictionary with plot JSON and metadata, or error information
    """
    try:
        # Get thread_id from parameter or environment
        if not thread_id:
            thread_id = os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")
        
        if not thread_id:
            return {
                "success": False,
                "error": "No thread_id provided and not available in environment",
                "plot_json": None,
            }
        
        # Construct file path
        from pathlib import Path
        monitor_file = Path(global_config.VITESS_PROJECT_PATH) / thread_id / "outputs" / "monitor2D.dat"
        
        if not monitor_file.exists():
            return {
                "success": False,
                "error": f"Monitor2D file not found: {monitor_file}",
                "plot_json": None,
                "file_path": str(monitor_file),
            }
        
        # Import and use the plotly reading function
        from vitess_ai.plots.vitess_plot import read_mfile_plotly
        
        result = read_mfile_plotly(str(monitor_file))
        
        if result.get("success"):
            return {
                "success": True,
                "plot_type": "monitor2d",
                "plot_json": result["plot_json"],
                "title": result.get("title", "Monitor2D Results"),
                "xaxis": result.get("xaxis", "x"),
                "yaxis": result.get("yaxis", "y"),
                "file_path": str(monitor_file),
                "message": f"✅ Successfully generated Monitor2D plot from {monitor_file.name}",
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Unknown error generating plot"),
                "plot_json": None,
                "file_path": str(monitor_file),
            }
            
    except Exception as e:
        logger.error(f"Error generating Monitor2D plot: {e}", exc_info=True)
        return {
            "success": False,
            "error": f"Error generating Monitor2D plot: {str(e)}",
            "plot_json": None,
        }


if __name__ == "__main__":
    # Support both stdio (development) and http (production) transports
    transport_mode = os.getenv("MCP_TRANSPORT_MODE", "http").lower()
    
    if transport_mode == "http":
        port = int(os.getenv("MCP_SUPERVISOR_PORT", "9005"))
        host = os.getenv("MCP_HOST", "0.0.0.0")
        mcp.run(transport="http", host=host, port=port)
    else:
        mcp.run(transport="stdio")