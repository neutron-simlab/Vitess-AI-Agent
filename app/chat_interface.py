"""
Chat interface for Streamlit app.

This module provides functions for handling chat interactions, streaming responses,
and message display.
"""
import streamlit as st
from vitess_ai.clients.client import AgentClient, AgentClientError
from vitess_ai.schema.server import ChatMessage
from ui_components import (
    apply_task_lifecycle_event,
    render_header_with_logo,
    render_message,
    render_task_lifecycle_stream,
    render_streaming_token,
    finalize_streaming_message,
)


def _initialize_task_lifecycle_state() -> None:
    """Initialize per-turn delegated task lifecycle state in Streamlit session."""
    if "current_turn_tasks" not in st.session_state:
        st.session_state.current_turn_tasks = {}


def _reset_task_lifecycle_state(task_stream_placeholder=None) -> None:
    """Reset delegated task lifecycle state for a new user turn."""
    st.session_state.current_turn_tasks = {}
    if task_stream_placeholder is not None:
        render_task_lifecycle_stream(
            st.session_state.current_turn_tasks,
            stream_placeholder=task_stream_placeholder,
        )


def process_stream_chunk(
    chunk,
    client: AgentClient,
    current_streaming_module: str,
    response_text: str,
    received_complete_message: bool,
    message_placeholder,
    messages: list,
    task_stream_placeholder=None,
) -> tuple[str, str, bool]:
    """
    Process a single chunk from the stream and update UI.
    
    Args:
        chunk: Stream chunk (ChatMessage, token dict, etc.)
        client: AgentClient instance for helper methods
        current_streaming_module: Current module name
        response_text: Accumulated response text
        received_complete_message: Whether complete message was received
        message_placeholder: Streamlit placeholder
        messages: Message history list
        task_stream_placeholder: Optional inline lifecycle placeholder
        
    Returns:
        Tuple of (updated_response_text, updated_module, updated_complete_flag)
    """
    if client.is_task_lifecycle_event(chunk):
        lifecycle_content = client.get_task_lifecycle_content(chunk) or {}
        st.session_state.current_turn_tasks = apply_task_lifecycle_event(
            st.session_state.current_turn_tasks,
            lifecycle_content,
        )
        if task_stream_placeholder is not None:
            render_task_lifecycle_stream(
                st.session_state.current_turn_tasks,
                stream_placeholder=task_stream_placeholder,
            )
        return response_text, current_streaming_module, received_complete_message

    if isinstance(chunk, ChatMessage):
        # Complete message received
        content_str = str(chunk.content) if chunk.content is not None else ""
        # Skip stray 'Start' messages
        if content_str.strip().lower() == "start":
            return response_text, current_streaming_module, received_complete_message
        
        received_complete_message = True
        # Backend handles deduplication, so we can always append
        messages.append(chunk)
        
        if chunk.type == "ai":
            # Extract module name from custom_data if available
            custom_data = chunk.custom_data or {}
            module_name = custom_data.get("module_name", current_streaming_module)
            # Render final content with JSON/markdown logic (same as history)
            finalize_streaming_message(
                message_placeholder,
                chunk.content,
                module_name,
                custom_data=chunk.custom_data
            )
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

    _initialize_task_lifecycle_state()
    is_high_throughput_mode = st.session_state.get("selected_agent_id") == "high_throughput"
    
    # Auto-trigger initial welcome from server when connected and history is empty
    if (
        st.session_state.server_connected
        and st.session_state.client
        and not st.session_state.messages
        and not st.session_state.get("welcome_initialized", False)
    ):
        st.session_state.welcome_initialized = True
        with st.chat_message("assistant"):
            lifecycle_placeholder = st.empty() if is_high_throughput_mode else None
            _reset_task_lifecycle_state(task_stream_placeholder=lifecycle_placeholder)
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
                    # Process chunk using unified helper
                    response_text, current_streaming_module, received_complete_message = process_stream_chunk(
                        chunk,
                        st.session_state.client,
                        current_streaming_module,
                        response_text,
                        received_complete_message,
                        message_placeholder,
                        st.session_state.messages,
                        task_stream_placeholder=lifecycle_placeholder,
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
                    custom_data = {"module_name": current_streaming_module}
                    # Render final content with JSON/markdown logic (same as history)
                    finalize_streaming_message(
                        message_placeholder,
                        response_text,
                        current_streaming_module,
                        custom_data=custom_data
                    )
                    # Backend handles deduplication, so we can always append
                    ai_message = ChatMessage(
                        type="ai",
                        content=response_text,
                        custom_data=custom_data,
                    )
                    st.session_state.messages.append(ai_message)
                st.rerun()

    # Display chat history (filter out system messages unless debug mode is enabled)
    for message in st.session_state.messages:
        render_message(message, show_system=st.session_state.show_system_messages)

    # Chat input
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
                lifecycle_placeholder = st.empty() if is_high_throughput_mode else None
                _reset_task_lifecycle_state(task_stream_placeholder=lifecycle_placeholder)
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
                        # Process chunk using unified helper
                        response_text, current_streaming_module, received_complete_message = process_stream_chunk(
                            chunk,
                            st.session_state.client,
                            current_streaming_module,
                            response_text,
                            received_complete_message,
                            message_placeholder,
                            st.session_state.messages,
                            task_stream_placeholder=lifecycle_placeholder,
                        )

                    # Finalize message display
                    # Only add accumulated token text if we didn't receive a complete ChatMessage
                    if response_text and not received_complete_message:
                        custom_data = {"module_name": current_streaming_module}
                        # Render final content with JSON/markdown logic (same as history)
                        finalize_streaming_message(
                            message_placeholder,
                            response_text,
                            current_streaming_module,
                            custom_data=custom_data
                        )
                        # Backend handles deduplication, so we can always append
                        ai_message = ChatMessage(
                            type="ai",
                            content=response_text,
                            custom_data=custom_data
                        )
                        st.session_state.messages.append(ai_message)
                    elif not response_text and st.session_state.messages:
                        # If no response text accumulated, check for last message
                        last_msg = st.session_state.messages[-1]
                        if isinstance(last_msg, ChatMessage) and last_msg.type == "ai":
                            # Render using same logic as history for consistency
                            last_custom_data = last_msg.custom_data or {}
                            module_name = last_custom_data.get("module_name", "default")
                            finalize_streaming_message(
                                message_placeholder,
                                last_msg.content,
                                module_name,
                                custom_data=last_msg.custom_data
                            )

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
