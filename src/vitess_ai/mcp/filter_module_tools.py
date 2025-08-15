# filter_module_tools.py
from fastmcp import FastMCP
import json
from vitess_ai.schema.filter_module import FilterBlock, FilterParameterSet
from typing import Any, Union, List

mcp = FastMCP("Filter Parameter Validation Server")

@mcp.tool()  
async def validate_filter_parameters(parameters: Union[str, dict[str, Any], List[FilterParameterSet]]) -> dict[str, Any]:
    """
    Validate filter parameters from either JSON string, dictionary, or list of FilterParameterSet.
    
    Args:
        parameters: Either a JSON string, dictionary containing filter parameters, or list of FilterParameterSet
        
    Returns:
        Dictionary with validation results
    """
    try:
        # Handle different input types
        if isinstance(parameters, str):
            try:
                parsed_parameters = json.loads(parameters)
            except json.JSONDecodeError:
                return {
                    "validation_status": False,
                    "errors": "Invalid JSON string format",
                    "message": "Filter validation failed: Invalid JSON string",
                }
        elif isinstance(parameters, dict):
            parsed_parameters = parameters
        elif isinstance(parameters, list):
            # Already a list, assume it's FilterParameterSet objects or dicts
            parsed_parameters = {"filters": parameters}
        else:
            return {
                "validation_status": False,
                "errors": f"Expected JSON string, dict, or list, got {type(parameters)}",
                "message": f"Filter validation failed: Invalid parameter type {type(parameters)}",
            }
        
        # Handle different dictionary structures
        if isinstance(parsed_parameters, dict):
            # Check if it's already in the expected format with 'filters' key
            if "filters" in parsed_parameters:
                filter_list = parsed_parameters["filters"]
            elif isinstance(parsed_parameters, dict) and all(isinstance(v, (dict, FilterParameterSet)) for v in parsed_parameters.values()):
                # If it's a dict of filter objects, convert to list
                filter_list = list(parsed_parameters.values())
            else:
                # Assume the entire dict is a single filter parameter set
                filter_list = [parsed_parameters]
        else:
            return {
                "validation_status": False,
                "errors": "Parsed parameters must be a dictionary or list",
                "message": "Filter validation failed: Invalid parsed parameter structure",
            }
        
        # Now validate using FilterBlock
        validated = FilterBlock(filters=filter_list)
        return {
            "validation_status": True,
            "validated_params": validated,
            "message": "Filter module parameters are valid!"
        }
       
    except Exception as e:
        return {
            "validation_status": False,
            "errors": str(e),
            "message": f"Filter validation failed: {e}", 
        }

if __name__ == "__main__":
    mcp.run(transport="stdio")