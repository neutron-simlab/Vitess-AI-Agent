"""
supervisor_mcp_tools.py - MCP Tools for Supervisor Agent CLI Generation
FastMCP tools for converting collected module parameters to CLI commands
"""
from fastmcp import FastMCP
from typing import Any, Dict, List, Optional, Union
from vitess_ai.core.config import global_config
import logging
import json

mcp = FastMCP("Supervisor CLI Generation Server")
logger = logging.getLogger(__name__)

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
    "readin": "$V/read_in${SUFFIX}",
    "guide": "$V/guide_parallel${SUFFIX}",
    "writeout": "$V/writeout${SUFFIX}",
}

# Common parameters that appear in all modules
COMMON_PARAMS = " ".join([
    "--Z1",
    "--U1.0e-25",
    "--G1", 
    "--T0",
    "--B10000",
    f"--P$P",
])

def generate_cli_command(
   module_results: Optional[dict] = None,
   execution_order: Optional[List[str]] = None,
) -> Dict[str, Any]:
   """
   Generate CLI command from collected module results.
   
   Args:
       module_results: Dictionary with module names as keys and ModuleResult objects as values
       execution_order: List of module names in execution order
       
   Returns:
       Dictionary with CLI command and metadata
   """
   try:
       if module_results is None:
           module_results = {}
       if execution_order is None or not execution_order:
           # Fallback: use module_results keys as execution order
           execution_order = list(module_results.keys())
           logger.warning(f"No execution_order provided, using module order: {execution_order}")
           
       cli_command = []
       
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

           
           # Build module-specific ordering parameter
           module_order_param = f"--N{i} --L${{L}}0{i}"
               
           # Build module command parts
           cli_module = [
               MODULE_EXECUTABLES[module], 
               COMMON_PARAMS,
               module_order_param, 
               cli_params
           ]
           
           # Add pipe separator except for last module
           if module != execution_order[-1]:
               cli_module.append("|")
           
           cli_module_str = " ".join(cli_module)
           cli_command.append(cli_module_str)
       
       # Join all commands
       final_command = " ".join(cli_command)

       return {
           "success": True,
           "cli_command": final_command,
           "modules_included": [m for m in execution_order],
           "command_parts": len(cli_command),
           "message": f"Generated CLI command for {len(cli_command)} modules",
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
    execute: bool = False
) -> Dict[str, Any]:
    """
    Generate and optionally execute simulation using CLI parameters from agent state.
    
    Args:
        module_results: Dictionary with module names as keys and their ModuleResult objects as values
            (can be passed as dict or JSON string)
        execution_order: List of module names in execution order
            (can be passed as list or JSON string)
        execute: Whether to actually run the command
        
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
        
        cli_result = generate_cli_command(parsed_module_results, parsed_execution_order)
        if not cli_result.get('success', False):
            return cli_result  # Return error immediately
            
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
            import os
            from datetime import datetime
            
            # Create a temporary script file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
                script_content = f"""#!/bin/sh
# Auto-generated simulation script
# Generated at: {datetime.now()}

# Set variables (following your environment pattern)
unset V
unset P  
unset L
unset SUFFIX

[ -z "$V" ] && V={global_config.VITESS_MODULES_PATH}
[ -z "$P" ] && P={global_config.VITESS_PROJECT_PATH} 
[ -z "$L" ] && L={global_config.VITESS_LOG_PATH}
[ -z "${{SUFFIX}}" ] && SUFFIX="_`uname -s`_`uname -m`"

# Execute simulation pipeline
{cli_command}

# Post-processing (following your script pattern)
rm -f $P/result.txt
cat ${{L}}?? >> $P/result.txt  
echo $P
rm ${{L}}*
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
                # Move script to VITESS_PROJECT_PATH for reference
                try:
                    import shutil
                    script_name = f"simulation_script_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sh"
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

if __name__ == "__main__":
    mcp.run(transport="stdio")