"""
UI components for rendering messages and badges in Streamlit.

This module provides functions for rendering chat messages, badges, and content
with consistent styling across the application.
"""
import json
import streamlit as st
from pathlib import Path
from typing import Dict, Any, Optional
import markdown

from vitess_ai.schema.server import ChatMessage

try:
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

# Paths and assets
_assets_dir = Path(__file__).parent / "assets"
_logo_path = _assets_dir / "logo.png"

# Module color mapping for visual differentiation (fallback for when dynamic info unavailable)
MODULE_COLORS = {
    "supervisor": "blue",      # Streamlit's primary blue
    "deep_analysis": "teal",   # Advanced analysis mode
    "readin": "green",         # Success green
    "guide": "orange",         # Warning orange  
    "writeout": "violet",      # Violet/purple
    "sim-runner": "red",       # Simulation execution specialist
    "tool": "gray",            # Neutral gray for tools
    "default": "blue"          # Fallback
}

# Module display names and icons (fallback for when dynamic info unavailable)
MODULE_INFO = {
    "supervisor": {"name": "SUPERVISOR", "icon": ""},
    "deep_analysis": {"name": "DEEP ANALYSIS", "icon": ""},
    "readin": {"name": "READ-IN", "icon": ""},
    "guide": {"name": "GUIDE", "icon": ""},
    "writeout": {"name": "WRITE-OUT", "icon": ""},
    "sim-runner": {"name": "SIM RUNNER", "icon": ""},
    "tool": {"name": "TOOL", "icon": "🔧"},
    "default": {"name": "AI", "icon": ""}
}

# Color palette for dynamic module assignment
# These colors are assigned to modules based on their order when not in MODULE_COLORS
COLOR_PALETTE = [
    "blue", "green", "orange", "violet", "red", "purple", 
    "pink", "yellow", "cyan", "teal", "indigo", "brown"
]


def get_module_info_from_server(server_url: str) -> Dict[str, Any]:
    """
    Fetch module information from the server and cache it in session state.
    
    Args:
        server_url: Base URL of the server
        
    Returns:
        Dictionary mapping module names to their info (name, display_name, order, etc.)
    """
    # Check if we have cached module info
    if "module_info_cache" not in st.session_state:
        st.session_state.module_info_cache = {}
    
    # Check if we have a cached timestamp and if it's recent (cache for 5 minutes)
    cache_key = f"module_info_{server_url}"
    if cache_key in st.session_state.module_info_cache:
        cached_data = st.session_state.module_info_cache[cache_key]
        # For simplicity, we'll refresh on each page load (Streamlit reruns)
        # In production, you might want to add timestamp checking
        pass
    
    # Try to fetch from server
    try:
        import httpx
        response = httpx.get(
            f"{server_url}/config/modules",
            timeout=5.0
        )
        response.raise_for_status()
        data = response.json()
        
        if data.get("status") == "success":
            modules = data.get("modules", [])
            # Build module info dictionary
            module_info_dict = {}
            for module in modules:
                module_name = module.get("name", "")
                if module_name:
                    module_info_dict[module_name] = {
                        "name": module.get("display_name", module_name.upper()),
                        "display_name": module.get("display_name", module_name),
                        "order": module.get("order", 999),
                        "description": module.get("description", ""),
                        "icon": ""  # Icons can be added later if needed
                    }
            
            # Cache the result
            st.session_state.module_info_cache[cache_key] = module_info_dict
            return module_info_dict
    except Exception as e:
        # If fetch fails, return empty dict (will use fallbacks)
        pass
    
    # Return cached data if available, otherwise empty dict
    return st.session_state.module_info_cache.get(cache_key, {})


