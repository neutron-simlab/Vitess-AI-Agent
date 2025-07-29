# guide_module_tools.py
from mcp.server.fastmcp import FastMCP
import json
from vitess_ai.schema.guide_module import GuideParameters
from typing import Any, Union

mcp = FastMCP("Guide Parameter Validation Server")

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
        return {
            "validation_status": True,
            "validated_params": validated,
            "message": "Guide module parameters are valid!"
        }
       
    except Exception as e:
        return {
            "validation_status": False,
            "errors": str(e),
            "message": f"Guide validation failed: {e}", 
        }
    
if __name__ == "__main__":
    mcp.run(transport="stdio")