"""
Module Middleware

This module provides middleware for filtering messages so that each module agent
only sees its own conversation context, and for choosing the LLM at invoke time
from config.configurable (provider/model) without restarting the graph.
"""

import logging
import os
from typing import Any, Callable, Optional, Set

from langchain.agents.middleware import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
    hook_config,
)
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage, ToolMessage
from langgraph.config import get_config
from langgraph.runtime import Runtime

from vitess_ai.core.log import get_logger
from vitess_ai.core.llms_providers import LLMFactory, create_llm_with_fallback
from vitess_ai.core.config import global_config


def _get_provider_model_from_request(request: ModelRequest) -> tuple[Optional[str], Optional[str]]:
    """
    Read provider and model for dynamic model selection.

    ModelRequest has state and runtime; LangGraph Runtime does not expose config.
    We use langgraph.config.get_config() to get the current run's RunnableConfig
    (set at invoke via config=...), then configurable["provider"] and ["model"].
    Fall back to request.state llm_provider / llm_model if present (e.g. if set by input).
    """
    provider, model = None, None

    # 1. Current run's config (set when graph is invoked with config=...)
    try:
        config = get_config()
        # RunnableConfig is dict-like; use .get for configurable
        configurable = config.get("configurable", None) if hasattr(config, "get") else getattr(config, "configurable", None)
        configurable = configurable or {}
        if isinstance(configurable, dict):
            provider = configurable.get("provider")
            model = configurable.get("model")
    except RuntimeError:
        # get_config() raises when called outside a runnable context
        pass

    # 2. State (e.g. if provider/model were put in state by input or a node)
    if (provider is None or model is None) and hasattr(request, "state") and request.state:
        state = request.state
        if isinstance(state, dict):
            if provider is None:
                provider = state.get("llm_provider")
            if model is None:
                model = state.get("llm_model")

    return provider, model


