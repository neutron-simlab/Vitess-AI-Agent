"""
supervisor_mcp_tools.py - MCP Tools for Supervisor Agent CLI Generation
FastMCP tools for converting collected module parameters to CLI commands
"""
from fastmcp import FastMCP
from typing import Any, Dict, List, Optional
from vitess_ai.core.config import global_config
import logging

mcp = FastMCP("Supervisor CLI Generation Server")
logger = logging.getLogger(__name__)

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
       if execution_order is None:
           execution_order = []
           
       cli_command = []
       
       for i, module in enumerate(execution_order, 1):  # Start from 1 for ordering
           # Get module result (could be dict or object)
           module_result = module_results[module]
           # Extract cli_parameters (handle both dict and object formats)
           cli_params = module_result.get('cli_parameters', '')

           
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
           "message": f"Generated CLI command for {len(cli_command)} modules"
       }
   
   except Exception as e:
       return {
           "success": False,
           "error": str(e),
           "message": f"Failed to generate Vitess CLI command: {e}"
       }
   
@mcp.tool()
async def run_simulation(
    module_results: Optional[dict] = None,
    execution_order: Optional[List[str]] = None,
    execute: bool = False
) -> Dict[str, Any]:
    """
    Generate and optionally execute simulation using CLI parameters from agent state.
    
    Args:
        cli_parameters: Dictionary with module names as keys and their CLI params as values
        execution_order: List of module names in execution order
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
        cli_result = generate_cli_command(module_results or {}, execution_order or [])
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
                    # "stdout": safe_decode(process.stdout),
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
                # Clean up script file
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