def get_module_color(module_name: str, dynamic_modules: Optional[Dict[str, Any]] = None) -> str:
    """
    Get color for a module, using dynamic info if available, otherwise fallback.
    
    Args:
        module_name: Module identifier
        dynamic_modules: Optional dictionary of dynamic module info
        
    Returns:
        Color string for the module
    """
    # First check hardcoded colors (for backward compatibility)
    if module_name in MODULE_COLORS:
        return MODULE_COLORS[module_name]
    
    # If we have dynamic modules, assign color based on order
    if dynamic_modules and module_name in dynamic_modules:
        module_order = dynamic_modules[module_name].get("order", 999)
        # Use order to pick a color from palette (skip supervisor, tool, default)
        color_index = (module_order - 1) % len(COLOR_PALETTE)
        return COLOR_PALETTE[color_index]
    
    # Fallback to default
    return MODULE_COLORS["default"]


def render_header_with_logo() -> None:
    """Render a top header with the Vitess AI logo if available."""
    # Just display the title without the logo
    st.title("Vitess AI Agent Chatbot")


def module_badge_html(module_display_name: str) -> str:
    """Render module badge as HTML."""
    return f'<strong>{module_display_name}</strong>'


def render_module_badge(module_name: str, dynamic_modules: Optional[Dict[str, Any]] = None) -> str:
    """
    Get formatted module badge HTML.
    
    Args:
        module_name: Module identifier
        dynamic_modules: Optional dictionary of dynamic module info from server
        
    Returns:
        Formatted badge HTML string
    """
    # Try to get display name from dynamic modules first
    if dynamic_modules and module_name in dynamic_modules:
        display_name = dynamic_modules[module_name].get("name", module_name.upper())
        return module_badge_html(display_name)
    
    # Fallback to hardcoded MODULE_INFO
    module_info = MODULE_INFO.get(module_name, MODULE_INFO["default"])
    return module_badge_html(module_info['name'])


def markdown_to_html(markdown_text: str) -> str:
    """
    Convert markdown text to HTML.
    
    Args:
        markdown_text: Markdown-formatted text string
        
    Returns:
        HTML string with markdown converted to HTML
    """
    if not markdown_text:
        return ""
    
    # Convert markdown to HTML
    html = markdown.markdown(str(markdown_text), extensions=['fenced_code', 'nl2br'])
    return html


def render_plotly_figure(plot_json: Dict[str, Any], title: str, expanded: bool = True) -> None:
    """
    Render a Plotly figure in an expandable section.
    
    Args:
        plot_json: Plotly figure as JSON-serializable dict
        title: Title for the expander
        expanded: Whether the expander should be expanded by default
    """
    if not PLOTLY_AVAILABLE:
        st.warning("Plotly is not available. Please install plotly to view interactive plots.")
        return
    
    try:
        # Reconstruct Plotly figure from JSON
        fig = go.Figure(plot_json)
        
        # Render in expandable section
        with st.expander(title, expanded=expanded):
            st.plotly_chart(fig, width='stretch')
    except Exception as e:
        st.error(f"Error rendering plot: {str(e)}")


def render_content(content: any, color: str, custom_data: Optional[Dict[str, Any]] = None) -> None:
    """
    Render message content uniformly (JSON or markdown).
    
    Args:
        content: Message content (string, dict, list, or JSON string)
        color: Border color for styling
        custom_data: Optional custom data that may contain plot information
    """
    # Check for plot data in custom_data first
    if custom_data:
        plot_data = custom_data.get("plot_data", {})
        if plot_data:
            # Render plots in expandable sections
            # Render Monitor1D plot if available
            if "monitor1d" in plot_data:
                plot_info = plot_data["monitor1d"]
                plot_json = plot_info.get("plot_json")
                if plot_json:
                    render_plotly_figure(
                        plot_json,
                        f"📊 {plot_info.get('title', 'Monitor1D Results')}",
                        expanded=True
                    )
                else:
                    st.warning("Monitor1D plot data is missing plot_json")
            
            # Render Monitor2D plot if available
            if "monitor2d" in plot_data:
                plot_info = plot_data["monitor2d"]
                plot_json = plot_info.get("plot_json")
                if plot_json:
                    render_plotly_figure(
                        plot_json,
                        f"📊 {plot_info.get('title', 'Monitor2D Results')}",
                        expanded=True
                    )
                else:
                    st.warning("Monitor2D plot data is missing plot_json")
    
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
                # Convert markdown to HTML first, then wrap in styled div
                html_content = markdown_to_html(content_str)
                st.markdown(
                    f'<div style="border-left: 4px solid {color}; padding-left: 10px; margin: 5px 0;">{html_content}</div>',
                    unsafe_allow_html=True
                )


