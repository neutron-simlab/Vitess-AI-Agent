"""
Agent input preparation utilities for LangGraph agents.

This module provides utilities for preparing input for LangGraph agent execution
in the react-agent architecture. With react-agent architecture, modules use the
END pattern (ending when user input is needed) rather than interrupts.
LangGraph automatically resumes from checkpoint when invoked with the same thread_id.
"""

import logging
from typing import Any
from uuid import UUID, uuid4

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from vitess_ai.server.errors import StateError

logger = logging.getLogger(__name__)


class AgentInputHandler:
    """Handles input preparation for LangGraph agents in react-agent architecture."""
    
    @staticmethod
    async def prepare_input(
        user_input: str,
        agent: CompiledStateGraph,
        thread_id: str | None = None,
        user_id: str | None = None,
        run_id: UUID | None = None
    ) -> tuple[dict[str, Any], UUID]:
        """
        Prepare input for agent invocation.
        
        With react-agent architecture, modules END when needing user input.
        LangGraph automatically resumes from checkpoint when invoked with same thread_id.
        
        Args:
            user_input: User input message
            agent: The compiled state graph
            thread_id: Optional thread ID for conversation continuity
            user_id: Optional user ID for cross-thread conversations
            run_id: Optional run ID, will generate if not provided
            
        Returns:
            Tuple of (kwargs for agent invocation, run_id)
            
        Raises:
            StateError: If there's an error accessing agent state
        """
        run_id = run_id or uuid4()
        thread_id = thread_id or str(uuid4())
        user_id = user_id or str(uuid4())
        
        configurable = {"thread_id": thread_id, "user_id": user_id}
        config = RunnableConfig(
            configurable=configurable,
            run_id=run_id,
        )
        
        # Prepare input - always add as human message
        # LangGraph will automatically resume from checkpoint if there's an active module
        # that ended waiting for user input (END pattern)
        input_data = {
            "messages": [HumanMessage(content=user_input)],
            "thread_id": thread_id,
            "user_id": user_id,
        }
        
        kwargs = {
            "input": input_data,
            "config": config,
        }
        
        return kwargs, run_id
    
    @staticmethod
    async def has_active_module_waiting(
        agent: CompiledStateGraph,
        config: RunnableConfig
    ) -> bool:
        """
        Check if there's an active module waiting for user input (END pattern).
        
        With react-agent architecture, modules END when needing user input.
        This checks if current_active_module is set in state.
        
        Args:
            agent: The compiled state graph
            config: The runnable config for state access
            
        Returns:
            True if there's an active module waiting, False otherwise
        """
        try:
            state: Any = await agent.aget_state(config=config)
            
            if not state or not state.values:
                return False
            
            # Check for current_active_module in state
            current_active_module = state.values.get('current_active_module')
            return current_active_module is not None
            
        except Exception as e:
            logger.error(f"Failed to access agent state: {e}", exc_info=True)
            # Return False on error - will start fresh
            return False

