"""
MCP utility functions.

Only the supervisor uses MCP (Vitess CLI tools). Module agents use LangChain tools.
"""


def is_mcp_tool(name: str) -> bool:
    """Check if a tool name is from the supervisor MCP server (Vitess CLI tools).
    
    Supervisor MCP tools: generate_cli_command, prepare_simulation, run_simulation,
    inspect_thread_folders, generate_monitor1d_plot. All other tools are LangChain tools.
    
    Args:
        name: Tool name to check
        
    Returns:
        True if the tool is a supervisor MCP tool, False otherwise
    """
    mcp_patterns = [
        "generate_cli_command",
        "prepare_simulation",
        "run_simulation",
        "inspect_thread_folders",
        "generate_monitor1d_plot",
        "launch_",  # if any launch_* in supervisor
    ]
    return any(name == pattern or (pattern.endswith("_") and name.startswith(pattern)) for pattern in mcp_patterns)

