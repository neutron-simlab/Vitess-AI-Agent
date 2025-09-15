"""
ReadInAgent - Migrated to use ModuleAgent
LangGraph Agent for Neutron Simulation Parameters Configuration
"""
from typing import List
from langchain.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from vitess_ai.schema.readin_module import InitialResponseReadIn
from vitess_ai.prompts.readin_module import READIN_AGENT_PROMPT, READIN_AGENT_WELCOME
from vitess_ai.agents.base_module_agent import BaseModuleAgent
from vitess_ai.core.config import global_config


class ReadInAgent(BaseModuleAgent[InitialResponseReadIn]):
    """
    ReadIn Agent for configuring neutron simulation input parameters.
    
    Handles:
    - Initial beam conditions
    - Source parameters  
    - Input file specifications
    - Simulation initialization settings
    """
    
    def __init__(self, provider:str, model: str, tools: List[BaseTool] = [], serverless_mode: bool = False):
        """Initialize the ReadIn Agent with base functionality"""
        super().__init__(provider, model, tools, serverless_mode)
    
    # =================
    # REQUIRED ABSTRACT METHODS
    # =================
    
    @property
    def name(self) -> str:
        return "Read-in Agent"
    
    @property
    def module_name(self) -> str:
        return "readin"
    
    @property
    def welcome_message(self) -> str:
        return READIN_AGENT_WELCOME
    
    @property
    def system_prompt(self) -> str:
        return READIN_AGENT_PROMPT
    
    def get_initial_response_schema(self):
        return InitialResponseReadIn
    
    def get_result_key(self) -> str:
        return "readin_params"
    
    # =================
    # CUSTOMIZATIONS FOR READIN MODULE
    # =================
    
    def get_default_setup_message(self) -> str:
        """Custom message for ReadIn default setup"""
        return """
        You have chosen the default setup configuration, we will handle all the setup 
        apart from several parameters that need to be filled manually.
        
        For the read-in module, this means:
        - Standard neutron beam parameters will be set
        - Default source configurations will be applied
        - You'll only need to specify essential input parameters
        """
    
    def get_customize_setup_message(self) -> str:
        """Custom message for ReadIn customization"""
        return """
        You have chosen the fully customize configuration, let me guide you to fill 
        all parameters.
        
        We'll go through:
        - Neutron beam specifications
        - Source parameters and geometry
        - Input file configurations
        - Initial conditions and boundary settings
        """
    
    def parse_config_mode(self, response: InitialResponseReadIn) -> str:
        """Parse config mode from ReadIn response"""
        return response.response
    
    def get_valid_config_modes(self) -> List[str]:
        """ReadIn uses 'Custom' instead of 'Customize'"""
        return ['Default Setup', 'Custom']
    
    def validate_config_mode(self, config_mode: str) -> bool:
        """Validate ReadIn configuration mode"""
        return config_mode in ['Default Setup', 'Custom']
    
    def get_completion_message(self) -> str:
        """Custom completion message for ReadIn"""
        return """
        ✅ Read-in parameters configuration completed successfully!
        
        Your neutron simulation input parameters have been validated and are ready.
        The configuration includes all necessary beam parameters, source specifications,
        and initial conditions for the simulation.
        """

# =================
# FACTORY FUNCTION FOR EASY SETUP
# =================

async def create_readin_agent(
    provider: str = global_config.DEFAULT_PROVIDER,
    model: str = global_config.DEFAULT_MODEL,
    mcp_tool_path: str = global_config.READIN_MCP_PATH
    ) -> ReadInAgent:
    """Factory function to create a ReadIn agent with MCP tools"""
    
    client = MultiServerMCPClient({
        "validation": {
            "command": "python",
            "args": [mcp_tool_path],
            "transport": "stdio"
        }
    })
    
    tools = await client.get_tools()
    return ReadInAgent(provider=provider, model=model, tools=tools, serverless_mode=True)


# =================
# EXAMPLE USAGE
# =================

async def main():
    """Example usage of the migrated ReadIn Agent"""
    print("🚀 Initializing ReadIn Agent...")
    
    # Create agent using factory function
    agent = await create_readin_agent()
    
    # Example conversation flow
    thread_id = "readin_200"
    print("=== Neutron Simulation Read-in Parameters Configuration ===\n")
    
    print("🤖 Starting conversation...")

    # Use run_serverless for standalone testing
    final_result = await agent.run_serverless("", thread_id)
    
    print("\n" + "="*60)
    print("FINAL READIN PARAMS:")
    print("="*60)
    print(final_result)
    
    # Example of getting conversation history
    history = agent.get_conversation_history(thread_id)
    print(f"\nConversation had {len(history)} messages")


if __name__ == "__main__":
    import asyncio
    
    # Run the main demo
    asyncio.run(main())