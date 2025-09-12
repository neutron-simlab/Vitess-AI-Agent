"""
GuideAgent - Migrated to use BaseModuleAgent
LangGraph Agent for Neutron Guide Parameters Configuration
"""
from typing import List
from langchain.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from vitess_ai.schema.guide_module import InitialResponseGuide
from vitess_ai.prompts.guide_module import GUIDE_AGENT_PROMPT, GUIDE_AGENT_WELCOME
from vitess_ai.agents.base_module_agent import BaseModuleAgent
from vitess_ai.core.config import global_config


class GuideAgent(BaseModuleAgent[InitialResponseGuide]):
    """
    Guide Agent for configuring neutron guide parameters.
    
    Handles:
    - Guide geometry (width, height, length)
    - Reflectivity parameters (m-value)
    - Guide coating specifications
    - Neutron transport optimization
    """
    
    def __init__(self, provider: str, model: str, tools: List[BaseTool] = []):
        """Initialize the Guide Agent with base functionality"""
        super().__init__(provider, model, tools)
    
    # =================
    # REQUIRED ABSTRACT METHODS
    # =================
    
    @property
    def name(self) -> str:
        return "Guide Agent"
    
    @property
    def module_name(self) -> str:
        return "guide"
    
    @property
    def welcome_message(self) -> str:
        return GUIDE_AGENT_WELCOME
    
    @property
    def system_prompt(self) -> str:
        return GUIDE_AGENT_PROMPT
    
    def get_initial_response_schema(self):
        return InitialResponseGuide
    
    def get_result_key(self) -> str:
        return "guide_params"
    
    # =================
    # CUSTOMIZATIONS FOR GUIDE MODULE
    # =================
    
    def get_default_setup_message(self) -> str:
        """Custom message for Guide default setup"""
        return """
        You have chosen the default setup configuration. We will use optimal default 
        values for neutron guide parameters.
        
        This creates:
        - 3x3 cm straight guide cross-section
        - 50 cm guide length
        - High-quality coating (m-value 3.0)
        - Standard neutron transport settings
        
        All parameters will be set to recommended values that work well for most 
        neutron guide simulations.
        """
    
    def get_customize_setup_message(self) -> str:
        """Custom message for Guide customization"""
        return """
        You have chosen the customize configuration. I'll help you configure the 
        guide parameters step by step.
        
        You can modify:
        - Guide dimensions (width, height, length)
        - Reflectivity properties (m-value coating)
        - Guide geometry and curvature
        - Surface properties and specifications
        
        We'll go through each customizable parameter and you can choose which ones 
        to change from the default values.
        """
    
    def parse_config_mode(self, response: InitialResponseGuide) -> str:
        """Parse config mode from Guide response"""
        return response.response
    
    def get_valid_config_modes(self) -> List[str]:
        """Guide uses 'Customize' instead of 'Custom'"""
        return ['Default Setup', 'Customize']
    
    def validate_config_mode(self, config_mode: str) -> bool:
        """Validate Guide configuration mode"""
        return config_mode in ['Default Setup', 'Customize']
    
    def get_completion_message(self) -> str:
        """Custom completion message for Guide"""
        return """
        ✅ Neutron guide parameters configuration completed successfully!
        
        Your guide specifications have been validated and optimized for neutron transport.
        The configuration includes all geometric parameters, coating specifications,
        and reflectivity settings for efficient neutron guiding.
        """


# =================
# FACTORY FUNCTION FOR EASY SETUP
# =================

async def create_guide_agent(
    provider: str = global_config.DEFAULT_PROVIDER,
    model: str = global_config.DEFAULT_MODEL,
    mcp_tool_path: str = global_config.GUIDE_MCP_PATH
    ) -> GuideAgent:
    """Factory function to create a Guide agent with MCP tools"""
    
    client = MultiServerMCPClient({
        "validation": {
            "command": "python",
            "args": [mcp_tool_path],
            "transport": "stdio"
        }
    })
    
    tools = await client.get_tools()
    return GuideAgent(provider=provider, model=model, tools=tools)


# =================
# EXAMPLE USAGE
# =================

async def main():
    """Example usage of the migrated Guide Agent"""
    print("🚀 Initializing Guide Agent...")
    
    # Create agent using factory function
    agent = await create_guide_agent()
    
    # Example conversation flow
    thread_id = "guide_500"
    print("=== Neutron Guide Parameters Configuration ===\n")
    
    print("🤖 Starting conversation...")
    # result = await agent.stream_run("", thread_id)

    final_result = None
    async for event in agent.stream_run("", thread_id):
        if event["type"] == "chunk":
            final_result = event["data"]  # Keep track of the last chunk
    
    print("\n" + "="*60)
    print("FINAL GUIDE PARAMS:")
    print("="*60)
    print(final_result)
    

async def test_standalone():
    """Simple standalone testing example using the new test_standalone() method"""
    print("🧪 Testing Guide Agent Standalone...")
    
    # Create agent with MCP tools
    agent = GuideAgent(provider="openai", model="gpt-4")
    
    # Test using the new standalone method
    result = await agent.test_standalone()
    
    print("\n" + "="*60)
    print("STANDALONE TEST RESULT:")
    print("="*60)
    print(result)
    return result


if __name__ == "__main__":
    import asyncio
    
    # Choose which test to run:
    # Option 1: Full demo (existing)
    # asyncio.run(main())
    
    # Option 2: Simple standalone test (new)
    asyncio.run(test_standalone())