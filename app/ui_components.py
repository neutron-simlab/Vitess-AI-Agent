"""
UI components for rendering messages and badges in Streamlit.

This module provides functions for rendering chat messages, badges, and content
with consistent styling across the application.
"""
import json
import re
import streamlit as st
from typing import Dict, Any, Optional
import markdown

from vitess_ai.schema.server import ChatMessage

try:
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

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

# Delegated task lifecycle status values
TASK_STATUS_VALUES = {"pending", "running", "complete"}


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
    
    # Cache key for fallback lookup if server fetch fails
    cache_key = f"module_info_{server_url}"
    
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


def apply_task_lifecycle_event(
    current_tasks: Dict[str, Dict[str, Any]],
    event_content: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """
    Apply one task_lifecycle event to per-turn task state (pure helper).

    Args:
        current_tasks: Existing task map keyed by task_id
        event_content: Parsed lifecycle event payload

    Returns:
        Updated task map (new dictionary)
    """
    updated_tasks: Dict[str, Dict[str, Any]] = {
        task_id: dict(task_data)
        for task_id, task_data in (current_tasks or {}).items()
    }

    task_id = str(event_content.get("task_id") or "").strip()
    if not task_id:
        return updated_tasks

    existing = updated_tasks.get(task_id, {})
    status = str(
        event_content.get("status")
        or event_content.get("phase")
        or existing.get("status")
        or "pending"
    ).lower()
    if status not in TASK_STATUS_VALUES:
        status = "pending"

    updated_tasks[task_id] = {
        "task_id": task_id,
        "run_id": event_content.get("run_id", existing.get("run_id")),
        "sequence": event_content.get("sequence", existing.get("sequence")),
        "phase": event_content.get("phase", existing.get("phase")),
        "status": status,
        "subagent_type": event_content.get("subagent_type", existing.get("subagent_type", "unknown")),
        "description": event_content.get("description", existing.get("description", "")),
        "pregel_id": event_content.get("pregel_id", existing.get("pregel_id")),
        "result_preview": event_content.get("result_preview", existing.get("result_preview")),
        "timestamp": event_content.get("timestamp", existing.get("timestamp")),
    }
    return updated_tasks


def get_task_lifecycle_counts(tasks: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    """
    Count pending/running/complete tasks from lifecycle state.

    Args:
        tasks: Task map keyed by task_id

    Returns:
        Dict with counts for pending, running, and complete
    """
    counts = {"pending": 0, "running": 0, "complete": 0}
    for task in (tasks or {}).values():
        status = str(task.get("status", "pending")).lower()
        if status not in counts:
            status = "pending"
        counts[status] += 1
    return counts


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


# Plot keys and default titles for tool plot_data (monitor1d, monitor2d, etc.)
_PLOT_ENTRIES = (
    ("monitor1d", "Monitor1D Results"),
    ("monitor2d", "Monitor2D Results"),
)


def _render_plot_data(plot_data: Dict[str, Any]) -> bool:
    """Render all plot entries in plot_data. Returns True if any plot was rendered."""
    rendered = False
    for key, default_title in _PLOT_ENTRIES:
        plot_info = plot_data.get(key)
        if not plot_info or not isinstance(plot_info, dict):
            continue
        plot_json = plot_info.get("plot_json")
        if not plot_json:
            st.warning(f"{key}: plot data is missing plot_json")
            continue
        title = f"📊 {plot_info.get('title', default_title)}"
        render_plotly_figure(plot_json, title, expanded=True)
        rendered = True
    return rendered


def _get_message_from_content(content: Any) -> Optional[str]:
    """Extract a short 'message' string from tool result content (dict or JSON string)."""
    if content is None:
        return None
    if isinstance(content, dict):
        msg = content.get("message")
        return str(msg).strip() if isinstance(msg, str) else None
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                msg = parsed.get("message")
                return str(msg).strip() if isinstance(msg, str) else None
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def _parse_json_like_content(content: Any) -> Optional[Dict[str, Any] | list[Any]]:
    """Parse tool content into JSON-compatible Python data when possible."""
    if isinstance(content, (dict, list)):
        return content
    if content is None:
        return None

    text = str(content).strip()
    if not text:
        return None

    try:
        parsed = json.loads(text)
        if isinstance(parsed, (dict, list)):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass

    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
    if fenced_match:
        try:
            parsed = json.loads(fenced_match.group(1))
            if isinstance(parsed, (dict, list)):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass

    start_obj = text.find("{")
    end_obj = text.rfind("}")
    if 0 <= start_obj < end_obj:
        candidate = text[start_obj : end_obj + 1]
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def extract_delegated_tool_summary(
    content: Any,
    custom_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Normalize delegated tool payload into a compact, structured summary.

    Returns:
        Dict with keys: module, validation_passed, parameters_count, parameters, raw_payload
    """
    payload = _parse_json_like_content(content)
    module = None
    validation_passed = None
    parameters: Any = None

    if isinstance(payload, dict):
        module = payload.get("module") or payload.get("module_name")
        if isinstance(payload.get("validation_passed"), bool):
            validation_passed = payload.get("validation_passed")
        elif isinstance(payload.get("validation_status"), bool):
            validation_passed = payload.get("validation_status")
        parameters = payload.get("parameters")

    if not module and custom_data:
        module = custom_data.get("subagent_type")

    parameters_count = 0
    if isinstance(parameters, dict):
        parameters_count = 1
    elif isinstance(parameters, list):
        parameters_count = len(parameters)

    return {
        "module": module,
        "validation_passed": validation_passed,
        "parameters_count": parameters_count,
        "parameters": parameters,
        "raw_payload": payload if payload is not None else content,
    }


def should_hide_delegated_tool_body(
    custom_data: Optional[Dict[str, Any]],
    show_delegated_tool_bodies: bool,
) -> bool:
    """Return True when delegated tool body should be hidden in default chat view."""
    if show_delegated_tool_bodies:
        return False
    custom_data = custom_data or {}
    return (
        custom_data.get("tool_kind") == "delegated_subagent_result"
        and custom_data.get("display_mode") == "hidden_by_default"
    )


def _render_delegated_tool_result_card(
    message: ChatMessage,
    color: str,
    show_raw_payload: bool = False,
) -> None:
    """Render compact delegated-tool card with optional raw payload expander."""
    custom_data = message.custom_data or {}
    summary = extract_delegated_tool_summary(message.content, custom_data)

    module_name = str(summary.get("module") or "unknown")
    delegated_task_id = custom_data.get("delegated_task_id") or message.tool_call_id
    validation_value = summary.get("validation_passed")
    if validation_value is True:
        validation_label = "True"
    elif validation_value is False:
        validation_label = "False"
    else:
        validation_label = "Unknown"

    st.markdown(
        (
            f'<div style="border-left: 4px solid {color}; padding-left: 10px; margin: 5px 0;">'
            f"<strong>Delegated Subagent Result</strong><br/>"
            f"Module: <code>{module_name}</code><br/>"
            f"Validation passed: <code>{validation_label}</code><br/>"
            f"Parameter sets: <code>{summary.get('parameters_count', 0)}</code>"
            f"</div>"
        ),
        unsafe_allow_html=True,
    )

    result_preview = custom_data.get("result_preview")
    if isinstance(result_preview, str) and result_preview.strip():
        st.caption(result_preview.strip())
    if delegated_task_id:
        st.caption(f"Task ID: {delegated_task_id}")

    if not show_raw_payload:
        return

    with st.expander("View raw tool payload", expanded=False):
        raw_payload = summary.get("raw_payload")
        if isinstance(raw_payload, (dict, list)):
            st.json(raw_payload)
        else:
            raw_text = str(raw_payload or "").strip()
            if raw_text:
                language = "json" if raw_text.startswith("{") or raw_text.startswith("[") else None
                st.code(raw_text, language=language)
            else:
                st.caption("No payload.")


def render_content(content: Any, color: str, custom_data: Optional[Dict[str, Any]] = None) -> None:
    """
    Render message content uniformly (JSON or markdown).

    Args:
        content: Message content (string, dict, list, or JSON string)
        color: Border color for styling
        custom_data: Optional custom data that may contain plot information
    """
    plot_data = (custom_data or {}).get("plot_data", {})
    rendered_plot = _render_plot_data(plot_data) if plot_data else False

    if rendered_plot:
        msg = _get_message_from_content(content)
        if msg:
            st.caption(msg)
        return

    if isinstance(content, (dict, list)):
        st.json(content)
    else:
        try:
            parsed = json.loads(str(content))
            st.json(parsed)
        except (json.JSONDecodeError, TypeError):
            content_str = str(content) if content else ""
            if content_str.strip():
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

            show_delegated_tool_bodies = bool(st.session_state.get("show_delegated_tool_bodies", False))
            tool_kind = str(custom_data.get("tool_kind", "regular_tool_result"))
            is_plot_tool = tool_kind == "plot_tool_result"

            if should_hide_delegated_tool_body(custom_data, show_delegated_tool_bodies):
                _render_delegated_tool_result_card(
                    message,
                    color,
                    show_raw_payload=show_delegated_tool_bodies,
                )
            elif message.content and not is_plot_tool and not show_delegated_tool_bodies:
                with st.expander("View tool payload", expanded=False):
                    render_content(message.content, color, custom_data=message.custom_data)
            elif message.content:
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


def render_task_lifecycle_stream(
    tasks: Dict[str, Dict[str, Any]],
    stream_placeholder,
) -> None:
    """
    Render compact delegated-task lifecycle updates inside an active chat stream.

    This view is intentionally minimal for in-message monitoring while tokens stream.
    """
    if stream_placeholder is None:
        return
    if not tasks:
        stream_placeholder.empty()
        return

    counts = get_task_lifecycle_counts(tasks)

    def _sort_key(task: Dict[str, Any]) -> tuple[int, str]:
        sequence = task.get("sequence")
        if isinstance(sequence, int):
            return sequence, str(task.get("task_id", ""))
        return 10**9, str(task.get("task_id", ""))

    lines = [
        f"**Delegated Tasks**  ",
        f"Pending: {counts['pending']} | Running: {counts['running']} | Complete: {counts['complete']}",
        "",
    ]
    for task in sorted(tasks.values(), key=_sort_key):
        subagent_type = str(task.get("subagent_type", "unknown"))
        status = str(task.get("status", "pending")).upper()
        description = str(task.get("description", "")).strip()
        task_id = str(task.get("task_id", "")).strip()
        line = f"- `{status}` **{subagent_type}**"
        if description:
            line += f": {description}"
        if task_id:
            line += f" (`{task_id}`)"
        lines.append(line)

    stream_placeholder.markdown("\n".join(lines))
