"""
Streamlit UI for Vitess AI Supervisor Agent

This Streamlit application provides a web interface for interacting with the
Vitess AI supervisor agent through the FastAPI service.
"""

import streamlit as st
import httpx
from uuid import uuid4
from typing import Optional
import sys
import json
from pathlib import Path

# Paths and assets
_assets_dir = Path(__file__).parent / "assets"
_logo_path = _assets_dir / "logo.png"

# Add parent directory to path to import vitess_ai modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitess_ai.clients.client import AgentClient, AgentClientError
from vitess_ai.schema.server import ChatMessage, ModuleInterruptResponse
from vitess_ai.schema.llm_models import Provider, OpenAIModelName, BlabladorModelName


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


# Page configuration
st.set_page_config(
    page_title="Vitess AI Agent Chatbot",
    page_icon=str(_logo_path) if _logo_path.exists() else None,
    layout="wide",
    initial_sidebar_state="expanded"
)

# Try to load and display the Vitess AI logo

def _render_header_with_logo() -> None:
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

def _module_badge_html(module_display_name: str) -> str:
    """Render module badge as HTML."""
    return f'<strong>{module_display_name}</strong>'


def _render_module_badge(module_name: str) -> str:
    """
    Get formatted module badge HTML.
    
    Args:
        module_name: Module identifier
        
    Returns:
        Formatted badge HTML string
    """
    module_info = MODULE_INFO.get(module_name, MODULE_INFO["default"])
    return _module_badge_html(module_info['name'])


def _render_content(content: any, color: str) -> None:
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


def _render_message_header(badge_text: str, message_type: str, tool_names: list[str] = None, is_mcp: bool = False) -> None:
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

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []

if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid4())

if "user_id" not in st.session_state:
    st.session_state.user_id = str(uuid4())

if "server_url" not in st.session_state:
    st.session_state.server_url = "http://localhost:8000"

if "client" not in st.session_state:
    st.session_state.client = None

if "current_interrupt" not in st.session_state:
    st.session_state.current_interrupt = None

if "server_connected" not in st.session_state:
    st.session_state.server_connected = False

if "show_system_messages" not in st.session_state:
    st.session_state.show_system_messages = False

if "selected_provider" not in st.session_state:
    st.session_state.selected_provider = Provider.OPENAI.value

if "selected_model" not in st.session_state:
    st.session_state.selected_model = OpenAIModelName.GPT_4O_MINI.value

if "provider_change_pending" not in st.session_state:
    st.session_state.provider_change_pending = False

if "pending_provider" not in st.session_state:
    st.session_state.pending_provider = None

if "pending_model" not in st.session_state:
    st.session_state.pending_model = None


def check_server_health(server_url: str) -> bool:
    """Check if server is running by hitting /health endpoint."""
    try:
        response = httpx.get(f"{server_url}/health", timeout=2.0)
        return response.status_code == 200
    except Exception:
        return False


def initialize_client(server_url: str) -> Optional[AgentClient]:
    """Initialize AgentClient with server URL."""
    try:
        # Set get_info=False since /info endpoint doesn't exist in the service
        # Initialize without agent first, then set it with verify=False
        client = AgentClient(base_url=server_url, agent=None, get_info=False)
        # Set agent to "supervisor" without verification
        client.update_agent("supervisor", verify=False)
        return client
    except Exception as e:
        st.error(f"Failed to initialize client: {e}")
        return None


def is_message_duplicate(message: ChatMessage, messages: list[ChatMessage]) -> bool:
    """Check if a message is a duplicate based on content and type.
    
    Args:
        message: ChatMessage to check
        messages: List of existing messages
        
    Returns:
        True if duplicate found, False otherwise
    """
    for existing_msg in messages:
        if (isinstance(existing_msg, ChatMessage) and 
            existing_msg.type == message.type and
            existing_msg.content == message.content):
            return True
    return False


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
            badge_text = _render_module_badge(module_name)
            
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
            _render_message_header(
                badge_text,
                "ai",
                tool_names=tool_names if is_mcp_call else None,
                is_mcp=False
            )
            
            # Render content uniformly
            if message.content:
                _render_content(message.content, color)
    
    elif message.type == "tool":
        # Tool messages - unified rendering same as AI messages
        with st.chat_message("assistant"):
            badge_text = _render_module_badge(module_name)
            
            # Check if this is an MCP tool result
            is_mcp_tool = (
                custom_data.get("is_mcp_tool", False) or
                custom_data.get("source") == "mcp"
            )
            
            # Render header (badge + tool indicator)
            _render_message_header(badge_text, "tool", is_mcp=is_mcp_tool)
            
            # Render content uniformly
            if message.content:
                _render_content(message.content, color)
    
    elif message.type == "system":
        # System messages - plain text display
        with st.chat_message("assistant"):
            st.text(message.content)