def render_message_header(badge_text: str, message_type: str) -> None:
    """
    Render consistent message header with badge and type indicator.
    
    Args:
        badge_text: Formatted module badge HTML
        message_type: Type of message ("ai" or "tool")
    """
    if message_type == "tool":
        st.markdown(
            f"{badge_text} | 🔧 <strong>Tool Result</strong>",
            unsafe_allow_html=True,
        )
    else:
        # AI message - just show badge
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
    
    # Get dynamic module info if available
    dynamic_modules = None
    if "server_url" in st.session_state:
        dynamic_modules = get_module_info_from_server(st.session_state.server_url)
    
    # Extract module information for color coding
    custom_data = message.custom_data or {}
    module_name = custom_data.get("module_name", "default")
    color = get_module_color(module_name, dynamic_modules)
    
    # Render based on message type
    if message.type == "human":
        # User messages - simple display
        with st.chat_message("user"):
            st.write(message.content)
    
    elif message.type == "ai":
        # AI messages - unified rendering with badges and content
        with st.chat_message("assistant"):
            badge_text = render_module_badge(module_name, dynamic_modules)
            
            # Render header (badge only for AI messages)
            render_message_header(badge_text, "ai")
            
            # Render content uniformly
            if message.content:
                render_content(message.content, color, custom_data=message.custom_data)
    
    elif message.type == "tool":
        # Tool messages - unified rendering same as AI messages
        with st.chat_message("assistant"):
            badge_text = render_module_badge(module_name, dynamic_modules)
            
            # Render header (badge + tool indicator)
            render_message_header(badge_text, "tool")
            
            # Render content uniformly
            if message.content:
                render_content(message.content, color, custom_data=message.custom_data)
    
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
    # Get dynamic module info if available
    dynamic_modules = None
    if "server_url" in st.session_state:
        dynamic_modules = get_module_info_from_server(st.session_state.server_url)
    
    color = get_module_color(module_name, dynamic_modules)
    badge_text = render_module_badge(module_name, dynamic_modules)
    
    # Convert markdown to HTML first, then wrap in styled div
    html_content = markdown_to_html(response_text)
    
    # Display badge and content with cursor
    message_placeholder.markdown(f"{badge_text}", unsafe_allow_html=True)
    message_placeholder.markdown(
        f'<div style="border-left: 4px solid {color}; padding-left: 10px; margin: 5px 0;">{html_content}▌</div>',
        unsafe_allow_html=True,
    )


def finalize_streaming_message(
    message_placeholder,
    content: any,
    module_name: str,
    custom_data: Optional[Dict[str, Any]] = None
) -> None:
    """
    Finalize a streaming message by clearing the placeholder and rendering
    final content with the same logic as history (JSON or markdown).
    
    This ensures the streamed message looks identical to how it will appear
    after st.rerun(), avoiding visual jumps.
    
    Args:
        message_placeholder: Streamlit placeholder (st.empty()) to finalize
        content: Message content (string, dict, list, or JSON string)
        module_name: Module name for badge and color styling
        custom_data: Optional custom data that may contain plot information
    """
    # Get dynamic module info if available
    dynamic_modules = None
    if "server_url" in st.session_state:
        dynamic_modules = get_module_info_from_server(st.session_state.server_url)
    
    color = get_module_color(module_name, dynamic_modules)
    badge_text = render_module_badge(module_name, dynamic_modules)
    
    # Clear the placeholder and render final content in a container
    with message_placeholder.container():
        # Render header (badge)
        render_message_header(badge_text, "ai")
        # Render content with JSON/markdown logic
        if content:
            render_content(content, color, custom_data=custom_data)
