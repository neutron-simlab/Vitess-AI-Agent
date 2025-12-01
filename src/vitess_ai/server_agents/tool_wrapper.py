"""
Simple tool wrapper to inject thread_id from UnifiedState into tool calls.
"""

import logging
from typing import Dict, Any, List
from langchain_core.messages import AIMessage
from langgraph.prebuilt import ToolNode
from langchain.tools import BaseTool

logger = logging.getLogger(__name__)


def create_thread_id_tool_node(tools: List[BaseTool]) -> callable:
    """
    Create a ToolNode wrapper that injects thread_id from UnifiedState into tool calls.
    
    Args:
        tools: List of tools to execute
        
    Returns:
        A node function that injects thread_id and delegates to ToolNode
    """
    tool_node = ToolNode(tools)
    tool_dict = {tool.name: tool for tool in tools}
    
    def _tool_accepts_thread_id(tool: BaseTool) -> bool:
        """Check if tool accepts thread_id parameter"""
        try:
            if hasattr(tool, 'args_schema') and tool.args_schema:
                schema = tool.args_schema
                if hasattr(schema, 'model_fields'):
                    return 'thread_id' in schema.model_fields
                elif hasattr(schema, '__fields__'):
                    return 'thread_id' in schema.__fields__
        except Exception:
            pass
        return False
    
    async def tool_node_with_thread_id(state: Dict[str, Any]) -> Dict[str, Any]:
        """ToolNode that injects thread_id from state into tool calls"""
        thread_id = state.get('thread_id')
        messages = state.get('messages', [])
        
        if not thread_id:
            logger.debug("No thread_id in state, executing tools without injection")
            return await tool_node.ainvoke(state)
        
        # Find last AIMessage with tool_calls
        last_ai_message = None
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and hasattr(msg, 'tool_calls') and msg.tool_calls:
                last_ai_message = msg
                break
        
        if not last_ai_message:
            return await tool_node.ainvoke(state)
        
        # Inject thread_id into tool calls
        modified_tool_calls = []
        for tool_call in last_ai_message.tool_calls:
            tool_name = tool_call.get('name', '')
            tool_args = tool_call.get('args', {}).copy()
            
            # Check if tool accepts thread_id and inject it
            tool = tool_dict.get(tool_name)
            if tool and _tool_accepts_thread_id(tool):
                if 'thread_id' not in tool_args or tool_args.get('thread_id') is None:
                    tool_args['thread_id'] = thread_id
                    logger.debug(f"Injected thread_id={thread_id} into tool call: {tool_name}")
            
            modified_tool_calls.append({
                **tool_call,
                'args': tool_args
            })
        
        # Create modified message with injected thread_id
        modified_message = AIMessage(
            content=last_ai_message.content,
            tool_calls=modified_tool_calls,
            additional_kwargs=getattr(last_ai_message, 'additional_kwargs', {})
        )
        
        # Replace message in state
        modified_messages = messages.copy()
        for i in range(len(modified_messages) - 1, -1, -1):
            if modified_messages[i] == last_ai_message:
                modified_messages[i] = modified_message
                break
        
        # Execute with modified state
        modified_state = {**state, 'messages': modified_messages}
        return await tool_node.ainvoke(modified_state)
    
    return tool_node_with_thread_id
