"""
Interrupt handling utilities for LangGraph agents.

This module provides utilities for detecting and handling interrupts in
LangGraph agent execution, including resumption logic.
"""

import logging
from typing import Any
from uuid import UUID, uuid4

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from vitess_ai.server.errors import InterruptError, StateError

logger = logging.getLogger(__name__)


class InterruptHandler:
    """Handles interrupt detection and input preparation for LangGraph agents."""
    
    @staticmethod
    async def prepare_input(
        user_input: str,
        agent: CompiledStateGraph,
        thread_id: str | None = None,
        user_id: str | None = None,
        run_id: UUID | None = None
    ) -> tuple[dict[str, Any], UUID]:
        """
        Prepare input for agent invocation, handling interrupts if present.
        
        Args:
            user_input: User input message
            agent: The compiled state graph
            thread_id: Optional thread ID for conversation continuity
            user_id: Optional user ID for cross-thread conversations
            run_id: Optional run ID, will generate if not provided
            
        Returns:
            Tuple of (kwargs for agent invocation, run_id)
            
        Raises:
            InterruptError: If there's an error checking for interrupts
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
        
        # Check for interrupts that need to be resumed
        try:
            has_interrupt = await InterruptHandler.has_pending_interrupt(agent, config)
        except Exception as e:
            logger.error(f"Failed to check for interrupts: {e}", exc_info=True)
            raise StateError(
                "Failed to check for interrupts",
                operation="get_state",
                details={"error": str(e)}
            ) from e
        
        # Prepare input based on interrupt status
        if has_interrupt:
            # User input is response to resume agent execution from interrupt
            input_data: Command | dict[str, Any] = Command(resume=user_input)
        else:
            # Normal input - add as human message
            input_data = {"messages": [HumanMessage(content=user_input)]}
        
        kwargs = {
            "input": input_data,
            "config": config,
        }
        
        return kwargs, run_id
    
    @staticmethod
    async def has_pending_interrupt(
        agent: CompiledStateGraph,
        config: RunnableConfig
    ) -> bool:
        """
        Check if there are pending interrupts in the agent state.
        
        Args:
            agent: The compiled state graph
            config: The runnable config for state access
            
        Returns:
            True if there are pending interrupts, False otherwise
            
        Raises:
            StateError: If there's an error accessing state
        """
        try:
            state: Any = await agent.aget_state(config=config)
            
            if not state:
                return False
            
            # Check for interrupts in state tasks
            if hasattr(state, 'tasks'):
                interrupted_tasks = [
                    task for task in state.tasks
                    if hasattr(task, "interrupts") and task.interrupts
                ]
                return len(interrupted_tasks) > 0
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to access agent state: {e}", exc_info=True)
            raise StateError(
                "Failed to access agent state",
                operation="get_state",
                details={"error": str(e)}
            ) from e

