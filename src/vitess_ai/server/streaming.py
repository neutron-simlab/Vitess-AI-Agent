"""
Stream handlers for processing LangGraph streaming events.

This module provides handlers for different stream modes (updates, messages, custom)
to process and convert LangGraph streaming events into chat messages.
"""

import inspect
import json
import logging
from typing import Any, AsyncGenerator, Optional
from collections.abc import AsyncGenerator as AsyncGeneratorType

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langgraph.types import Interrupt
from langgraph.graph.state import CompiledStateGraph
from langchain_core.runnables import RunnableConfig

from vitess_ai.server.utils import (
    convert_message_content_to_string,
    langchain_to_chat_message,
    remove_tool_calls,
)
from vitess_ai.server.module_tracker import ModuleTracker
from vitess_ai.server.errors import StreamingError, MessageProcessingError

logger = logging.getLogger(__name__)


class UpdatesStreamHandler:
    """Handler for stream_mode='updates' events."""
    
    def __init__(
        self,
        agent: CompiledStateGraph,
        config: RunnableConfig,
        run_id: str,
        user_input_message: str
    ):
        self.agent = agent
        self.config = config
        self.run_id = run_id
        self.user_input_message = user_input_message
    
    def process_updates(
        self,
        event: dict[str, Any],
        node_path: Optional[str],
        current_module: Optional[str]
    ) -> list[BaseMessage]:
        """
        Process updates stream events and extract messages.
        
        Args:
            event: The updates event dictionary
            node_path: Optional node path for module detection
            current_module: Current module from state
            
        Returns:
            List of messages extracted from updates
        """
        new_messages = []
        
        for node, updates in event.items():
            # Handle interrupts
            if node == "__interrupt__":
                interrupt: Interrupt
                for interrupt in updates:
                    interrupt_msg = AIMessage(content=interrupt.value)
                    new_messages.append(interrupt_msg)
                continue
            
            # Extract messages from updates
            updates = updates or {}
            update_messages = updates.get("messages", [])
            
            # Filter out internal supervisor nodes that don't emit user-facing messages
            if ModuleTracker.is_internal_node(node):
                update_messages = []
            
            new_messages.extend(update_messages)
        
        return new_messages


