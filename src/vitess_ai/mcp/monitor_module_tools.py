# monitor_module_tools.py
from fastmcp import FastMCP
import json
from vitess_ai.schema.monitor1d_module import Monitor1DParameters
from vitess_ai.schema.monitor2d_module import Monitor2DParameters
from vitess_ai.schema.base import get_field_flag
from typing import Any, Union

mcp = FastMCP("Monitor Parameter Validation Server")


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
    mcp.run(transport="stdio")

