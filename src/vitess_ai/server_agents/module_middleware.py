"""
Module Middleware - Message Filtering for Module Agents

This module provides middleware for filtering messages so that each module agent
only sees its own conversation context, maintaining independence between modules.
"""

import logging
import os
from typing import Any, Optional, Set
from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage, ToolMessage
from langgraph.runtime import Runtime

from vitess_ai.core.log import get_logger


class MessageFilterMiddleware(AgentMiddleware):
    """
    Middleware that filters messages to only include those relevant to a specific module.
    
    This ensures that module agents remain independent and only see their own
    conversation context, improving their ability to understand and respond appropriately.
    
    Message filtering logic:
    - Always includes SystemMessages (thread_id context, etc.)
    - Includes messages explicitly tagged with module_name in additional_kwargs
    - Includes the module's welcome message
    - Includes user messages that occur after the module's welcome message
    - Excludes messages from other modules
    """
    
    def __init__(self, module_name: str):
        """
        Initialize the message filter middleware.
        
        Args:
            module_name: The name of the module this middleware filters for
        """
        self.module_name = module_name
        self.logger = get_logger(f"vitess_ai.server_agents.module_middleware.{module_name}", level=logging.DEBUG)
    
    def _filter_module_messages(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        """
        Filter messages to only include those relevant to this module.
        
        This improved filtering logic:
        1. Always includes SystemMessages
        2. Finds the module's welcome message (tagged with module_name)
        3. Includes all messages after the welcome until hitting another module's message
        4. Includes ToolMessages that are responses to this module's tool calls
        5. Tracks tool_call_ids from this module's AIMessages to include their ToolMessages
        
        Args:
            messages: List of all messages in the conversation
            
        Returns:
            Filtered list of messages relevant to this module
        """
        filtered = []
        welcome_found = False
        in_module_context = False
        module_tool_call_ids: Set[str] = set()
        
        for msg in messages:
            # Always include system messages (thread_id context, etc.)
            if isinstance(msg, SystemMessage):
                filtered.append(msg)
                self.logger.debug(f"[FILTER] Including SystemMessage: {str(msg.content)[:50]}...")
                continue
            
            # Check if message is explicitly tagged with a module_name
            msg_module = None
            if hasattr(msg, 'additional_kwargs') and msg.additional_kwargs:
                msg_module = msg.additional_kwargs.get('module_name')
            
            # If message is explicitly tagged with this module, include it
            if msg_module == self.module_name:
                filtered.append(msg)
                welcome_found = True
                in_module_context = True
                
                # Check if this is a welcome message
                if isinstance(msg, AIMessage) and hasattr(msg, 'content'):
                    content_lower = str(msg.content).lower()
                    if 'welcome' in content_lower or self.module_name in content_lower:
                        self.logger.debug(f"[FILTER] Found welcome message for {self.module_name}")
                
                # Track tool_call_ids from this module's AIMessages
                if isinstance(msg, AIMessage):
                    # Handle different formats of tool_calls
                    tool_calls = getattr(msg, 'tool_calls', None) or []
                    for tool_call in tool_calls:
                        # Handle both dict and object formats
                        if isinstance(tool_call, dict):
                            tool_call_id = tool_call.get('id')
                        else:
                            tool_call_id = getattr(tool_call, 'id', None)
                        if tool_call_id:
                            module_tool_call_ids.add(str(tool_call_id))
                            self.logger.debug(f"[FILTER] Tracking tool_call_id {tool_call_id} for module {self.module_name}")
                
                self.logger.debug(f"[FILTER] Including module-tagged message: {type(msg).__name__}")
                continue
            
            # Exclude messages explicitly tagged with other modules
            if msg_module and msg_module != self.module_name:
                # This message belongs to another module - exclude it
                # But don't reset in_module_context if we're already in a conversation chain
                # Only reset if this is a clear boundary (like a supervisor message or another module's welcome)
                if isinstance(msg, AIMessage):
                    # Another module's AIMessage - this is a clear boundary
                    in_module_context = False
                    welcome_found = False
                    self.logger.debug(f"[FILTER] Excluding message from other module: {msg_module}, resetting context")
                else:
                    # Other module's non-AI message - exclude but keep context for tool messages
                    self.logger.debug(f"[FILTER] Excluding message from other module: {msg_module}")
                continue
            
            # Handle ToolMessages - include if they're responses to this module's tool calls
            if isinstance(msg, ToolMessage):
                tool_call_id = getattr(msg, 'tool_call_id', None)
                tool_call_id_str = str(tool_call_id) if tool_call_id else None
                if tool_call_id_str and tool_call_id_str in module_tool_call_ids:
                    # This ToolMessage is a response to this module's tool call
                    filtered.append(msg)
                    in_module_context = True  # Keep context active
                    self.logger.debug(f"[FILTER] Including ToolMessage for tool_call_id {tool_call_id}")
                    continue
                elif in_module_context:
                    # In module context but tool_call_id not tracked - might be from a previous iteration
                    # Include it to maintain conversation flow (important for react-agent to see tool results)
                    filtered.append(msg)
                    self.logger.debug(f"[FILTER] Including ToolMessage in module context (tool_call_id={tool_call_id}, not in tracked set)")
                    continue
                else:
                    # Not in module context and not a tracked tool call - exclude
                    self.logger.debug(f"[FILTER] Excluding ToolMessage outside module context (tool_call_id={tool_call_id})")
                    continue
            
            # For other messages (AIMessage, HumanMessage) without explicit module tags:
            # If we're in this module's context (found welcome), include them
            # This handles user messages and AI responses that are part of this module's conversation
            if in_module_context:
                filtered.append(msg)
                
                # Track tool_call_ids from AIMessages in this context
                if isinstance(msg, AIMessage):
                    tool_calls = getattr(msg, 'tool_calls', None) or []
                    for tool_call in tool_calls:
                        # Handle both dict and object formats
                        if isinstance(tool_call, dict):
                            tool_call_id = tool_call.get('id')
                        else:
                            tool_call_id = getattr(tool_call, 'id', None)
                        if tool_call_id:
                            module_tool_call_ids.add(str(tool_call_id))
                            self.logger.debug(f"[FILTER] Tracking tool_call_id {tool_call_id} for module {self.module_name}")
                
                self.logger.debug(f"[FILTER] Including message in module context (no tag): {type(msg).__name__}")
            else:
                # Not in module context and no explicit tag - exclude
                self.logger.debug(f"[FILTER] Excluding message outside module context: {type(msg).__name__}")
        
        self.logger.info(
            f"[FILTER] Filtered {len(messages)} messages to {len(filtered)} "
            f"messages for module {self.module_name} (tracked {len(module_tool_call_ids)} tool_call_ids)"
        )
        return filtered
    
    def before_model(self, state: AgentState, runtime: Runtime) -> Optional[dict[str, Any]]:
        """
        Filter messages before model call.
        
        This hook is called before each model invocation. It filters the messages
        in the state to only include those relevant to this module, while keeping
        the original messages intact for supervisor coordination.
        
        Args:
            state: The agent state containing messages
            runtime: The runtime context
            
        Returns:
            Dictionary with filtered messages, or None if no changes needed
        """
        messages = state.get('messages', [])
        
        if not messages:
            self.logger.debug("[FILTER] No messages to filter")
            return None
        
        # Filter messages to only include module-relevant ones
        filtered_messages = self._filter_module_messages(messages)
        
        # Only return update if filtering actually changed the message list
        if len(filtered_messages) != len(messages):
            self.logger.info(
                f"[FILTER] Filtering messages: {len(messages)} -> {len(filtered_messages)} "
                f"for module {self.module_name}"
            )
            # Return filtered messages - the middleware system will use these for the model call
            # Note: We're modifying the messages that will be passed to the model,
            # but the original state remains unchanged for supervisor coordination
            return {'messages': filtered_messages}
        
        self.logger.debug("[FILTER] No filtering needed - all messages are relevant")
        return None


class ThreadIdMiddleware(AgentMiddleware):
    """
    Middleware that injects thread_id context into messages before model calls.
    
    This ensures that the LLM receives thread_id information so it can pass it
    to tools that require file access (such as file_status, get_files, etc.).
    
    The thread_id context is added as a SystemMessage at the beginning of the
    messages list, ensuring it's available for every model invocation.
    """
    
    def __init__(self):
        """Initialize the thread ID middleware."""
        self.logger = get_logger("vitess_ai.server_agents.module_middleware.ThreadIdMiddleware", level=logging.DEBUG)
    
    def _has_thread_id_context(self, messages: list[BaseMessage]) -> bool:
        """
        Check if messages already contain a thread_id context SystemMessage.
        
        Args:
            messages: List of messages to check
            
        Returns:
            True if thread_id context message is already present
        """
        for msg in messages:
            if isinstance(msg, SystemMessage):
                content = str(msg.content)
                # Check if this SystemMessage contains thread_id context
                if 'thread_id' in content.lower() and 'context' in content.lower():
                    return True
        return False
    
    def before_model(self, state: AgentState, runtime: Runtime) -> Optional[dict[str, Any]]:
        """
        Inject thread_id context before model call.
        
        This hook is called before each model invocation. It adds a SystemMessage
        with thread_id context if:
        - thread_id exists in state, runtime config, or environment variables
        - A thread_id context message is not already present in messages
        
        Args:
            state: The agent state containing messages and thread_id
            runtime: The runtime context
            
        Returns:
            Dictionary with updated messages including thread_id context, or None if no changes needed
        """
        messages = state.get('messages', [])
        thread_id = None
        
        # Try multiple sources for thread_id
        # 1. Check state directly
        thread_id = state.get('thread_id')
        if thread_id:
            self.logger.debug(f"[THREAD_ID] Found thread_id in state: {thread_id}")
        else:
            # 2. Check runtime config (configurable fields)
            if hasattr(runtime, 'config') and runtime.config:
                configurable = getattr(runtime.config, 'configurable', None)
                if configurable:
                    thread_id = configurable.get('thread_id')
                    if thread_id:
                        self.logger.debug(f"[THREAD_ID] Found thread_id in runtime config: {thread_id}")
            
            # 3. Fallback to environment variables
            if not thread_id:
                thread_id = os.environ.get('THREAD_ID') or os.environ.get('VITESS_THREAD_ID')
                if thread_id:
                    self.logger.debug(f"[THREAD_ID] Found thread_id in environment: {thread_id}")
        
        # Only add thread_id context if thread_id exists and context is not already present
        if not thread_id:
            self.logger.warning("[THREAD_ID] No thread_id found in state, runtime config, or environment - skipping context injection")
            return None
        
        if self._has_thread_id_context(messages):
            self.logger.debug("[THREAD_ID] Thread_id context already present in messages")
            return None
        
        # Create thread_id context SystemMessage
        thread_id_context = SystemMessage(
            content=f"**CONTEXT: Current thread_id is {thread_id}. When calling tools that require file access (such as file_status, get_files, etc.), you MUST pass thread_id={thread_id} as a parameter.**"
        )
        
        # Prepend thread_id context to messages (should be at the beginning)
        updated_messages = [thread_id_context] + messages
        
        self.logger.info(f"[THREAD_ID] Added thread_id={thread_id} context to messages")
        
        return {'messages': updated_messages}