class MessagesStreamHandler:
    """Handler for stream_mode='messages' token streaming."""
    
    def __init__(
        self,
        run_id: str,
        current_module: Optional[str]
    ):
        self.run_id = run_id
        self.current_module = current_module
    
    def process_messages(
        self,
        event: tuple[BaseMessage, dict[str, Any]],
        user_input_message: str
    ) -> Optional[str]:
        """
        Process messages stream events and yield token chunks.
        
        Args:
            event: Tuple of (message, metadata)
            user_input_message: Original user input message to filter duplicates
            
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
        token_module = self.current_module if self.current_module else 'supervisor'
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


class MessageProcessor:
    """Processes and converts messages to chat format for streaming."""
    
    def __init__(
        self,
        agent: CompiledStateGraph,
        config: RunnableConfig,
        run_id: str,
        user_input_message: str
    ):
        self.agent = agent
        self.config = config
        self.run_id = run_id
        self.user_input_message = user_input_message
    
    def _create_ai_message(self, parts: dict) -> AIMessage:
        """Create an AIMessage from parts dictionary."""
        sig = inspect.signature(AIMessage)
        valid_keys = set(sig.parameters)
        filtered = {k: v for k, v in parts.items() if k in valid_keys}
        return AIMessage(**filtered)
    
    def _process_message_parts(self, messages: list[BaseMessage | tuple]) -> list[BaseMessage]:
        """
        Process messages that may contain tuples (field_name, field_value).
        
        LangGraph streaming may emit tuples: (field_name, field_value)
        e.g. ('content', <str>), ('tool_calls', [ToolCall,...]), etc.
        We accumulate these into complete messages.
        
        Args:
            messages: List of messages that may contain tuples
            
        Returns:
            List of processed BaseMessage objects
        """
        processed_messages = []
        current_message: dict[str, Any] = {}
        
        for message in messages:
            if isinstance(message, tuple):
                key, value = message
                current_message[key] = value
            else:
                # Complete message - add any accumulated parts first
                if current_message:
                    processed_messages.append(self._create_ai_message(current_message))
                    current_message = {}
                processed_messages.append(message)
        
        # Add any remaining message parts
        if current_message:
            processed_messages.append(self._create_ai_message(current_message))
        
        return processed_messages
    
    async def process_and_yield_messages(
        self,
        messages: list[BaseMessage],
        node_path: Optional[str],
        current_module: Optional[str]
    ) -> AsyncGenerator[str, None]:
        """
        Process messages and yield SSE-formatted strings.
        
        Args:
            messages: List of messages to process
            node_path: Optional node path for module detection
            current_module: Current module from state
            
        Yields:
            SSE-formatted data strings
        """
        # Process message parts (handle tuple-based streaming)
        processed_messages = self._process_message_parts(messages)
        
        for message in processed_messages:
            try:
                # Skip SystemMessage - they should remain in state but not be streamed
                if isinstance(message, SystemMessage):
                    continue
                
                # Determine module for this message
                module_for_message = ModuleTracker.get_module_for_message(
                    current_module,
                    node_path
                )
                
                # Convert to ChatMessage
                chat_message = langchain_to_chat_message(message, module_name=module_for_message)
                chat_message.run_id = str(self.run_id)
                
                # Filter out duplicate user input messages
                if chat_message.type == "human" and chat_message.content == self.user_input_message:
                    continue
                
                # Skip system messages
                if chat_message.type == "system":
                    continue
                
                # Yield SSE-formatted message
                yield f"data: {json.dumps({'type': 'message', 'content': chat_message.model_dump()})}\n\n"
                
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)
                error_msg = MessageProcessingError(
                    "Failed to process message",
                    message_type=type(message).__name__,
                    details={"error": str(e)}
                )
                yield f"data: {json.dumps({'type': 'error', 'content': error_msg.message})}\n\n"


class StreamEventProcessor:
    """Main processor for LangGraph stream events."""
    
    def __init__(
        self,
        agent: CompiledStateGraph,
        config: RunnableConfig,
        run_id: str,
        user_input_message: str
    ):
        self.agent = agent
        self.config = config
        self.run_id = run_id
        self.user_input_message = user_input_message
        
        # Initialize handlers
        self.updates_handler = UpdatesStreamHandler(agent, config, run_id, user_input_message)
        self.message_processor = MessageProcessor(agent, config, run_id, user_input_message)
        
        # Track current module
        self.current_module: Optional[str] = None
    
    def _parse_stream_event(self, stream_event: Any) -> tuple[str, Any, Optional[str]]:
        """
        Parse a stream event into (stream_mode, event, node_path).
        
        Args:
            stream_event: The raw stream event from LangGraph
            
        Returns:
            Tuple of (stream_mode, event, node_path)
        """
        if not isinstance(stream_event, tuple):
            raise StreamingError(f"Unexpected stream event type: {type(stream_event)}")
        
        if len(stream_event) == 3:
            # With subgraphs=True: (node_path, stream_mode, event)
            node_path, stream_mode, event = stream_event
            return stream_mode, event, node_path
        else:
            # Without subgraphs: (stream_mode, event)
            stream_mode, event = stream_event
            return stream_mode, event, None
    
    async def _update_current_module(self, node_path: Optional[str]) -> None:
        """Update the current module from state or node path."""
        self.current_module = await ModuleTracker.get_current_module(
            self.agent,
            self.config,
            node_path
        )
    
    async def process_event(
        self,
        stream_event: Any
    ) -> AsyncGenerator[str, None]:
        """
        Process a single stream event and yield SSE-formatted strings.
        
        Args:
            stream_event: The raw stream event from LangGraph
            
        Yields:
            SSE-formatted data strings
        """
        try:
            stream_mode, event, node_path = self._parse_stream_event(stream_event)
            
            # Update current module
            await self._update_current_module(node_path)
            
            # Process based on stream mode
            if stream_mode == "updates":
                messages = self.updates_handler.process_updates(
                    event,
                    node_path,
                    self.current_module
                )
                async for sse_string in self.message_processor.process_and_yield_messages(
                    messages,
                    node_path,
                    self.current_module
                ):
                    yield sse_string
            
            elif stream_mode == "messages":
                handler = MessagesStreamHandler(self.run_id, self.current_module)
                token_data = handler.process_messages(event, self.user_input_message)
                if token_data:
                    yield token_data
            
            elif stream_mode == "custom":
                messages = CustomStreamHandler.process_custom(event)
                async for sse_string in self.message_processor.process_and_yield_messages(
                    messages,
                    node_path,
                    self.current_module
                ):
                    yield sse_string
            
        except Exception as e:
            logger.error(f"Error processing stream event: {e}", exc_info=True)
            error = StreamingError(
                "Failed to process stream event",
                stream_mode=getattr(e, 'stream_mode', None),
                details={"error": str(e)}
            )
            yield f"data: {json.dumps({'type': 'error', 'content': error.message})}\n\n"

