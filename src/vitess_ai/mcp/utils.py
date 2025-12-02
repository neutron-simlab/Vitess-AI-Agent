"""
MCP utility functions.

This module provides utility functions for working with MCP tools.
"""


def is_mcp_tool(name: str) -> bool:
    """Check if a tool name indicates it's an MCP tool.
    
    MCP tools typically have names like:
    - validate_*_parameters (validate_guide_parameters, validate_readin_parameters, etc.)
    - run_simulation
    - launch_*_gui (launch_picker_gui, launch_instrument_gui)
    - Other module-specific validation tools
    
    Args:
        name: Tool name to check
        
    Returns:
        True if the tool is an MCP tool, False otherwise
    """
    mcp_patterns = [
        "validate_",
        "run_simulation",
        "launch_",
        "generate_cli",
    ]
    return any(name.startswith(pattern) for pattern in mcp_patterns)

