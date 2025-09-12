import logging
from langgraph.types import Command
from langchain_core.messages import HumanMessage
from langgraph.graph.state import CompiledStateGraph
from vitess_ai.schema.base import FillingStage
from vitess_ai.agents.base_module_agent import BaseModuleAgent

class InterruptManager:
    """Centralized interrupt handling for all module agents"""
    
    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self.interrupt_count = 0
    
    async def execute_with_interrupts(self, agent_app: CompiledStateGraph, input_state: dict, config: dict) -> dict:
        """
        Execute any agent app with centralized interrupt handling
        
        This replaces the interrupt loop that's currently in each module agent's run() method
        """
        self.logger.info("Starting agent execution with interrupt handling")
        
        # Start the agent execution
        result = await agent_app.ainvoke(input_state, config)
        
        # Handle ALL interrupts in a centralized way
        while result.get("__interrupt__"):
            self.interrupt_count += 1
            self.logger.info(f"Handling interrupt #{self.interrupt_count}")
            
            # Extract interrupt message (e.g., "User:\n")
            interrupt_value = result["__interrupt__"][0].value
            self.logger.info(f"Graph interrupted, waiting for user input: {interrupt_value}")
            
            # Get user input (same as current logic)
            user_response = input(interrupt_value).strip()
            self.logger.info(f"User provided input: {user_response[:50]}{'...' if len(user_response) > 50 else ''}")
            
            # Resume the graph with user input
            self.logger.info(f"Resuming graph with user input (interrupt #{self.interrupt_count})")
            result = await agent_app.ainvoke(Command(resume=user_response), config)
            self.logger.info(f"Graph resumed after interrupt #{self.interrupt_count}")
        
        self.logger.info(f"Agent execution completed after handling {self.interrupt_count} interrupt(s)")
        return result
    
    async def execute_module_agent(self, agent: BaseModuleAgent, thread_id: str, user_input: str = "") -> dict:
        """
        Execute a module agent with centralized interrupt handling
        
        This is what the supervisor would call instead of agent.run()
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
        
        # Execute with centralized interrupt handling
        result = await self.execute_with_interrupts(agent.app, input_state, config)
        
        # Return standardized results (same as current logic)
        if result.get('validation_status'):
            return {
                'parameters': result['parameters'],
                'cli_parameters': result['cli_parameters']
            }
        else:
            return "No response generated"