def _render_streaming_token(
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
    badge_text = _render_module_badge(module_name)
    
    # Display badge and content with cursor
    message_placeholder.markdown(f"{badge_text}", unsafe_allow_html=True)
    message_placeholder.markdown(
        f'<div style="border-left: 4px solid {color}; padding-left: 10px; margin: 5px 0;">{response_text}▌</div>',
        unsafe_allow_html=True,
    )


def _process_stream_chunk(
    chunk,
    client: AgentClient,
    current_streaming_module: str,
    response_text: str,
    received_complete_message: bool,
    message_placeholder,
    messages: list
) -> tuple[str, str, bool]:
    """
    Process a single chunk from the stream and update UI.
    
    Args:
        chunk: Stream chunk (ChatMessage, token dict, ModuleInterruptResponse, etc.)
        client: AgentClient instance for helper methods
        current_streaming_module: Current module name
        response_text: Accumulated response text
        received_complete_message: Whether complete message was received
        message_placeholder: Streamlit placeholder
        messages: Message history list
        
    Returns:
        Tuple of (updated_response_text, updated_module, updated_complete_flag)
    """
    if isinstance(chunk, ModuleInterruptResponse):
        # Module interrupt - return as-is for caller to handle
        return response_text, current_streaming_module, received_complete_message
    
    elif isinstance(chunk, ChatMessage):
        # Complete message received
        content_str = str(chunk.content) if chunk.content is not None else ""
        # Skip stray 'Start' messages
        if content_str.strip().lower() == "start":
            return response_text, current_streaming_module, received_complete_message
        
        received_complete_message = True
        if not is_message_duplicate(chunk, messages):
            messages.append(chunk)
        
        if chunk.type == "ai":
            message_placeholder.markdown(chunk.content)
            response_text = chunk.content
        
        return response_text, current_streaming_module, received_complete_message
    
    elif client.is_token_message(chunk):
        # Token message - normalize and accumulate
        if not received_complete_message:
            token_module = client.get_token_module(chunk) or current_streaming_module
            token_content = client.get_token_content(chunk) or ""
            
            if token_content:
                # Update module if changed
                if token_module != current_streaming_module:
                    current_streaming_module = token_module
                
                response_text += token_content
                _render_streaming_token(
                    current_streaming_module,
                    response_text,
                    message_placeholder
                )
        
        return response_text, current_streaming_module, received_complete_message
    
    return response_text, current_streaming_module, received_complete_message


# Sidebar - Configuration and Status
with st.sidebar:
    if _logo_path.exists():
        st.image(str(_logo_path), use_container_width=True)
    st.title("Vitess AI Agent Chatbot")
    st.divider()

    # Server Configuration
    st.subheader("Server Configuration")
    server_url_input = st.text_input(
        "Server URL",
        value=st.session_state.server_url,
        help="FastAPI server URL (default: http://localhost:8000)"
    )

    if server_url_input != st.session_state.server_url:
        st.session_state.server_url = server_url_input
        st.session_state.client = None
        st.session_state.server_connected = False
        st.session_state._health_checked = False

    # Health Check
    if st.button("🔄 Check Server Status", use_container_width=True):
        st.session_state.server_connected = check_server_health(st.session_state.server_url)
        if st.session_state.server_connected:
            st.session_state.client = initialize_client(st.session_state.server_url)
            if st.session_state.client is None:
                st.session_state.server_connected = False
        else:
            st.session_state.client = None

    # Auto-check on load (only if not already checked)
    if st.session_state.client is None:
        # Only check if we haven't initialized or if server was previously disconnected
        if not hasattr(st.session_state, '_health_checked'):
            st.session_state.server_connected = check_server_health(st.session_state.server_url)
            st.session_state._health_checked = True
            if st.session_state.server_connected:
                st.session_state.client = initialize_client(st.session_state.server_url)
                if st.session_state.client is None:
                    st.session_state.server_connected = False

    # Display connection status
    if st.session_state.server_connected:
        st.success("🟢 Server Connected")
    else:
        st.error("🔴 Server Disconnected")
        st.info(
            """
            **Server not running. Please start the server:**
            ```bash
            python main.py
            ```
            Server should run on `http://localhost:8000`
            """
        )

    st.divider()

    # LLM Provider and Model Selection
    st.subheader("LLM Configuration")
    
    # Show confirmation dialog if provider change is pending
    if st.session_state.provider_change_pending and st.session_state.pending_provider:
        st.warning(
            f"⚠️ **Provider Change Pending**\n\n"
            f"You selected **{st.session_state.pending_provider}** as the provider.\n\n"
            f"This will regenerate the agent graph with the new LLM. "
            f"Your current conversation will continue with the new model.\n\n"
            f"**Model**: {st.session_state.pending_model or ('alias-function-call' if st.session_state.pending_provider == Provider.BLABLADOR.value else 'gpt-4o-mini')}"
        )
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Confirm", use_container_width=True, type="primary"):
                # Apply the provider change
                st.session_state.selected_provider = st.session_state.pending_provider
                if st.session_state.pending_model:
                    st.session_state.selected_model = st.session_state.pending_model
                elif st.session_state.pending_provider == Provider.BLABLADOR.value:
                    st.session_state.selected_model = BlabladorModelName.ALIAS_FUNCTION_CALL.value
                else:
                    st.session_state.selected_model = OpenAIModelName.GPT_4O_MINI.value
                
                # Clear pending state
                st.session_state.provider_change_pending = False
                st.session_state.pending_provider = None
                st.session_state.pending_model = None
                
                # Restart the graph with new provider/model if server is connected
                if st.session_state.server_connected and st.session_state.client:
                    try:
                        st.session_state.client.restart(
                            provider=st.session_state.selected_provider,
                            model=st.session_state.selected_model
                        )
                        # Clear conversation state for fresh start
                        st.session_state.thread_id = str(uuid4())
                        st.session_state.user_id = str(uuid4())
                        st.session_state.messages = []
                        st.session_state.current_interrupt = None
                        st.session_state.welcome_initialized = False
                        st.success(f"✅ Switched to **{st.session_state.selected_provider}** with model **{st.session_state.selected_model}**. Graph restarted and conversation cleared for fresh start!")
                    except Exception as e:
                        st.warning(f"⚠️ Provider/model changed, but graph restart failed: {e}. Graph will regenerate on next request.")
                else:
                    st.success(f"✅ Switched to **{st.session_state.selected_provider}** with model **{st.session_state.selected_model}**. Graph will regenerate on next request.")
                st.rerun()
        
        with col2:
            if st.button("❌ Cancel", use_container_width=True):
                # Cancel the change
                st.session_state.provider_change_pending = False
                st.session_state.pending_provider = None
                st.session_state.pending_model = None
                st.rerun()
        
        st.divider()
        # Show current provider (not pending one) while confirmation is pending
        st.info(f"**Current Provider**: {st.session_state.selected_provider}")
    else:
        # Provider selector (only show when not pending confirmation)
        provider_options = [Provider.OPENAI.value, Provider.BLABLADOR.value]
        selected_provider = st.radio(
            "Provider",
            options=provider_options,
            index=provider_options.index(st.session_state.selected_provider) if st.session_state.selected_provider in provider_options else 0,  # Default to OpenAI (index 0)
            help="Select the LLM provider to use"
        )
        
        # Handle provider change - require confirmation for Blablador
        if selected_provider != st.session_state.selected_provider:
            if selected_provider == Provider.BLABLADOR.value:
                # For Blablador, require confirmation
                st.session_state.provider_change_pending = True
                st.session_state.pending_provider = selected_provider
                st.session_state.pending_model = BlabladorModelName.ALIAS_FUNCTION_CALL.value
                st.rerun()
            else:
                # For OpenAI, apply immediately
                st.session_state.selected_provider = selected_provider
                st.session_state.selected_model = OpenAIModelName.GPT_4O_MINI.value
                
                # Restart the graph with new provider/model if server is connected
                if st.session_state.server_connected and st.session_state.client:
                    try:
                        st.session_state.client.restart(
                            provider=st.session_state.selected_provider,
                            model=st.session_state.selected_model
                        )
                        # Clear conversation state for fresh start
                        st.session_state.thread_id = str(uuid4())
                        st.session_state.user_id = str(uuid4())
                        st.session_state.messages = []
                        st.session_state.current_interrupt = None
                        st.session_state.welcome_initialized = False
                        st.info("✅ Switched to OpenAI. Graph restarted and conversation cleared for fresh start!")
                    except Exception as e:
                        st.warning(f"⚠️ Provider/model changed, but graph restart failed: {e}. Graph will regenerate on next request.")
                else:
                    st.info("✅ Switched to OpenAI. Graph will regenerate on next request.")
        
        # Model selector based on provider
        if st.session_state.selected_provider == Provider.OPENAI.value:
            model_options = [model.value for model in OpenAIModelName]
            # Ensure selected model is valid for current provider
            if st.session_state.selected_model not in model_options:
                st.session_state.selected_model = OpenAIModelName.GPT_4O_MINI.value
            selected_model = st.selectbox(
                "Model",
                options=model_options,
                index=model_options.index(st.session_state.selected_model) if st.session_state.selected_model in model_options else 0,
                help="Select the OpenAI model to use"
            )
        else:  # Blablador
            model_options = [model.value for model in BlabladorModelName]
            # Ensure selected model is valid for current provider, or auto-select alias-function-call
            if st.session_state.selected_model not in model_options:
                st.session_state.selected_model = BlabladorModelName.ALIAS_FUNCTION_CALL.value
            selected_model = st.selectbox(
                "Model",
                options=model_options,
                index=model_options.index(st.session_state.selected_model) if st.session_state.selected_model in model_options else 0,
                help="Select the Blablador model to use (defaults to alias-function-call)"
            )
        
        # Update model if changed
        if selected_model != st.session_state.selected_model:
            st.session_state.selected_model = selected_model
            
            # Restart the graph with new model if server is connected
            if st.session_state.server_connected and st.session_state.client:
                try:
                    st.session_state.client.restart(
                        provider=st.session_state.selected_provider,
                        model=st.session_state.selected_model
                    )
                    # Clear conversation state for fresh start
                    st.session_state.thread_id = str(uuid4())
                    st.session_state.user_id = str(uuid4())
                    st.session_state.messages = []
                    st.session_state.current_interrupt = None
                    st.session_state.welcome_initialized = False
                    st.info(f"✅ Model changed to **{selected_model}**. Graph restarted and conversation cleared for fresh start!")
                except Exception as e:
                    st.warning(f"⚠️ Model changed, but graph restart failed: {e}. Graph will regenerate on next request.")
            else:
                st.info(f"ℹ️ Model changed to **{selected_model}**. Graph will regenerate with the new model on next request.")
        
        st.divider()

    # Thread Management
    st.subheader("Thread Management")
    st.text(f"Thread ID: {st.session_state.thread_id[:8]}...")
    st.text(f"User ID: {st.session_state.user_id[:8]}...")

    if st.button("🆕 New Thread", use_container_width=True):
        st.session_state.thread_id = str(uuid4())
        st.session_state.user_id = str(uuid4())
        st.session_state.messages = []
        st.session_state.current_interrupt = None
        st.rerun()

    if st.button("🗑️ Clear Chat", use_container_width=True):
        st.session_state.messages = []
        st.session_state.current_interrupt = None
        st.rerun()

    st.divider()

    # Debug Options
    st.subheader("Debug Options")
    show_system = st.checkbox(
        "Show System Messages",
        value=st.session_state.show_system_messages,
        help="Show internal system messages (for debugging)"
    )
    if show_system != st.session_state.show_system_messages:
        st.session_state.show_system_messages = show_system
        st.rerun()

    st.divider()

    # Information
    st.subheader("About")
    st.info(
        """
        **Vitess AI Supervisor** helps configure neutron simulation
        parameters through an interactive chat interface.
        
        The system guides you through:
        - Read-in parameters
        - Guide configuration
        - Writeout settings
        - Simulation execution
        """
    )


# Main Chat Interface
_render_header_with_logo()

# Do not inject a local welcome message; initialize from server when available

# Auto-trigger initial welcome from server when connected and history is empty
if (
    st.session_state.server_connected
    and st.session_state.client
    and not st.session_state.messages
    and not st.session_state.get("welcome_initialized", False)
    and not st.session_state.current_interrupt
):
    st.session_state.welcome_initialized = True
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        response_text = ""
        received_complete_message = False
        current_streaming_module = "default"

        try:
            for chunk in st.session_state.client.stream(
                message="Start",
                thread_id=st.session_state.thread_id,
                user_id=st.session_state.user_id,
                provider=st.session_state.selected_provider,
                model=st.session_state.selected_model,
                stream_tokens=True,
            ):
                if isinstance(chunk, ModuleInterruptResponse):
                    st.session_state.current_interrupt = chunk
                    st.rerun()
                
                # Process chunk using unified helper
                response_text, current_streaming_module, received_complete_message = _process_stream_chunk(
                    chunk,
                    st.session_state.client,
                    current_streaming_module,
                    response_text,
                    received_complete_message,
                    message_placeholder,
                    st.session_state.messages
                )

        except AgentClientError as e:
            st.error(f"Error communicating with server: {e}")
            error_message = ChatMessage(type="ai", content=f"Error: {str(e)}")
            st.session_state.messages.append(error_message)
        except Exception as e:
            st.error(f"Unexpected error: {e}")
            error_message = ChatMessage(type="ai", content=f"Unexpected error: {str(e)}")
            st.session_state.messages.append(error_message)
        finally:
            # Finalize message if we streamed tokens only
            if response_text and not received_complete_message:
                color = MODULE_COLORS.get(current_streaming_module, MODULE_COLORS["default"])
                badge_text = _render_module_badge(current_streaming_module)
                message_placeholder.markdown(f"{badge_text}", unsafe_allow_html=True)
                message_placeholder.markdown(
                    f'<div style="border-left: 4px solid {color}; padding-left: 10px; margin: 5px 0;">{response_text}</div>',
                    unsafe_allow_html=True,
                )
                if not is_message_duplicate(
                    ChatMessage(type="ai", content=response_text),
                    st.session_state.messages,
                ):
                    ai_message = ChatMessage(
                        type="ai",
                        content=response_text,
                        custom_data={"module_name": current_streaming_module},
                    )
                    st.session_state.messages.append(ai_message)
            st.rerun()

# Display chat history (filter out system messages unless debug mode is enabled)
for message in st.session_state.messages:
    render_message(message, show_system=st.session_state.show_system_messages)

# Handle module interrupt
if st.session_state.current_interrupt:
    interrupt: ModuleInterruptResponse = st.session_state.current_interrupt
    st.warning(
        f"**Module Interrupt from {interrupt.module_name}:**\n\n{interrupt.interrupt_value}"
    )
    
    with st.form("interrupt_response", clear_on_submit=True):
        interrupt_input = st.text_input("Your response:")
        submitted = st.form_submit_button("Send Response")

        if submitted and interrupt_input:
            if not st.session_state.client:
                st.error("Server not connected. Please check server status.")
            else:
                try:
                    # Stream response to interrupt
                    response_text = ""
                    current_streaming_module = "default"
                    received_complete_message = False
                    with st.chat_message("assistant"):
                        message_placeholder = st.empty()
                        
                        for chunk in st.session_state.client.respond_to_module_interrupt(
                            message=interrupt_input,
                            thread_id=st.session_state.thread_id,
                            user_id=st.session_state.user_id,
                            provider=st.session_state.selected_provider,
                            model=st.session_state.selected_model,
                            stream_tokens=True
                        ):
                            if isinstance(chunk, ModuleInterruptResponse):
                                # New interrupt detected
                                st.session_state.current_interrupt = chunk
                                st.rerun()
                            
                            # Process chunk using unified helper
                            response_text, current_streaming_module, received_complete_message = _process_stream_chunk(
                                chunk,
                                st.session_state.client,
                                current_streaming_module,
                                response_text,
                                received_complete_message,
                                message_placeholder,
                                st.session_state.messages
                            )
                        
                        # Finalize message if we streamed tokens only
                        if response_text and not received_complete_message:
                            color = MODULE_COLORS.get(current_streaming_module, MODULE_COLORS["default"])
                            badge_text = _render_module_badge(current_streaming_module)
                            message_placeholder.markdown(f"{badge_text}", unsafe_allow_html=True)
                            message_placeholder.markdown(
                                f'<div style="border-left: 4px solid {color}; padding-left: 10px; margin: 5px 0;">{response_text}</div>',
                                unsafe_allow_html=True,
                            )
                            # Add as AI message if not already added (avoid duplicates)
                            if not is_message_duplicate(
                                ChatMessage(type="ai", content=response_text),
                                st.session_state.messages
                            ):
                                ai_message = ChatMessage(
                                    type="ai",
                                    content=response_text,
                                    custom_data={"module_name": current_streaming_module}
                                )
                                st.session_state.messages.append(ai_message)
                    
                    st.session_state.current_interrupt = None
                    st.rerun()
                except AgentClientError as e:
                    st.error(f"Error responding to interrupt: {e}")

# Chat input
if not st.session_state.current_interrupt:
    if prompt := st.chat_input("Type your message here..."):
        if not st.session_state.client:
            st.error("Server not connected. Please check server status in the sidebar.")
        else:
            # Add user message
            user_message = ChatMessage(type="human", content=prompt)
            st.session_state.messages.append(user_message)
            render_message(user_message)

            # Stream response
            with st.chat_message("assistant"):
                message_placeholder = st.empty()
                response_text = ""
                received_complete_message = False
                current_streaming_module = "default"

                try:
                    for chunk in st.session_state.client.stream(
                        message=prompt,
                        thread_id=st.session_state.thread_id,
                        user_id=st.session_state.user_id,
                        provider=st.session_state.selected_provider,
                        model=st.session_state.selected_model,
                        stream_tokens=True
                    ):
                        if isinstance(chunk, ModuleInterruptResponse):
                            # Module interrupt detected
                            st.session_state.current_interrupt = chunk
                            st.rerun()
                        
                        # Process chunk using unified helper
                        response_text, current_streaming_module, received_complete_message = _process_stream_chunk(
                            chunk,
                            st.session_state.client,
                            current_streaming_module,
                            response_text,
                            received_complete_message,
                            message_placeholder,
                            st.session_state.messages
                        )

                    # Finalize message display
                    # Only add accumulated token text if we didn't receive a complete ChatMessage
                    if response_text and not received_complete_message:
                        # Apply final color styling
                        color = MODULE_COLORS.get(current_streaming_module, MODULE_COLORS["default"])
                        badge_text = _render_module_badge(current_streaming_module)
                        
                        # Display final message with color and badge
                        message_placeholder.markdown(f"{badge_text}", unsafe_allow_html=True)
                        message_placeholder.markdown(
                            f'<div style="border-left: 4px solid {color}; padding-left: 10px; margin: 5px 0;">{response_text}</div>',
                            unsafe_allow_html=True
                        )
                        
                        # Ensure message is in history (avoid duplicates)
                        if not is_message_duplicate(
                            ChatMessage(type="ai", content=response_text),
                            st.session_state.messages
                        ):
                            # Create AI message with module info for proper display in history
                            ai_message = ChatMessage(
                                type="ai", 
                                content=response_text,
                                custom_data={"module_name": current_streaming_module}
                            )
                            st.session_state.messages.append(ai_message)
                    elif not response_text and st.session_state.messages:
                        # If no response text accumulated, check for last message
                        last_msg = st.session_state.messages[-1]
                        if isinstance(last_msg, ChatMessage) and last_msg.type == "ai":
                            message_placeholder.markdown(last_msg.content)
                    
                    # After streaming completes, rerun to display any tool messages that were added
                    # This ensures all messages (including tool messages) are displayed in correct order
                    st.rerun()

                except AgentClientError as e:
                    st.error(f"Error communicating with server: {e}")
                    error_message = ChatMessage(
                        type="ai",
                        content=f"Error: {str(e)}"
                    )
                    st.session_state.messages.append(error_message)
                except Exception as e:
                    st.error(f"Unexpected error: {e}")
                    error_message = ChatMessage(
                        type="ai",
                        content=f"Unexpected error: {str(e)}"
                    )
                    st.session_state.messages.append(error_message)

