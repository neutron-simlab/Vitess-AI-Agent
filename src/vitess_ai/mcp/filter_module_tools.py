# validation_server.py
from mcp.server.fastmcp import FastMCP
from typing import List
from vitess_ai.schema.filter_module import FilterBlock, FilterParameterSet

mcp = FastMCP("Parameter Validation Server")

@mcp.tool()  
async def validate_filter_module(parameters: List[FilterParameterSet]) -> dict:
    """Validate filter module parameters"""
    try:
        validated = FilterBlock(filters=parameters)
        return {
            "valid": True,
            "validated_params": validated,
            "message": "Filter module parameters are valid!"
        }
    except Exception as e:
        return {
            "valid": False,
            "errors": str(e),
            "message": f"Filter validation failed: {e}"
        }

if __name__ == "__main__":
    mcp.run(transport="stdio")