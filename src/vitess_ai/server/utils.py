import os
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages import (
    ChatMessage as LangchainChatMessage,
)

from vitess_ai.schema.server import ChatMessage


def set_thread_id_env(thread_id: str) -> None:
    """Set thread_id as environment variable for MCP tools.
    
    Args:
        thread_id: Thread ID to set in environment variables
    """
    os.environ["THREAD_ID"] = thread_id


def set_request_thread_id_env(thread_id: str | None) -> None:
    """Set or clear thread_id env for this request so the process never reuses a previous request's thread_id.
    
    Call this at the start of every invoke/stream request. If thread_id is None or empty,
    clears the env so tools and MCP subprocesses do not see a stale value.
    
    Args:
        thread_id: Thread ID from the current request, or None to clear.
    """
    if thread_id:
        os.environ["THREAD_ID"] = thread_id
    else:
        os.environ.pop("THREAD_ID", None)


def convert_message_content_to_string(content: str | list[str | dict]) -> str:
    if isinstance(content, str):
        return content
    text: list[str] = []
    for content_item in content:
        if isinstance(content_item, str):
            text.append(content_item)
            continue
        if content_item["type"] == "text":
            text.append(content_item["text"])
    return "".join(text)


# Import MCP tool detection from mcp module
from vitess_ai.mcp.utils import is_mcp_tool as _is_mcp_tool


def langchain_to_chat_message(message: BaseMessage, module_name: str = None) -> ChatMessage:
    """Create a ChatMessage from a LangChain message.
    
    Adds metadata to distinguish MCP tool calls from regular tool calls
    and includes module information for color coding.
    
    Args:
        message: LangChain message to convert
        module_name: Optional module name for color coding
    """
    match message:
        case HumanMessage():
            human_message = ChatMessage(
                type="human",
                content=convert_message_content_to_string(message.content),
            )
            return human_message
        case AIMessage():
            ai_message = ChatMessage(
                type="ai",
                content=convert_message_content_to_string(message.content),
            )
            # Initialize custom_data if not already set
            if not ai_message.custom_data:
                ai_message.custom_data = {}
            
            # Check for module info in message metadata first (has priority)
            # This ensures messages with explicit module_name in additional_kwargs
            # (like supervisor welcome message) are correctly labeled
            message_module_name = None
            if hasattr(message, "additional_kwargs") and message.additional_kwargs:
                metadata = message.additional_kwargs
                if "module_name" in metadata:
                    message_module_name = metadata["module_name"]
                # Extract plot_data if present
                if "plot_data" in metadata:
                    ai_message.custom_data["plot_data"] = metadata["plot_data"]
            
            # Use module_name from message metadata if available, otherwise use provided parameter
            final_module_name = message_module_name or module_name
            if final_module_name:
                ai_message.custom_data["module_name"] = final_module_name
            
            if message.tool_calls:
                ai_message.tool_calls = message.tool_calls
                # Check if any tool calls are MCP tools
                has_mcp_tools = any(
                    _is_mcp_tool(tool_call.get("name", ""))
                    for tool_call in message.tool_calls
                )
                if has_mcp_tools:
                    ai_message.custom_data.update({
                        "has_mcp_tools": True,
                        "source": "mcp"
                    })
            if message.response_metadata:
                ai_message.response_metadata = message.response_metadata
            return ai_message
        case ToolMessage():
            tool_message = ChatMessage(
                type="tool",
                content=convert_message_content_to_string(message.content),
                tool_call_id=message.tool_call_id,
            )
            # Initialize custom_data if not already set
            if not tool_message.custom_data:
                tool_message.custom_data = {}
            
            # Add module information if provided
            if module_name:
                tool_message.custom_data["module_name"] = module_name
            
            # Check for module info in message metadata
            if hasattr(message, "additional_kwargs") and message.additional_kwargs:
                metadata = message.additional_kwargs
                if "module_name" in metadata and not module_name:
                    tool_message.custom_data["module_name"] = metadata["module_name"]
            
            # Try to detect if this is an MCP tool by checking metadata or content
            # MCP tools typically return JSON with validation_status or similar fields
            content_str = convert_message_content_to_string(message.content)
            try:
                import json
                parsed_content = json.loads(content_str)
                # Check for MCP-specific response patterns
                if isinstance(parsed_content, dict) and (
                    "validation_status" in parsed_content or
                    "cli_parameters" in parsed_content or
                    "validated_params" in parsed_content or
                    "simulation_finish" in parsed_content
                ):
                    tool_message.custom_data.update({
                        "source": "mcp",
                        "is_mcp_tool": True
                    })
            except (json.JSONDecodeError, TypeError):
                # Not JSON, but we can still check metadata if available
                if hasattr(message, "additional_kwargs"):
                    metadata = message.additional_kwargs
                    if metadata.get("source") == "mcp":
                        tool_message.custom_data.update({
                            "source": "mcp",
                            "is_mcp_tool": True
                        })
            return tool_message
        case SystemMessage():
            system_message = ChatMessage(
                type="system",
                content=convert_message_content_to_string(message.content),
            )
            return system_message
        case LangchainChatMessage():
            if message.role == "custom":
                custom_message = ChatMessage(
                    type="custom",
                    content="",
                    custom_data=message.content[0],
                )
                return custom_message
            else:
                raise ValueError(f"Unsupported chat message role: {message.role}")
        case _:
            raise ValueError(f"Unsupported message type: {message.__class__.__name__}")


def remove_tool_calls(content: str | list[str | dict]) -> str | list[str | dict]:
    """Remove tool calls from content."""
    if isinstance(content, str):
        return content
    # Currently only Anthropic models stream tool calls, using content item type tool_use.
    return [
        content_item
        for content_item in content
        if isinstance(content_item, str) or content_item["type"] != "tool_use"
    ]
