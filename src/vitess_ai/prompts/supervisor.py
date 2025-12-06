"""Supervisor agent prompts for server mode."""
from typing import List, Dict, Any, Optional


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


def get_supervisor_routing_prompt(
    execution_order: List[str],
    completed_modules: List[str],
    module_results: Dict[str, Any],
    current_active_module: Optional[str],
    recent_messages: List[Any],
    modules_info: List[Dict[str, Any]],
    simulation_tools_available: bool = False
) -> str:
    """
    Generate the system prompt for supervisor routing decisions.
    
    Args:
        execution_order: List of module names in execution order
        completed_modules: List of completed module names
        module_results: Dictionary of module results with their status
        current_active_module: Currently active module name (if any)
        recent_messages: Last 5-10 conversation messages for context
        modules_info: List of module metadata dictionaries with name, display_name, description, order
        simulation_tools_available: Whether simulation execution tools are available
        
    Returns:
        Formatted prompt string for LLM routing decisions
    """
    # Build module status summary
    pending_modules = [m for m in execution_order if m not in completed_modules]
    
    # Format module information
    modules_text = []
    for module_info in modules_info:
        name = module_info.get('name', '')
        display_name = module_info.get('display_name', name)
        description = module_info.get('description', '')
        optional = module_info.get('optional', False)
        order = module_info.get('order', 999)
        optional_text = " (optional)" if optional else ""
        status = "✓ Completed" if name in completed_modules else "⏳ Pending"
        modules_text.append(f"  {order}. {display_name}{optional_text} ({name}) - {description} [{status}]")
    
    # Format recent conversation (last few messages)
    conversation_text = ""
    if recent_messages:
        conversation_text = "\n**Recent Conversation:**\n"
        for msg in recent_messages[-8:]:  # Last 8 messages
            if hasattr(msg, 'content'):
                content = str(msg.content)[:200]  # Truncate long messages
                msg_type = type(msg).__name__
                conversation_text += f"  [{msg_type}]: {content}\n"
    
    # Build module results summary
    results_summary = []
    for module_name in execution_order:
        if module_name in module_results:
            result = module_results[module_name]
            if hasattr(result, 'stage'):
                stage = result.stage.stage if hasattr(result.stage, 'stage') else str(result.stage)
            elif isinstance(result, dict):
                stage = result.get('stage', {}).get('stage', 'unknown') if isinstance(result.get('stage'), dict) else str(result.get('stage', 'unknown'))
            else:
                stage = 'unknown'
            results_summary.append(f"  - {module_name}: {stage}")
        else:
            results_summary.append(f"  - {module_name}: not started")
    
    prompt = f"""You are an intelligent routing supervisor for a neutron simulation configuration system.

Your task is to analyze the current state and conversation context to determine where to route the user next.

**Current State:**
- Execution Order: {execution_order}
- Completed Modules: {completed_modules}
- Pending Modules: {pending_modules}
- Current Active Module: {current_active_module or "None"}

**Module Status:**
{chr(10).join(results_summary)}

**Available Modules:**
{chr(10).join(modules_text)}
{conversation_text}
**Routing Rules:**

1. **First Interaction**: If this is the first user message (no previous conversation), provide a natural, friendly greeting in the `greeting_message` field. Do NOT use formal welcome messages - be conversational and helpful. 
   
   **CRITICAL**: Your greeting MUST include information about the registered modules. Mention the modules that are available for configuration (listed in the "Available Modules" section above). For example, you might say something like "I'll help you configure your neutron simulation. We'll work through [module names] step by step." This helps users understand what will be configured.

2. **Normal Flow**: If the user is continuing normally and there are pending modules, route to the next pending module in execution order.

3. **Change Previous Module**: If the user explicitly wants to change or modify a previous (completed) module, route back to that module. The module will handle re-validation.

4. **All Modules Complete**: If all modules are completed and the user hasn't requested changes, route to simulation (set action="route_to_simulation" and target_module="simulation" or None).

5. **Resume Active Module**: If there's a current_active_module and the user just provided input, route back to that module.

6. **CRITICAL - Unvalidated Active Module**: If current_active_module exists and is NOT in completed_modules, you MUST route back to current_active_module. Do NOT route to the next module or simulation until the active module is validated (stage="completed"). This ensures parameters are validated before proceeding. This rule takes precedence over all other routing rules except explicit user requests to change modules.

7. **User Intent Detection**: Carefully analyze the conversation messages to understand user intent:
   - "I want to change X" → route to module X
   - "Let me modify the Y parameters" → route to module Y  
   - "Go back to Z" → route to module Z
   - General questions or clarifications → continue with current flow

**Important:**
- Use `action="route_to_module"` when routing to any module
- Use `action="route_to_simulation"` when all modules are complete
- The `target_module` must be one of: {execution_order + ['simulation']}
- Provide clear `reasoning` explaining your routing decision
- Only set `greeting_message` for first-time interactions

Analyze the state and conversation, then return your routing decision."""
    
    return prompt

