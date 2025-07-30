"""
WriteoutAgent - Migrated to use BaseModuleAgent
LangGraph Agent for Neutron Simulation Writeout Parameters Configuration
"""
from typing import List
from langchain.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from vitess_ai.schema.writeout_module import InitialResponseWriteout
from vitess_ai.prompts.writeout_module import WRITEOUT_AGENT_PROMPT, WRITEOUT_AGENT_WELCOME
from vitess_ai.agents.base_module_agent import BaseModuleAgent


class WriteoutAgent(BaseModuleAgent[InitialResponseWriteout]):
    """
    Writeout Agent for configuring neutron simulation output parameters.
    
    Handles:
    - Output directory and file specifications
    - Data format and structure settings
    - Neutron detection parameters
    - Post-processing configurations
    """
    
    def __init__(self, model_name: str, tools: List[BaseTool] = []):
        """Initialize the Writeout Agent with base functionality"""
        super().__init__(model_name, tools)
    
    # =================
    # REQUIRED ABSTRACT METHODS
    # =================
    
    @property
    def name(self) -> str:
        return "Writeout Agent"
    
    @property
    def module_name(self) -> str:
        return "writeout"
    
    @property
    def welcome_message(self) -> str:
        return WRITEOUT_AGENT_WELCOME
    
    @property
    def system_prompt(self) -> str:
        return WRITEOUT_AGENT_PROMPT
    
    def get_initial_response_schema(self):
        return InitialResponseWriteout

    def get_result_key(self) -> str:
        return "writeout_params"
    
    # =================
    # CUSTOMIZATIONS FOR WRITEOUT MODULE
    # =================
    
    def get_default_setup_message(self) -> str:
        """Custom message for Writeout default setup"""
        return """
        You have chosen the default setup configuration. We will use optimal default 
        values for all parameters.
        
        For the writeout module, this means:
        - Standard output format (HDF5/ASCII)
        - Default data collection settings
        - Recommended file organization
        - Standard neutron detection parameters
        
        You only need to specify the output directory where the neutron data will be written.
        All other parameters will be set to recommended values that work well for most 
        neutron simulations.
        """
    
    def get_customize_setup_message(self) -> str:
        """Custom message for Writeout customization"""
        return """
        You have chosen the customize configuration. I'll help you configure the 
        writeout parameters step by step.
        
        We'll configure:
        - Output directory and file naming
        - Data format preferences (HDF5, ASCII, binary)
        - Neutron detection and recording settings
        - Post-processing and analysis options
        - File compression and optimization
        
        We'll start with the output directory, then you can choose which specific 
        parameters to modify from the defaults.
        """
    
    def parse_config_mode(self, response: InitialResponseWriteout) -> str:
        """Parse config mode from Writeout response"""
        return response.response
    
    def get_valid_config_modes(self) -> List[str]:
        """Writeout uses 'Customize' instead of 'Custom'"""
        return ['Default Setup', 'Customize']
    
    def validate_config_mode(self, config_mode: str) -> bool:
        """Validate Writeout configuration mode"""
        return config_mode in ['Default Setup', 'Customize']
    
    def get_completion_message(self) -> str:
        """Custom completion message for Writeout"""
        return """
        ✅ Writeout parameters configuration completed successfully!
        
        Your output specifications have been configured and validated.
        The simulation will write neutron data according to your settings,
        including proper file organization and data format preferences.
        """
    
    # =================
    # OVERRIDE ROUTING FOR WRITEOUT-SPECIFIC BEHAVIOR
    # =================
    
    def _route_after_init(self, state) -> str:
        """Custom routing for Writeout - handles 'Customize' mapping"""
        config_mode = state.get('config_mode', '')
        
        if not self.validate_config_mode(config_mode):
            print("We don't understand your choice.\nWe will end the conversation.")
            return "END"
        
        # Writeout specific mapping (note the difference from base implementation)
        if config_mode == 'Customize':
            return 'customize_setup'  # Note: different from base class logic
        elif config_mode == 'Default Setup':
            return 'default_setup'
        else:
            print("Invalid configuration mode selected.")
            return "END"


# =================
# FACTORY FUNCTION FOR EASY SETUP
# =================

async def create_writeout_agent(
    model_name: str = 'gpt-4o-mini-2024-07-18',
    mcp_tool_path: str = "/Users/az-ihsan/Documents/kerjaan-ihsan/post-doc/JueNA_knowledge_base/vitess-ai-agent/src/vitess_ai/mcp/writeout_module_tools.py"
) -> WriteoutAgent:
    """Factory function to create a Writeout agent with MCP tools"""
    
    client = MultiServerMCPClient({
        "validation": {
            "command": "python",
            "args": [mcp_tool_path],
            "transport": "stdio"
        }
    })
    
    tools = await client.get_tools()
    return WriteoutAgent(model_name=model_name, tools=tools)


# =================
# EXAMPLE USAGE
# =================

async def main():
    """Example usage of the migrated Writeout Agent"""
    print("🚀 Initializing Writeout Agent...")
    
    # Create agent using factory function
    agent = await create_writeout_agent()
    
    # Example conversation flow
    thread_id = "writeout_300"
    print("=== Neutron Simulation Writeout Parameters Configuration ===\n")
    
    print("🤖 Starting conversation...")
    result = await agent.run("", thread_id)
    
    print("\n" + "="*60)
    print("FINAL WRITEOUT PARAMS:")
    print("="*60)
    print(result)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())