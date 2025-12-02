"""Supervisor agent prompts for server mode."""


SUPERVISOR_WELCOME_MESSAGE = """
**Neutron Simulation Configuration System**

Welcome! I'm your configurable Simulation Supervisor. I'll guide you through 
setting up your neutron simulation with the registered modules.
"""


def get_supervisor_welcome_message(modules_info: list, simulation_tools_available: bool = False) -> str:
    """Generate the welcome message for the supervisor.
    
    Args:
        modules_info: List of formatted module information strings
        simulation_tools_available: Whether simulation execution tools are available
        
    Returns:
        Formatted welcome message string
    """
    welcome_text = SUPERVISOR_WELCOME_MESSAGE
    
    if modules_info:
        welcome_text += "\n\n**Modules to Configure:**\n"
        welcome_text += "\n".join(modules_info)
        welcome_text += "\n\nI'll guide you through configuring each module step by step."
    else:
        welcome_text += "\n\nNo modules are currently registered. Please register modules before starting configuration."
    
    if simulation_tools_available:
        welcome_text += "\n\n**Simulation Execution**: Once all modules are configured, the simulation will be executed automatically."
    
    return welcome_text


def get_simulation_execution_prompt(module_results: dict, execution_order: list) -> str:
    """Generate the system prompt for simulation execution.
    
    Args:
        module_results: Dictionary with module results
        execution_order: List of module names in execution order
        
    Returns:
        Formatted prompt string for simulation execution
    """
    return f"""
You are a neutron simulation executor. All modules have been configured and you need to run the simulation.

IMPORTANT: You must call the run_simulation tool with these EXACT parameters:

Tool Call Required:
```
run_simulation(
    module_results={module_results},
    execution_order={execution_order},
    execute=true
)
```

Module Summary:
- Configured modules: {list(module_results.keys())}
- Execution order: {execution_order}
- Total modules: {len(module_results)}

Each module has generated CLI parameters that will be combined into a simulation pipeline.

CRITICAL: You must call the run_simulation tool with execute=true to actually run the simulation.
The tool expects:
- module_results: Dictionary with module results (already provided)
- execution_order: List of module names in execution order (already provided)  
- execute: Boolean set to true to actually run the simulation

Execute the simulation immediately using the run_simulation tool with the exact parameters shown above.
Do not modify or interpret the module_results data - pass it exactly as provided.
"""


def get_post_simulation_response_prompt(tool_result: dict) -> str:
    """Generate the system prompt for post-simulation response.
    
    Args:
        tool_result: The result from the simulation tool execution
        
    Returns:
        Formatted prompt string for generating AI response after simulation execution
    """
    success = tool_result.get('simulation_finish', False)
    status = tool_result.get('status', 'unknown')
    executed = tool_result.get('executed', False)
    
    if success and executed:
        prompt = """
You are a helpful assistant that provides feedback after a simulation execution.

The simulation has been executed successfully. The tool result shows that the simulation completed without errors.

Generate a friendly, informative response to the user about the successful simulation execution. Include:
- Confirmation that the simulation executed successfully
- Brief summary of what was executed
- Next steps or information about the results (if available)

Be concise but warm and helpful. Keep the response under 200 words.
"""
    elif executed:
        prompt = f"""
You are a helpful assistant that provides feedback after a simulation execution.

The simulation execution finished, but there were some issues. The status is: {status}

Generate a helpful response to the user about the simulation execution. Include:
- Acknowledgment that the simulation ran but encountered issues
- Brief summary of what happened
- Guidance on what the user might want to check or do next

Be supportive and constructive. Keep the response under 200 words.
"""
    else:
        prompt = """
You are a helpful assistant that provides feedback after a simulation execution.

The simulation tool was called but execution status is unclear.

Generate a helpful response to the user. Acknowledge that the simulation was attempted and provide guidance on next steps.

Be concise and helpful. Keep the response under 150 words.
"""
    
    return prompt

