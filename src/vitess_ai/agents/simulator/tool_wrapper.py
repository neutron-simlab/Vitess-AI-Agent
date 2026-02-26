"""
Tool wrapper for supervisor simulation tools.

This wrapper injects thread_id into MCP tool calls when the tool schema accepts it.
It uses UnifiedState first and falls back to config.configurable.thread_id.
"""

from typing import Dict, Any, List, Callable, Awaitable, Optional
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import ToolNode
from langchain.tools import BaseTool

from vitess_ai.core.log import get_logger

logger = get_logger(__name__)


def create_thread_id_tool_node(
    tools: List[BaseTool],
) -> Callable[[Dict[str, Any], Optional[RunnableConfig]], Awaitable[Dict[str, Any]]]:
    """
    Create a ToolNode wrapper that injects thread_id from UnifiedState into tool calls.
    
    Args:
        tools: List of tools to execute
        
    Returns:
        A node function that injects thread_id and delegates to ToolNode
    """
    tool_node = ToolNode(tools)
    tool_dict = {tool.name: tool for tool in tools if getattr(tool, "name", None)}

    def _get_configurable(config: Optional[RunnableConfig]) -> dict:
        """Extract config.configurable safely from dict-like or object-like config."""
        if not config:
            return {}
        configurable = (
            config.get("configurable", None)
            if hasattr(config, "get")
            else getattr(config, "configurable", None)
        )
        return configurable if isinstance(configurable, dict) else {}

    def _resolve_thread_id(
        state: Dict[str, Any], config: Optional[RunnableConfig]
    ) -> Optional[str]:
        """Resolve thread_id from state first, then config.configurable."""
        thread_id = state.get("thread_id")
        if thread_id:
            return str(thread_id)
        thread_id = _get_configurable(config).get("thread_id")
        return str(thread_id) if thread_id else None
    
    def _tool_accepts_thread_id(tool: BaseTool) -> bool:
        """Check if tool accepts thread_id parameter"""
        try:
            if hasattr(tool, "args_schema") and tool.args_schema:
                schema = tool.args_schema
                if hasattr(schema, "model_fields"):  # pydantic v2
                    return "thread_id" in schema.model_fields
                if hasattr(schema, "__fields__"):  # pydantic v1
                    return "thread_id" in schema.__fields__
        except Exception:
            pass
        return False
    
    async def tool_node_with_thread_id(
        state: Dict[str, Any], config: Optional[RunnableConfig] = None
    ) -> Dict[str, Any]:
        """ToolNode that injects thread_id into tool calls when needed."""
        thread_id = _resolve_thread_id(state, config)
        messages = state.get("messages", [])
        
        if not thread_id:
            logger.debug("No thread_id in state, executing tools without injection")
            return await tool_node.ainvoke(state, config=config)
        
        # Find last AIMessage with tool_calls
        last_ai_message = None
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                last_ai_message = msg
                break
        
        if not last_ai_message:
            return await tool_node.ainvoke(state, config=config)
        
        # Inject thread_id into tool calls
        modified_tool_calls = []
        injected_any = False
        for tool_call in last_ai_message.tool_calls:
            tool_name = tool_call.get("name", "")
            raw_args = tool_call.get("args", {})
            tool_args = raw_args.copy() if isinstance(raw_args, dict) else {}
            updated_args = raw_args
            
            # Check if tool accepts thread_id and inject it
            tool = tool_dict.get(tool_name)
            if tool and _tool_accepts_thread_id(tool):
                if isinstance(raw_args, dict) and (
                    "thread_id" not in tool_args or tool_args.get("thread_id") is None
                ):
                    tool_args["thread_id"] = thread_id
                    updated_args = tool_args
                    injected_any = True
                    logger.debug(f"Injected thread_id={thread_id} into tool call: {tool_name}")
            
            modified_tool_calls.append({
                **tool_call,
                "args": updated_args
            })

        # Fast path: no changes to tool calls
        if not injected_any:
            return await tool_node.ainvoke(state, config=config)
        
        # Preserve all AIMessage metadata when updating tool calls
        if hasattr(last_ai_message, "model_copy"):
            modified_message = last_ai_message.model_copy(
                update={"tool_calls": modified_tool_calls}
            )
        else:
            modified_message = AIMessage(
                content=last_ai_message.content,
                tool_calls=modified_tool_calls,
                additional_kwargs=getattr(last_ai_message, "additional_kwargs", {}),
            )
        
        # Replace message in state (find last occurrence)
        modified_messages = messages.copy()
        for i in range(len(modified_messages) - 1, -1, -1):
            if modified_messages[i] == last_ai_message:
                modified_messages[i] = modified_message
                break
        
        # Execute with modified state
        modified_state = {**state, "messages": modified_messages}
        return await tool_node.ainvoke(modified_state, config=config)
    
    return tool_node_with_thread_id
