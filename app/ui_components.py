"""
UI components for rendering messages and badges in Streamlit.

This module provides functions for rendering chat messages, badges, and content
with consistent styling across the application.
"""
import json
import streamlit as st
from pathlib import Path

from vitess_ai.schema.server import ChatMessage

# Paths and assets
_assets_dir = Path(__file__).parent / "assets"
_logo_path = _assets_dir / "logo.png"

# Module color mapping for visual differentiation
MODULE_COLORS = {
    "supervisor": "blue",      # Streamlit's primary blue
    "readin": "green",         # Success green
    "guide": "orange",         # Warning orange  
    "writeout": "violet",      # Violet/purple
    "tool": "gray",            # Neutral gray for tools
    "default": "blue"          # Fallback
}

# Module display names and icons
MODULE_INFO = {
    "supervisor": {"name": "SUPERVISOR", "icon": ""},
    "readin": {"name": "READ-IN", "icon": ""},
    "guide": {"name": "GUIDE", "icon": ""},
    "writeout": {"name": "WRITE-OUT", "icon": ""},
    "tool": {"name": "TOOL", "icon": "🔧"},
    "default": {"name": "AI", "icon": ""}
}


def render_header_with_logo() -> None:
    """Render a top header with the Vitess AI logo if available."""
    if _logo_path.exists():
        left, mid, right = st.columns([1, 6, 1])
        with left:
            st.image(str(_logo_path), use_container_width=True)
        with mid:
            st.title("Vitess AI Agent Chatbot")
        with right:
            st.empty()
    else:
        # Fallback to text title
        st.title("Vitess AI Agent Chatbot")


def module_badge_html(module_display_name: str) -> str:
    """Render module badge as HTML."""
    return f'<strong>{module_display_name}</strong>'


def render_module_badge(module_name: str) -> str:
    """
    Get formatted module badge HTML.
    
    Args:
        module_name: Module identifier
        
    Returns:
        Formatted badge HTML string
    """
    module_info = MODULE_INFO.get(module_name, MODULE_INFO["default"])
    return module_badge_html(module_info['name'])


def render_content(content: any, color: str) -> None:
    """
    Render message content uniformly (JSON or markdown).
    
    Args:
        content: Message content (string, dict, list, or JSON string)
        color: Border color for styling
    """
    # Try to render JSON nicely if possible
    if isinstance(content, (dict, list)):
        st.json(content)
    else:
        try:
            # Try parsing as JSON string
            parsed = json.loads(str(content))
            st.json(parsed)
        except (json.JSONDecodeError, TypeError):
            # Render as markdown with color styling
            content_str = str(content) if content else ""
            if content_str.strip():
                st.markdown(
                    f'<div style="border-left: 4px solid {color}; padding-left: 10px; margin: 5px 0;">{content_str}</div>',
                    unsafe_allow_html=True
                )


def render_message_header(badge_text: str, message_type: str, tool_names: list[str] = None, is_mcp: bool = False) -> None:
    """
    Render consistent message header with badge and type indicator.
    
    Args:
        badge_text: Formatted module badge HTML
        message_type: Type of message (ai, tool, etc.)
        tool_names: Optional list of tool names for tool messages
        is_mcp: Whether this is an MCP tool message
    """
    if message_type == "tool":
        if is_mcp:
            st.markdown(
                f"{badge_text} | ✅ <strong>MCP Tool Result</strong>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"{badge_text} | 🔧 <strong>Tool Result</strong>",
                unsafe_allow_html=True,
            )
    elif message_type == "ai" and tool_names:
        st.markdown(
            f"{badge_text} | 🔧 <strong>MCP Tool Call</strong>: {', '.join(tool_names)}",
            unsafe_allow_html=True,
        )
    else:
        # Regular AI message - just show badge
        st.markdown(badge_text, unsafe_allow_html=True)


def render_message(message: ChatMessage, show_system: bool = False) -> None:
    """
    Render a chat message uniformly with consistent styling across all message types.
    
    This unified function handles all message types (human, ai, tool, system) with
    consistent module badge display, color coding, and content rendering.
    
    Args:
        message: ChatMessage to display
        show_system: If True, display system messages. If False, skip them.
    """
    # Skip system messages unless explicitly enabled
    if message.type == "system" and not show_system:
        return
    
    # Extract module information for color coding
    custom_data = message.custom_data or {}
    module_name = custom_data.get("module_name", "default")
    color = MODULE_COLORS.get(module_name, MODULE_COLORS["default"])
    
    # Render based on message type
    if message.type == "human":
        # User messages - simple display
        with st.chat_message("user"):
            st.write(message.content)
    
    elif message.type == "ai":
        # AI messages - unified rendering with badges and content
        with st.chat_message("assistant"):
            badge_text = render_module_badge(module_name)
            
            # Check if this is an MCP tool call
            is_mcp_call = (
                custom_data.get("has_mcp_tools", False) or
                custom_data.get("source") == "mcp"
            )
            
            # Extract tool names if present
            tool_names = None
            if message.tool_calls:
                tool_names = [tc.get("name", "unknown") for tc in message.tool_calls]
            
            # Render header (badge + type indicator if needed)
            render_message_header(
                badge_text,
                "ai",
                tool_names=tool_names if is_mcp_call else None,
                is_mcp=False
            )
            
            # Render content uniformly
            if message.content:
                render_content(message.content, color)
    
    elif message.type == "tool":
        # Tool messages - unified rendering same as AI messages
        with st.chat_message("assistant"):
            badge_text = render_module_badge(module_name)
            
            # Check if this is an MCP tool result
            is_mcp_tool = (
                custom_data.get("is_mcp_tool", False) or
                custom_data.get("source") == "mcp"
            )
            
            # Render header (badge + tool indicator)
            render_message_header(badge_text, "tool", is_mcp=is_mcp_tool)
            
            # Render content uniformly
            if message.content:
                render_content(message.content, color)
    
    elif message.type == "system":
        # System messages - plain text display
        with st.chat_message("assistant"):
            st.text(message.content)


def render_streaming_token(
    module_name: str,
    response_text: str,
    message_placeholder
) -> None:
    """
    Render streaming text with module badge and color styling.
    
    Args:
        module_name: Module name for badge and color
        response_text: Accumulated response text so far
        message_placeholder: Streamlit placeholder for the message
    """
    color = MODULE_COLORS.get(module_name, MODULE_COLORS["default"])
    badge_text = render_module_badge(module_name)
    
    # Display badge and content with cursor
    message_placeholder.markdown(f"{badge_text}", unsafe_allow_html=True)
    message_placeholder.markdown(
        f'<div style="border-left: 4px solid {color}; padding-left: 10px; margin: 5px 0;">{response_text}▌</div>',
        unsafe_allow_html=True,
    )