class DynamicModelMiddleware(AgentMiddleware):
    """
    Middleware that swaps the model per request using provider/model from
    config.configurable (or state), so the graph can use a different LLM
    per invocation without restarting.
    """

    def __init__(self):
        """Initialize the dynamic model middleware."""
        self.logger = get_logger(
            "vitess_ai.server_agents.module_middleware.DynamicModelMiddleware",
            level=logging.DEBUG,
        )

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Use provider/model from configurable to create LLM and override the request."""
        provider, model = _get_provider_model_from_request(request)
        if provider and model:
            try:
                streaming = getattr(request.model, "streaming", False)
                llm = LLMFactory.create_llm(
                    provider=str(provider),
                    model=str(model),
                    temperature=0.0,
                    streaming=streaming,
                )
                self.logger.debug(
                    f"[DYNAMIC_MODEL] Using configurable model: provider={provider}, model={model}"
                )
                return handler(request.override(model=llm))
            except Exception as e:
                self.logger.warning(
                    f"[DYNAMIC_MODEL] Failed to create LLM for provider={provider}, model={model}: {e}. Using default model."
                )
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Any],
    ) -> ModelResponse:
        """Async: use provider/model from configurable to create LLM and override the request."""
        provider, model = _get_provider_model_from_request(request)
        if provider and model:
            try:
                streaming = getattr(request.model, "streaming", False)
                llm = LLMFactory.create_llm(
                    provider=str(provider),
                    model=str(model),
                    temperature=0.0,
                    streaming=streaming,
                )
                self.logger.debug(
                    f"[DYNAMIC_MODEL] Using configurable model: provider={provider}, model={model}"
                )
                return await handler(request.override(model=llm))
            except Exception as e:
                self.logger.warning(
                    f"[DYNAMIC_MODEL] Failed to create LLM for provider={provider}, model={model}: {e}. Using default model."
                )
        return await handler(request)


def filter_module_messages(
    messages: list[BaseMessage],
    module_name: str,
    logger: logging.Logger
) -> list[BaseMessage]:
    """
    Filter messages to only include those relevant to a specific module.
    
    This shared filtering logic:
    1. Always includes SystemMessages
    2. Finds the module's welcome message (tagged with module_name)
    3. Includes all messages after the welcome until hitting another module's message
    4. Includes ToolMessages that are responses to this module's tool calls
    5. Tracks tool_call_ids from this module's AIMessages to include their ToolMessages
    
    Args:
        messages: List of all messages in the conversation
        module_name: The name of the module to filter for
        logger: Logger instance for debug messages
        
    Returns:
        Filtered list of messages relevant to this module
    """
    filtered = []
    in_module_context = False
    module_tool_call_ids: Set[str] = set()
    
    for msg in messages:
        # Always include system messages (thread_id context, etc.)
        if isinstance(msg, SystemMessage):
            filtered.append(msg)
            logger.debug(f"Including SystemMessage: {str(msg.content)[:50]}...")
            continue
        
        # Check if message is explicitly tagged with a module_name
        msg_module = None
        if hasattr(msg, 'additional_kwargs') and msg.additional_kwargs:
            msg_module = msg.additional_kwargs.get('module_name')
        
        # If message is explicitly tagged with this module, include it
        if msg_module == module_name:
            filtered.append(msg)
            in_module_context = True
            
            # Check if this is a welcome message
            if isinstance(msg, AIMessage) and hasattr(msg, 'content'):
                content_lower = str(msg.content).lower()
                if 'welcome' in content_lower or module_name in content_lower:
                    logger.debug(f"Found welcome message for {module_name}")
            
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
                        logger.debug(f"Tracking tool_call_id {tool_call_id} for module {module_name}")
            
            logger.debug(f"Including module-tagged message: {type(msg).__name__}")
            continue
        
        # Exclude messages explicitly tagged with other modules
        if msg_module and msg_module != module_name:
            # This message belongs to another module - exclude it
            # But don't reset in_module_context if we're already in a conversation chain
            # Only reset if this is a clear boundary (like a supervisor message or another module's welcome)
            if isinstance(msg, AIMessage):
                # Another module's AIMessage - this is a clear boundary
                in_module_context = False
                logger.debug(f"Excluding message from other module: {msg_module}, resetting context")
            else:
                # Other module's non-AI message - exclude but keep context for tool messages
                logger.debug(f"Excluding message from other module: {msg_module}")
            continue
        
        # Handle ToolMessages - include if they're responses to this module's tool calls
        if isinstance(msg, ToolMessage):
            tool_call_id = getattr(msg, 'tool_call_id', None)
            tool_call_id_str = str(tool_call_id) if tool_call_id else None
            if tool_call_id_str and tool_call_id_str in module_tool_call_ids:
                # This ToolMessage is a response to this module's tool call
                filtered.append(msg)
                in_module_context = True  # Keep context active
                logger.debug(f"Including ToolMessage for tool_call_id {tool_call_id}")
                continue
            elif in_module_context:
                # In module context but tool_call_id not tracked - might be from a previous iteration
                # Include it to maintain conversation flow (important for react-agent to see tool results)
                filtered.append(msg)
                logger.debug(f"Including ToolMessage in module context (tool_call_id={tool_call_id}, not in tracked set)")
                continue
            else:
                # Not in module context and not a tracked tool call - exclude
                logger.debug(f"Excluding ToolMessage outside module context (tool_call_id={tool_call_id})")
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
                        logger.debug(f"Tracking tool_call_id {tool_call_id} for module {module_name}")
            
            logger.debug(f"Including message in module context (no tag): {type(msg).__name__}")
        else:
            # Not in module context and no explicit tag - exclude
            logger.debug(f"Excluding message outside module context: {type(msg).__name__}")
    
    logger.info(
        f"Filtered {len(messages)} messages to {len(filtered)} "
        f"messages for module {module_name} (tracked {len(module_tool_call_ids)} tool_call_ids)"
    )
    return filtered


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
        
        Delegates to the shared filter_module_messages function.
        
        Args:
            messages: List of all messages in the conversation
            
        Returns:
            Filtered list of messages relevant to this module
        """
        return filter_module_messages(messages, self.module_name, self.logger)
    
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
                f"[FILTER] Filtered {len(messages)} messages to {len(filtered_messages)} "
                f"messages for module {self.module_name}"
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
                thread_id = os.environ.get('THREAD_ID')
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


