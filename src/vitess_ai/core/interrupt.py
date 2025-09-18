import logging
from typing import Union
from langgraph.types import Command
from langchain_core.messages import HumanMessage
from langgraph.graph.state import CompiledStateGraph


def _setup_interrupt_logging():
    logger_name = f"vitess_ai.interrupt"
    logger = logging.getLogger(logger_name)
    """Setup logging for the interrupt module"""
    # Only add handler if logger doesn't have one (avoid duplicates)
    if not logger.handlers:
        # Create console handler
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        
        # Create formatter
        formatter = logging.Formatter(
            fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        
        # Add handler to logger
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        
        # Prevent propagation to avoid duplicate logs
        logger.propagate = False
    return logger

# Setup logging when module is imported
logger = _setup_interrupt_logging()


class InterruptManager:
    """
    Simplified interrupt manager that leverages LangGraph's automatic subgraph resumption.
    
    With LangGraph, subgraphs (modules) automatically resume after interrupts when the main
    graph is invoked with Command(resume=...). This eliminates the need for complex context
    tracking - we only need:
    1. Thread ID (for graph state persistence)
    2. Main graph instance
    3. User input after interrupt
    
    Modes:
    1. FastAPI Mode: Returns interrupts to the API layer for handling (non-blocking)
    2. Standalone Mode: Uses input() for testing (blocking)
    """
    
    def __init__(self, server_mode: bool = True):
        self.logger = logger
        self.server_mode = server_mode
        self.interrupt_count = 0
    
    async def execute_with_interrupts(
        self, 
        agent_app: CompiledStateGraph, 
        input_state: dict, 
        config: dict
    ) -> Union[dict, dict]:
        """
        Execute agent with interrupt handling.
        
        Args:
            agent_app: The compiled agent graph
            input_state: Initial input state
            config: Agent configuration
            
        Returns:
            - In FastAPI mode: Either final result or interrupt info
            - In standalone mode: Final result after handling all interrupts
        """
        self.logger.info("Starting agent execution with interrupt handling")
        thread_id = config.get("configurable", {}).get("thread_id", "default")
        user_id = config.get("configurable", {}).get("user_id", "default")
        self.logger.info(f"Execution context - thread_id: {thread_id}, user_id: {user_id}")
        
        # Start the agent execution
        result = await agent_app.ainvoke(input_state, config)
        
        # Handle interrupts
        while result.get("__interrupt__"):
            # self.interrupt_count += 1
            # interrupt_value = result["__interrupt__"][0].value
            # self.logger.info(f"Handling interrupt #{self.interrupt_count}: {interrupt_value}")
            
            # if self.server_mode:
                # FastAPI mode: Graph will pause and wait for resumption
                # The server will detect interrupts via stream_mode="updates" and handle via /module-interrupt endpoint
                # self.logger.info(f"Graph paused at interrupt #{self.interrupt_count}, waiting for server resumption")
            if not self.server_mode:
                # Standalone mode: Use blocking input() for testing
                interrupt_value = result["__interrupt__"][0].value
                user_response = input(interrupt_value).strip()
                self.logger.info(f"User provided input: {user_response[:50]}{'...' if len(user_response) > 50 else ''}")
                
                # Resume the graph with user input
                result = await agent_app.ainvoke(Command(resume=user_response), config)
                self.logger.info(f"Graph resumed after interrupt #{self.interrupt_count}")
        
        # Execution completed successfully
        self.logger.info(f"Agent execution completed after handling {self.interrupt_count} interrupt(s)")
        self.logger.info(f"Final result keys: {list(result.keys()) if isinstance(result, dict) else 'Non-dict result'}")
        return result
    


