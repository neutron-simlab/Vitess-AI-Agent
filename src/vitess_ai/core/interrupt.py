import logging
from typing import Dict, Any, Optional, Union
from langgraph.types import Command
from langchain_core.messages import HumanMessage
from langgraph.graph.state import CompiledStateGraph
from vitess_ai.schema.base import FillingStage
# from vitess_ai.agents.base_module_agent import BaseModuleAgent


class InterruptManager:
    """
    Unified interrupt manager that handles interrupts in two modes:
    1. FastAPI Mode: Returns interrupts to the API layer for handling (non-blocking)
    2. Standalone Mode: Uses input() for testing (blocking)
    
    This replaces the old InterruptManager and provides a single, clean interface.
    """
    
    def __init__(self, logger=None, server_mode: bool = True):
        self.logger = logger or logging.getLogger(__name__)
        self.server_mode = server_mode
        self.interrupt_count = 0
        self.interrupt_contexts: Dict[str, Dict[str, Any]] = {}  # Store interrupt contexts by thread_id
    
    async def execute_with_interrupts(
        self, 
        agent_app: CompiledStateGraph, 
        input_state: dict, 
        config: dict,
        user_responses: Optional[Dict[int, str]] = None
    ) -> Union[dict, Dict[str, Any]]:
        """
        Execute agent with interrupt handling.
        
        Args:
            agent_app: The compiled agent graph
            input_state: Initial input state
            config: Agent configuration
            user_responses: Pre-provided responses for interrupts (FastAPI mode)
            
        Returns:
            - In FastAPI mode: Either final result or interrupt info
            - In standalone mode: Final result after handling all interrupts
        """
        self.logger.info("Starting agent execution with interrupt handling")
        
        # Start the agent execution
        result = await agent_app.ainvoke(input_state, config)
        
        # Handle interrupts
        while result.get("__interrupt__"):
            self.interrupt_count += 1
            interrupt_value = result["__interrupt__"][0].value
            self.logger.info(f"Handling interrupt #{self.interrupt_count}: {interrupt_value}")
            
            if self.server_mode:
                # FastAPI mode: Return interrupt info instead of blocking
                thread_id = config.get("configurable", {}).get("thread_id", "default")
                interrupt_info = {
                    "status": "interrupted",
                    "interrupt_count": self.interrupt_count,
                    "interrupt_value": interrupt_value,
                    "thread_id": thread_id,
                    "run_id": config.get("run_id"),
                    "message": f"Agent interrupted at step {self.interrupt_count}. Please provide response to: {interrupt_value}"
                }
                # Store interrupt context for later resumption
                self.store_interrupt_context(thread_id, interrupt_info)
                return interrupt_info
            else:
                # Standalone mode: Use blocking input() for testing
                user_response = input(interrupt_value).strip()
                self.logger.info(f"User provided input: {user_response[:50]}{'...' if len(user_response) > 50 else ''}")
                
                # Resume the graph with user input
                result = await agent_app.ainvoke(Command(resume=user_response), config)
                self.logger.info(f"Graph resumed after interrupt #{self.interrupt_count}")
        
        # Execution completed successfully
        self.logger.info(f"Agent execution completed after handling {self.interrupt_count} interrupt(s)")
        return result
    
    def store_interrupt_context(self, thread_id: str, interrupt_info: Dict[str, Any]):
        """Store interrupt context for later resumption"""
        self.interrupt_contexts[thread_id] = interrupt_info
        self.logger.info(f"Stored interrupt context for thread {thread_id}")
    
    def get_interrupt_context(self, thread_id: str) -> Optional[Dict[str, Any]]:
        """Get stored interrupt context"""
        return self.interrupt_contexts.get(thread_id)
    
    def clear_interrupt_context(self, thread_id: str):
        """Clear stored interrupt context"""
        if thread_id in self.interrupt_contexts:
            del self.interrupt_contexts[thread_id]
            self.logger.info(f"Cleared interrupt context for thread {thread_id}")
    
    def has_interrupt_context(self, thread_id: str) -> bool:
        """Check if interrupt context exists for thread"""
        return thread_id in self.interrupt_contexts
    
    async def execute_module_agent(
        self, 
        agent: Any, 
        thread_id: str, 
        user_input: str = "",
        user_responses: Optional[Dict[int, str]] = None
    ) -> Union[dict, str, Dict[str, Any]]:
        """
        Execute a module agent with interrupt handling.
        
        Args:
            agent: The module agent to execute
            thread_id: Thread ID for conversation continuity
            user_input: Initial user input
            user_responses: Pre-provided responses for interrupts (FastAPI mode)
            
        Returns:
            - In FastAPI mode: Either final result or interrupt info
            - In standalone mode: Final result after handling all interrupts
        """
        config = {"configurable": {"thread_id": thread_id}}
        
        # Prepare input state (same logic as current agent.run())
        current_state = agent.app.get_state(config)
        user_message = HumanMessage(content=user_input)
        
        if current_state.values:
            # Continue existing conversation
            current_messages = current_state.values.get("messages", [])
            input_state = {
                "messages": current_messages + [user_message],
                "stage": current_state.values.get("stage", FillingStage(stage='processing')),
                "config_mode": current_state.values.get("config_mode", ""),
                "validation_status": current_state.values.get("validation_status"),
                "error_message": current_state.values.get("error_message")
            }
        else:
            # Start new conversation
            input_state = {
                "messages": [user_message],
                "stage": FillingStage(stage='processing'),
                "config_mode": "",
                "validation_status": None,
                "error_message": None
            }
        
        # Execute with interrupt handling
        result = await self.execute_with_interrupts(agent.app, input_state, config, user_responses)
        
        # Handle interrupt response
        if isinstance(result, dict) and result.get("status") == "interrupted":
            return result
        
        # Return standardized results for successful completion
        if result.get('validation_status'):
            return {
                'parameters': result['parameters'],
                'cli_parameters': result['cli_parameters']
            }
        else:
            return "No response generated"
    
    async def resume_from_interrupt(
        self,
        agent_app: CompiledStateGraph,
        config: dict,
        user_response: str
    ) -> Union[dict, Dict[str, Any]]:
        """
        Resume agent execution from an interrupt.
        
        Args:
            agent_app: The compiled agent graph
            config: Agent configuration (must include thread_id)
            user_response: User's response to the interrupt
            
        Returns:
            Either final result or new interrupt info
        """
        thread_id = config.get("configurable", {}).get("thread_id", "default")
        self.logger.info(f"Resuming agent execution with user response: {user_response[:50]}{'...' if len(user_response) > 50 else ''}")
        
        # Check if we have stored interrupt context
        if self.has_interrupt_context(thread_id):
            self.logger.info(f"Found stored interrupt context for thread {thread_id}")
            # Clear the stored context as we're resuming
            self.clear_interrupt_context(thread_id)
        
        # Resume the graph with user input
        result = await agent_app.ainvoke(Command(resume=user_response), config)
        
        # Handle any new interrupts
        while result.get("__interrupt__"):
            self.interrupt_count += 1
            interrupt_value = result["__interrupt__"][0].value
            self.logger.info(f"New interrupt #{self.interrupt_count}: {interrupt_value}")
            
            if self.server_mode:
                # Return new interrupt info
                thread_id = config.get("configurable", {}).get("thread_id", "default")
                interrupt_info = {
                    "status": "interrupted",
                    "interrupt_count": self.interrupt_count,
                    "interrupt_value": interrupt_value,
                    "thread_id": thread_id,
                    "run_id": config.get("run_id"),
                    "message": f"Agent interrupted again at step {self.interrupt_count}. Please provide response to: {interrupt_value}"
                }
                # Store new interrupt context
                self.store_interrupt_context(thread_id, interrupt_info)
                return interrupt_info
            else:
                # Standalone mode: Use blocking input()
                user_response = input(interrupt_value).strip()
                result = await agent_app.ainvoke(Command(resume=user_response), config)
        
        # Execution completed successfully
        self.logger.info(f"Agent execution completed after handling {self.interrupt_count} interrupt(s)")
        return result


