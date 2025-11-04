"""
Chat interface for Streamlit app.

This module provides functions for handling chat interactions, streaming responses,
interrupt handling, and message display.
"""
import streamlit as st
from vitess_ai.clients.client import AgentClient, AgentClientError
from vitess_ai.schema.server import ChatMessage, ModuleInterruptResponse
from ui_components import (
    render_header_with_logo,
    render_message,
    render_module_badge,
    render_streaming_token,
    MODULE_COLORS
)


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


def process_stream_chunk(
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
                render_streaming_token(
                    current_streaming_module,
                    response_text,
                    message_placeholder
                )
        
        return response_text, current_streaming_module, received_complete_message
    
    return response_text, current_streaming_module, received_complete_message


def render_chat_interface() -> None:
    """Render the main chat interface including header, message history, and input."""
    # Render header
    render_header_with_logo()
    
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
                    response_text, current_streaming_module, received_complete_message = process_stream_chunk(
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
                    badge_text = render_module_badge(current_streaming_module)
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
                                response_text, current_streaming_module, received_complete_message = process_stream_chunk(
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
                                badge_text = render_module_badge(current_streaming_module)
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
                            response_text, current_streaming_module, received_complete_message = process_stream_chunk(
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
                            badge_text = render_module_badge(current_streaming_module)
                            
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