class RelevanceGuardrailMiddleware(AgentMiddleware):
    """
    Middleware that guards against unrelated questions using LLM-based evaluation.
    
    This guardrail ensures that only questions related to Vitess or neutron experiment
    simulations are processed by the agents. Unrelated questions are blocked before
    they reach the agent, saving processing time and providing clear feedback to users.
    
    The evaluation uses an LLM to understand context and determine relevance, making
    it more flexible than simple keyword matching. It considers the full conversation
    context of the module to avoid false positives when users respond to agent questions.
    """
    
    def __init__(self, module_name: str, provider: str = None, model: str = None):
        """
        Initialize the relevance guardrail middleware.
        
        Args:
            module_name: The name of the module this guardrail is protecting
            provider: LLM provider for evaluation (defaults to global config)
            model: Model name for evaluation (defaults to global config, can use cheaper model)
        """
        super().__init__()
        self.module_name = module_name
        self.provider = provider or global_config.DEFAULT_PROVIDER
        self.model = model or global_config.DEFAULT_MODEL
        # Create a lightweight LLM for evaluation
        # Using same provider/model but could be optimized to use cheaper model
        # Explicitly disable streaming to prevent evaluation results from appearing in UI
        self.evaluation_llm = create_llm_with_fallback(
            provider=self.provider,
            model=self.model,
            temperature=0.0,  # Low temperature for consistent evaluation
            streaming=False  # Disable streaming for internal evaluation
        )
        self.logger = get_logger(f"vitess_ai.server_agents.module_middleware.RelevanceGuardrailMiddleware.{module_name}", level=logging.INFO)
        self.logger.info(f"Initialized relevance guardrail for module {module_name} with provider={self.provider}, model={self.model}")
    
    def _filter_module_messages(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        """
        Filter messages to only include those relevant to this module.
        
        Delegates to the shared filter_module_messages function.
        
        Args:
            messages: List of all messages in the conversation
            
        Returns:
            Filtered list of messages relevant to this module
        """
        return filter_module_messages(messages, self.module_name, self.logger)
    
    def _get_latest_user_message(self, messages: list[BaseMessage]) -> Optional[HumanMessage]:
        """
        Extract the latest user message from the message list.
        
        Args:
            messages: List of messages in the conversation
            
        Returns:
            The latest HumanMessage, or None if not found
        """
        # Iterate backwards to find the most recent user message
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                return msg
        return None
    
    def _format_conversation_context(self, conversation_context: list[BaseMessage]) -> str:
        """
        Format conversation context into a readable string for the evaluation prompt.
        
        Args:
            conversation_context: List of messages in the conversation context
            
        Returns:
            Formatted string representation of the conversation
        """
        formatted_messages = []
        for msg in conversation_context:
            if isinstance(msg, SystemMessage):
                formatted_messages.append(f"System: {str(msg.content)[:200]}...")
            elif isinstance(msg, HumanMessage):
                formatted_messages.append(f"User: {str(msg.content)}")
            elif isinstance(msg, AIMessage):
                # Truncate long AI messages for context
                content = str(msg.content)
                if len(content) > 300:
                    content = content[:300] + "..."
                formatted_messages.append(f"Assistant: {content}")
            elif isinstance(msg, ToolMessage):
                # Include tool messages but keep them brief
                formatted_messages.append(f"Tool: {str(msg.content)[:150]}...")
        
        return "\n".join(formatted_messages) if formatted_messages else "No previous conversation context."
    
    def _evaluate_relevance(self, conversation_context: list[BaseMessage], latest_user_message: str) -> bool:
        """
        Use LLM to evaluate if the user's question is relevant to Vitess/neutron experiments.
        
        This evaluation considers the full conversation context to avoid false positives
        when users respond to agent questions (e.g., "yes", "no", "keep default").
        
        Args:
            conversation_context: The full conversation context for this module
            latest_user_message: The latest user message to evaluate
            
        Returns:
            True if relevant, False if unrelated
        """
        # Format conversation context for the prompt
        context_str = self._format_conversation_context(conversation_context)
        
        evaluation_prompt = f"""You are evaluating whether a user's latest message is relevant to Vitess simulation software or neutron experiment simulations.

IMPORTANT: Consider the FULL CONVERSATION CONTEXT when evaluating. Short responses like "yes", "no", "keep default", or parameter values are often valid responses to agent questions and should be considered RELEVANT if they occur in the context of a Vitess/neutron experiment conversation.

RELEVANT TOPICS INCLUDE:
- Vitess software usage, configuration, parameters, and simulation setup
- Neutron experiment setup, analysis, simulation, and data processing
- Physics simulations related to neutron experiments
- Scientific computing workflows for these domains
- Parameter configuration for physics simulations
- File management for simulation data
- Simulation execution and monitoring
- Responses to agent questions about configuration, parameters, or simulation setup
- Short confirmations or answers in the context of an ongoing Vitess/neutron conversation

UNRELATED TOPICS (should be rejected):
- General questions about unrelated software
- Questions about other physics experiments (unless clearly related to neutrons)
- General programming questions not related to simulations
- Questions about unrelated scientific domains
- Personal questions or casual conversation
- Questions about other simulation software (unless comparing to Vitess)
- Topics completely unrelated to the conversation context

CONVERSATION CONTEXT:
{context_str}

User's latest message: "{latest_user_message}"

Evaluate if this message is relevant to Vitess or neutron experiment simulations, considering the conversation context.
If the message is a response to an agent question in the context of Vitess/neutron experiments, it should be considered RELEVANT.
Respond with ONLY one word: "RELEVANT" or "UNRELATED"."""

        try:
            response = self.evaluation_llm.invoke([HumanMessage(content=evaluation_prompt)])
            result = response.content.strip().upper()
            
            # Check if response indicates relevance
            is_relevant = "RELEVANT" in result and "UNRELATED" not in result
            
            self.logger.debug(
                f"[GUARDRAIL] Evaluation result: {result}, is_relevant={is_relevant} "
                f"for message: {latest_user_message[:100]}... "
                f"(context: {len(conversation_context)} messages)"
            )
            
            return is_relevant
            
        except Exception as e:
            self.logger.error(f"[GUARDRAIL] Error during relevance evaluation: {e}", exc_info=True)
            # On error, allow the message through to avoid blocking legitimate questions
            # This is a fail-open approach for better user experience
            self.logger.warning("[GUARDRAIL] Evaluation failed, allowing message through (fail-open)")
            return True
    
    @hook_config(can_jump_to=["end"])
    def before_agent(self, state: AgentState, runtime: Runtime) -> Optional[dict[str, Any]]:
        """
        Check user input relevance before agent processes it.
        
        This hook is called before the agent processes the input. It evaluates
        if the user's question is related to Vitess or neutron experiments,
        considering the full conversation context of the module.
        If unrelated, it blocks execution and returns a polite rejection message.
        
        Args:
            state: The agent state containing messages
            runtime: The runtime context
            
        Returns:
            Dictionary with rejection message and jump_to="end" if unrelated,
            None if relevant (allows normal processing)
        """
        messages = state.get('messages', [])
        
        if not messages:
            self.logger.debug("[GUARDRAIL] No messages to evaluate")
            return None
        
        # Filter messages to get this module's conversation context
        filtered_messages = self._filter_module_messages(messages)
        
        if not filtered_messages:
            self.logger.debug("[GUARDRAIL] No filtered messages found, allowing processing")
            return None
        
        # Get the latest user message from the filtered context
        user_message = self._get_latest_user_message(filtered_messages)
        
        if not user_message:
            self.logger.debug("[GUARDRAIL] No user message found in filtered context, allowing processing")
            return None
        
        user_content = str(user_message.content).strip()
        
        # Skip evaluation for very short messages or system messages
        if len(user_content) < 3:
            self.logger.debug("[GUARDRAIL] Message too short, allowing through")
            return None
        
        # Evaluate relevance with full conversation context
        # Pass all filtered messages as context, including the latest user message
        is_relevant = self._evaluate_relevance(filtered_messages, user_content)
        
        if not is_relevant:
            # Block execution and return polite rejection message
            rejection_message = (
                "I'm specialized in helping with Vitess simulation software and neutron experiment simulations. "
                "Your question seems to be outside my area of expertise. "
                "Please ask questions related to:\n"
                "- Vitess software configuration and parameters\n"
                "- Neutron experiment setup and simulation\n"
                "- Physics simulation workflows\n"
                "- Scientific computing for these domains\n\n"
                "How can I help you with your Vitess or neutron experiment simulation?"
            )
            
            self.logger.info(
                f"[GUARDRAIL] Blocked unrelated question: {user_content[:100]}... "
                f"(context: {len(filtered_messages)} messages)"
            )
            
            return {
                "messages": [AIMessage(content=rejection_message)],
                "jump_to": "end"
            }
        
        self.logger.debug(f"[GUARDRAIL] Question is relevant, allowing processing")
        return None
