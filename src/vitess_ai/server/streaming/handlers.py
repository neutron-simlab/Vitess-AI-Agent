"""
Stream handlers for processing LangGraph streaming events.

This module provides handlers for different stream modes (updates, messages, custom)
to process and convert LangGraph streaming events into chat messages.
"""

from typing import Any, Optional

from langchain_core.messages import AIMessageChunk, BaseMessage
from langgraph.types import Overwrite

from vitess_ai.server.module_tracker import ModuleTracker
from vitess_ai.server.utils import (
    convert_message_content_to_string,
    remove_tool_calls,
)
import json


class UpdatesStreamHandler:
    """Handler for stream_mode='updates' events."""
    
    def process_updates(
        self,
        event: dict[str, Any],
    ) -> list[BaseMessage]:
        """
        Process updates stream events and extract messages.
        
        Args:
            event: The updates event dictionary
            
        Returns:
            List of messages extracted from updates
        """
        new_messages = []
        
        for node, updates in event.items():
            # Extract messages from updates
            updates = updates or {}
            raw_messages = updates.get("messages", [])

            # LangGraph can send Overwrite(value=[...]) for reducer channels; unwrap to get the list
            if isinstance(raw_messages, Overwrite):
                update_messages = list(raw_messages.value) if raw_messages.value else []
            elif isinstance(raw_messages, (list, tuple)):
                update_messages = raw_messages
            else:
                update_messages = []

            # Filter out internal supervisor nodes that don't emit user-facing messages
            if ModuleTracker.is_internal_node(node):
                update_messages = []

            new_messages.extend(update_messages)
        
        return new_messages


class MessagesStreamHandler:
    """Handler for stream_mode='messages' token streaming."""
    
    def __init__(
        self,
        current_module: Optional[str],
        default_module: str = "supervisor",
    ):
        self.current_module = current_module
        self.default_module = default_module
    
    def process_messages(
        self,
        event: tuple[BaseMessage, dict[str, Any]],
    ) -> Optional[str]:
        """
        Process messages stream events and yield token chunks.
        
        Args:
            event: Tuple of (message, metadata)
            
        Returns:
            SSE data string with token chunk, or None if should be skipped
        """
        msg, metadata = event
        
        # Skip messages with skip_stream tag
        if "skip_stream" in metadata.get("tags", []):
            return None
        
        # Only process AIMessageChunk for token streaming
        if not isinstance(msg, AIMessageChunk):
            return None
        
        content = remove_tool_calls(msg.content)
        if not content:
            return None
        
        # Include module info in token type for color coding
        token_module = self.current_module if self.current_module else self.default_module
        token_type = f"token_{token_module}"
        
        token_content = convert_message_content_to_string(content)
        return f"data: {json.dumps({'type': token_type, 'content': token_content})}\n\n"


class CustomStreamHandler:
    """Handler for stream_mode='custom' events."""
    
    @staticmethod
    def process_custom(event: Any) -> list[BaseMessage]:
        """
        Process custom stream events.
        
        Args:
            event: The custom event data
            
        Returns:
            List containing the custom event as a message
        """
        return [event]
