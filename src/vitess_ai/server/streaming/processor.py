"""
Main stream event processor for LangGraph streaming events.

This module provides the main StreamEventProcessor class that orchestrates
the processing of different stream modes.
"""

import json
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Optional

from langchain_core.messages import SystemMessage
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Overwrite
from langchain_core.runnables import RunnableConfig

from vitess_ai.core.log import get_logger
from vitess_ai.server.module_tracker import ModuleTracker
from vitess_ai.server.errors import StreamingError
from vitess_ai.server.utils import langchain_to_chat_message
from vitess_ai.server.streaming.handlers import (
    UpdatesStreamHandler,
    MessagesStreamHandler,
    CustomStreamHandler,
)
from vitess_ai.server.streaming.message_processor import MessageProcessor
from vitess_ai.server.streaming.deduplication import get_message_identifier

logger = get_logger(__name__)


class StreamEventProcessor:
    """Main processor for LangGraph stream events."""

    MODEL_NODES = {"model", "model_request"}
    
    def __init__(
        self,
        agent: CompiledStateGraph,
        config: RunnableConfig,
        run_id: str,
        user_input_message: str,
        default_module: str = "supervisor",
        enable_task_lifecycle: bool = False,
    ):
        self.agent = agent
        self.config = config
        self.run_id = run_id
        self.user_input_message = user_input_message
        self.default_module = default_module
        self.enable_task_lifecycle = enable_task_lifecycle
        
        # Track already-streamed messages to prevent duplicates
        # Uses message IDs (from LangChain BaseMessage.id) or hash fallback
        self._streamed_message_ids: set[str] = set()

        # Advanced mode lifecycle tracking (delegated subagent task tool calls)
        self._active_subagents: dict[str, dict[str, Any]] = {}
        self._pregel_to_subagent: dict[str, str] = {}
        self._task_tool_metadata: dict[str, dict[str, Any]] = {}
        self._sequence_counter: int = 0
        
        # Initialize handlers
        self.updates_handler = UpdatesStreamHandler()
        self.message_processor = MessageProcessor(
            agent,
            config,
            run_id,
            user_input_message,
            self._streamed_message_ids,
            default_module=default_module,
            delegated_task_metadata=self._task_tool_metadata,
        )
        
        # Track current module
        self.current_module: Optional[str] = None
    
    def _normalize_namespace(self, raw_namespace: Any) -> tuple[str, ...]:
        """Normalize stream namespace into tuple[str, ...]."""
        if raw_namespace is None:
            return tuple()
        if isinstance(raw_namespace, (tuple, list)):
            return tuple(str(part) for part in raw_namespace if part is not None)
        if isinstance(raw_namespace, str):
            return (raw_namespace,) if raw_namespace else tuple()
        return (str(raw_namespace),)

    def _node_path_from_namespace(self, raw_namespace: Any, namespace: tuple[str, ...]) -> Optional[str]:
        """
        Derive a node_path string for module tracking fallback.

        Keeps simulator behavior unchanged (raw string namespace remains node_path),
        while normalizing tuple/list namespace from deep-agent subgraphs.
        """
        if isinstance(raw_namespace, str):
            return raw_namespace
        if namespace:
            candidate = namespace[-1]
            if candidate and not candidate.startswith("tools:"):
                return candidate
        return None

    def _parse_stream_event(
        self, stream_event: Any
    ) -> tuple[str, Any, Optional[str], tuple[str, ...]]:
        """
        Parse a stream event into (stream_mode, event, node_path, namespace).
        
        Args:
            stream_event: The raw stream event from LangGraph
            
        Returns:
            Tuple of (stream_mode, event, node_path, namespace)
        """
        if not isinstance(stream_event, tuple):
            raise StreamingError(f"Unexpected stream event type: {type(stream_event)}")
        
        if len(stream_event) == 3:
            # With subgraphs=True: (namespace, stream_mode, event)
            raw_namespace, stream_mode, event = stream_event
            namespace = self._normalize_namespace(raw_namespace)
            node_path = self._node_path_from_namespace(raw_namespace, namespace)
            return stream_mode, event, node_path, namespace
        if len(stream_event) == 2:
            # Without subgraphs: (stream_mode, event)
            stream_mode, event = stream_event
            return stream_mode, event, None, tuple()
        raise StreamingError(f"Unexpected stream event tuple shape: len={len(stream_event)}")

    def _extract_messages(self, node_updates: Any) -> list[Any]:
        """Extract normalized message list from a node update payload."""
        updates = node_updates or {}
        raw_messages = updates.get("messages", []) if isinstance(updates, dict) else []
        if isinstance(raw_messages, Overwrite):
            return list(raw_messages.value) if raw_messages.value else []
        if isinstance(raw_messages, (list, tuple)):
            return list(raw_messages)
        return []

    def _next_sequence(self) -> int:
        """Return next monotonic sequence number for lifecycle events."""
        self._sequence_counter += 1
        return self._sequence_counter

    def _build_lifecycle_sse(
        self,
        phase: str,
        task_id: str,
        status: str,
        subagent_type: str,
        description: str,
        pregel_id: str | None = None,
        result_preview: str | None = None,
    ) -> str:
        """Build SSE payload for task lifecycle event."""
        payload = {
            "type": "task_lifecycle",
            "content": {
                "run_id": self.run_id,
                "sequence": self._next_sequence(),
                "phase": phase,
                "task_id": task_id,
                "subagent_type": subagent_type,
                "description": description,
                "status": status,
                "pregel_id": pregel_id,
                "result_preview": result_preview,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }
        return f"data: {json.dumps(payload)}\n\n"

    def _extract_content_preview(self, content: Any, max_len: int = 120) -> str:
        """Generate a short result preview string from tool content."""
        if content is None:
            return ""
        text = str(content).strip()
        if len(text) <= max_len:
            return text
        return f"{text[:max_len]}..."

    def _process_task_lifecycle(
        self,
        updates_event: Any,
        namespace: tuple[str, ...],
    ) -> list[str]:
        """
        Extract delegated-subagent lifecycle events from updates stream chunks.

        Lifecycle phases:
        - pending: root model/model_request emits task tool call
        - running: subgraph namespace starts with tools:<pregel_id>
        - complete: root tools node emits ToolMessage with matching tool_call_id
        """
        if not self.enable_task_lifecycle or not isinstance(updates_event, dict):
            return []

        lifecycle_events: list[str] = []
        is_root = len(namespace) == 0

        # Phase 1: pending
        for node_name, node_updates in updates_event.items():
            messages = self._extract_messages(node_updates)
            if not messages:
                continue

            if is_root and node_name in self.MODEL_NODES:
                for msg in messages:
                    for tool_call in (getattr(msg, "tool_calls", None) or []):
                        if tool_call.get("name") != "task":
                            continue
                        task_id = tool_call.get("id")
                        if not task_id or task_id in self._active_subagents:
                            continue

                        args = tool_call.get("args", {}) or {}
                        subagent_type = str(args.get("subagent_type") or "unknown")
                        description = str(args.get("description") or "")[:80]
                        self._active_subagents[task_id] = {
                            "subagent_type": subagent_type,
                            "description": description,
                            "status": "pending",
                            "pregel_id": None,
                        }
                        self._task_tool_metadata[task_id] = {
                            "tool_kind": "delegated_subagent_result",
                            "subagent_type": subagent_type,
                            "delegated_task_id": task_id,
                            "display_mode": "hidden_by_default",
                            "status": "pending",
                            "description": description,
                            "pregel_id": None,
                        }
                        logger.debug(
                            "Task lifecycle PENDING task_id=%s subagent=%s",
                            task_id,
                            subagent_type,
                        )
                        lifecycle_events.append(
                            self._build_lifecycle_sse(
                                phase="pending",
                                task_id=task_id,
                                status="pending",
                                subagent_type=subagent_type,
                                description=description,
                            )
                        )

            # Phase 3: complete
            if is_root and node_name == "tools":
                for msg in messages:
                    if getattr(msg, "type", None) != "tool":
                        continue
                    task_id = getattr(msg, "tool_call_id", None)
                    if not task_id or task_id not in self._active_subagents:
                        continue
                    state = self._active_subagents[task_id]
                    if state.get("status") == "complete":
                        continue
                    state["status"] = "complete"
                    result_preview = self._extract_content_preview(getattr(msg, "content", ""))
                    tool_meta = self._task_tool_metadata.get(task_id)
                    if tool_meta is not None:
                        tool_meta["status"] = "complete"
                        tool_meta["result_preview"] = result_preview or None
                    logger.debug(
                        "Task lifecycle COMPLETE task_id=%s pregel_id=%s",
                        task_id,
                        state.get("pregel_id"),
                    )
                    lifecycle_events.append(
                        self._build_lifecycle_sse(
                            phase="complete",
                            task_id=task_id,
                            status="complete",
                            subagent_type=str(state.get("subagent_type") or "unknown"),
                            description=str(state.get("description") or ""),
                            pregel_id=state.get("pregel_id"),
                            result_preview=result_preview or None,
                        )
                    )

        # Phase 2: running
        if namespace and namespace[0].startswith("tools:"):
            pregel_id = namespace[0].split(":", 1)[1]
            if pregel_id and pregel_id not in self._pregel_to_subagent:
                pending_task_id = next(
                    (
                        sid
                        for sid, sub_state in self._active_subagents.items()
                        if sub_state.get("status") == "pending"
                    ),
                    None,
                )
                if pending_task_id:
                    self._pregel_to_subagent[pregel_id] = pending_task_id
                    state = self._active_subagents[pending_task_id]
                    state["status"] = "running"
                    state["pregel_id"] = pregel_id
                    tool_meta = self._task_tool_metadata.get(pending_task_id)
                    if tool_meta is not None:
                        tool_meta["status"] = "running"
                        tool_meta["pregel_id"] = pregel_id
                    logger.debug(
                        "Task lifecycle RUNNING task_id=%s pregel_id=%s",
                        pending_task_id,
                        pregel_id,
                    )
                    lifecycle_events.append(
                        self._build_lifecycle_sse(
                            phase="running",
                            task_id=pending_task_id,
                            status="running",
                            subagent_type=str(state.get("subagent_type") or "unknown"),
                            description=str(state.get("description") or ""),
                            pregel_id=pregel_id,
                        )
                    )

        return lifecycle_events
    
    async def _update_current_module(self, node_path: Optional[str]) -> None:
        """Update the current module from state or node path."""
        self.current_module = await ModuleTracker.get_current_module(
            self.agent,
            self.config,
            node_path
        )
    
    async def _initialize_streamed_message_ids(self) -> None:
        """
        Initialize streamed_message_ids by reading existing messages from state.
        
        This prevents duplicate messages from being streamed when the graph resumes
        from a checkpoint. All existing messages in the state are marked as already
        streamed, so only new messages will be sent to the client.
        
        Handles edge cases:
        - State doesn't exist yet (first invocation) - no messages to initialize
        - State exists but has no messages - empty set
        - Errors accessing state - logs warning and continues with empty set
        """
        try:
            # Get current state from the agent
            state: Any = await self.agent.aget_state(config=self.config)
            
            # Check if state exists and has values
            if not state or not hasattr(state, 'values') or not state.values:
                logger.debug("No existing state found, starting with empty streamed_message_ids")
                return
            
            # Extract messages from state
            existing_messages = state.values.get('messages', [])
            
            if not existing_messages:
                logger.debug("State exists but has no messages, starting with empty streamed_message_ids")
                return
            
            # Get current module from state for consistent module detection
            current_module_from_state = state.values.get('current_module')
            
            # Generate IDs for all existing messages
            initialized_count = 0
            for message in existing_messages:
                try:
                    # Skip SystemMessage - they shouldn't be streamed anyway
                    if isinstance(message, SystemMessage):
                        continue
                    
                    # Determine module for this message
                    # Use state's current_module if available, otherwise try to extract from message metadata
                    module_for_message = current_module_from_state
                    if not module_for_message and hasattr(message, 'additional_kwargs'):
                        module_for_message = message.additional_kwargs.get('module_name')
                    if not module_for_message:
                        module_for_message = self.default_module
                    
                    # Convert to ChatMessage to get consistent format
                    chat_message = langchain_to_chat_message(
                        message, 
                        module_name=module_for_message
                    )
                    
                    # Generate message ID using same logic as MessageProcessor
                    message_id = get_message_identifier(
                        message,
                        chat_message,
                        module_for_message,
                        run_id=self.run_id
                    )
                    
                    # Add to streamed_message_ids
                    self._streamed_message_ids.add(message_id)
                    initialized_count += 1
                    
                except Exception as e:
                    # Log but continue processing other messages
                    logger.warning(f"Error initializing message ID for message: {e}", exc_info=True)
            
            logger.debug(f"Initialized streamed_message_ids with {initialized_count} existing messages")
            
        except Exception as e:
            # Log error but don't fail - we can still process new messages
            # This ensures the system is resilient to state access issues
            logger.warning(f"Failed to initialize streamed_message_ids from state: {e}", exc_info=True)
            # Continue with empty set - new messages will still be processed
    
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
            stream_mode, event, node_path, namespace = self._parse_stream_event(stream_event)
            
            # Update current module
            await self._update_current_module(node_path)
            
            # Process based on stream mode
            if stream_mode == "updates":
                if self.enable_task_lifecycle:
                    try:
                        for lifecycle_sse in self._process_task_lifecycle(event, namespace):
                            yield lifecycle_sse
                    except Exception as lifecycle_error:
                        logger.warning(
                            "Lifecycle parsing failed; continuing normal streaming: %s",
                            lifecycle_error,
                            exc_info=True,
                        )

                messages = self.updates_handler.process_updates(
                    event
                )
                async for sse_string in self.message_processor.process_and_yield_messages(
                    messages,
                    node_path,
                    self.current_module
                ):
                    yield sse_string
            
            elif stream_mode == "messages":
                handler = MessagesStreamHandler(
                    self.current_module,
                    default_module=self.default_module,
                )
                token_data = handler.process_messages(event)
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
