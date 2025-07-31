"""
FilterAgent - Migrated to use BaseModuleAgent
LangGraph Agent for Neutron Filter Configuration
"""
from typing import List
from langchain.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from vitess_ai.schema.filter_module import InitialResponseFilter
from vitess_ai.prompts.filter_module import (
    FILTER_AGENT_PROMPT, 
    FILTER_AGENT_WELCOME,
)
from vitess_ai.agents.base_module_agent import BaseModuleAgent
from vitess_ai.core.config import global_config


class FilterAgent(BaseModuleAgent[InitialResponseFilter]):
    """
    Filter Agent for configuring neutron filter parameters.
    
    """
    
    def __init__(self, provider: str, model: str, tools: List[BaseTool] = []):
        """Initialize the Filter Agent with base functionality"""
        super().__init__(provider, model, tools)
    
    # =================
    # REQUIRED ABSTRACT METHODS
    # =================
    
    @property
    def name(self) -> str:
        return "Filter Agent"
    
    @property
    def module_name(self) -> str:
        return "filter"
    
    @property
    def welcome_message(self) -> str:
        return FILTER_AGENT_WELCOME
    
    @property
    def system_prompt(self) -> str:
        return FILTER_AGENT_PROMPT
    
    def get_initial_response_schema(self):
        return InitialResponseFilter
    
    def get_result_key(self) -> str:
        return "filter_params"
    
    # =================
    # CUSTOMIZATIONS FOR FILTER MODULE
    # =================
    
    def get_default_setup_message(self) -> str:
        """Custom message for Filter default setup"""
        return """
        You have chosen the default setup configuration.
        Unfortunatel, the filter module agent can only work with the custom configuration.
        Let me guide you through configuring all filter parameters.
        """
    
    def get_customize_setup_message(self) -> str:
        """Custom message for Filter customization"""
        return """
        You have chosen the custom configuration. Let me guide you through 
        configuring all filter parameters.
        """
    
    def parse_config_mode(self, response: InitialResponseFilter) -> str:
        """Parse config mode from Filter response"""
        return response.response
    
    def get_valid_config_modes(self) -> List[str]:
        """Filter uses 'Custom' and 'Default' modes"""
        return ['Default Setup', 'Customize']
    
    def validate_config_mode(self, config_mode: str) -> bool:
        """Validate Filter configuration mode"""
        return config_mode in ['Default Setup', 'Customize']
    
    def get_completion_message(self) -> str:
        """Custom completion message for Filter"""
        return """
        ✅ Filter parameters configuration completed successfully!
        
        Your neutron filter specifications have been validated and are ready.
        The configuration includes all necessary filter materials, dimensions,
        positioning, and transmission properties for the simulation.
        """
    
    # =================
    # FILTER-SPECIFIC CUSTOMIZATIONS
    # =================
    
    def _route_after_init(self, state) -> str:
        """Custom routing for Filter module"""
        config_mode = state.get('config_mode', '')
        self.logger.info(f"Routing after init with config_mode: {config_mode}")
        
        if not self.validate_config_mode(config_mode):
            self.logger.warning(f"Invalid config mode '{config_mode}', ending conversation")
            print("We don't understand your choice.\nWe will end the conversation.")
            return "END"  # Use string instead of END constant
        
        # Filter-specific routing logic
        if config_mode == 'Customize':
            self.logger.info("Routing to customize setup for custom filter configuration")
            return 'customize_setup'  # Route custom to customize_setup
        elif config_mode == 'Default Setup':
            self.logger.info("Routing to default setup for standard filter configuration")
            return 'default_setup'
        else:
            self.logger.error(f"Unhandled config mode: {config_mode}")
            print("Invalid configuration mode selected.")
            return "END"


# =================
# FACTORY FUNCTION FOR EASY SETUP
# =================

async def create_filter_agent(
    provider: str = global_config.DEFAULT_PROVIDER,
    model: str = global_config.DEFAULT_MODEL,
    mcp_tool_path: str = global_config.FILTER_MCP_PATH  # Update this path
) -> FilterAgent:
    """Factory function to create a Filter agent with MCP tools"""
    
    client = MultiServerMCPClient({
        "validation": {
            "command": "python",
            "args": [mcp_tool_path],
            "transport": "stdio"
        }
    })
    
    tools = await client.get_tools()
    return FilterAgent(provider=provider, model=model, tools=tools)


# =================
# EXAMPLE USAGE
# =================

async def main():
    """Example usage of the migrated Filter Agent"""
    print("🚀 Initializing Filter Agent...")
    
    # Create agent using factory function
    agent = await create_filter_agent()
    
    # Example conversation flow
    thread_id = "filter_100"
    print("=== Neutron Filter Configuration Demo ===\n")
    
    print("🤖 Starting conversation...")
    result = await agent.run("", thread_id)
    
    print("\n" + "="*60)
    print("FINAL FILTER PARAMS:")
    print("="*60)
    print(result)
    
    # Example of getting conversation history
    history = agent.get_conversation_history(thread_id)
    print(f"\nConversation had {len(history)} messages")
    
    # Example of accessing the logger for this specific agent
    agent.logger.info("Filter agent demo completed successfully")


if __name__ == "__main__":
    import asyncio
    
    # Run the main example
    asyncio.run(main())
    