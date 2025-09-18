"""
Writeout Module Agent Server - Server-optimized writeout module agent

This agent implements the writeout module functionality using the flat graph
architecture for server mode, enabling unified state management and
centralized interrupt handling.
"""

from typing import Type, List
from pydantic import BaseModel, Field
from vitess_ai.server_agents.base_module_agent_server import BaseModuleAgentServer
from vitess_ai.prompts.writeout_module import WRITEOUT_AGENT_WELCOME, WRITEOUT_AGENT_PROMPT


class WriteoutInitialResponse(BaseModel):
    """Schema for parsing initial user response in writeout module"""
    response: str = Field(description="User's configuration choice: 'Default Setup', 'Customize', or 'Custom'")


class WriteoutModuleAgentServer(BaseModuleAgentServer[WriteoutInitialResponse]):
    """
    Server-optimized writeout module agent.
    
    This agent handles output settings and data formats configuration
    using a flat graph architecture for server mode.
    """
    
    @property
    def name(self) -> str:
        """Agent name"""
        return "Writeout Parameters"
    
    @property
    def module_name(self) -> str:
        """Module name"""
        return "writeout"
    
    @property
    def welcome_message(self) -> str:
        """Welcome message for the writeout module"""
        return WRITEOUT_AGENT_WELCOME
    
    @property
    def system_prompt(self) -> str:
        """System prompt for the writeout module"""
        return WRITEOUT_AGENT_PROMPT
    
    def get_initial_response_schema(self) -> Type[WriteoutInitialResponse]:
        """Return the schema for initial response parsing"""
        return WriteoutInitialResponse
    
    def get_result_key(self) -> str:
        """Return the key name for storing results"""
        return "writeout_params"
    
    def get_default_setup_message(self) -> str:
        """Message shown when user chooses default setup"""
        return """
        You have chosen the default setup configuration for writeout parameters. 
        We will use optimal default values for most output settings. 
        You'll only need to specify essential parameters that require manual input.
        
        Default writeout parameters include:
        - Standard data output formats (Nexus, ASCII)
        - Typical file naming conventions
        - Common data compression settings
        - Standard metadata inclusion options
        
        The system will guide you through any parameters that need customization.
        """
    
    def get_customize_setup_message(self) -> str:
        """Message shown when user chooses customization"""
        return """
        You have chosen the customize configuration for writeout parameters. 
        I'll help you configure the output settings step by step. 
        We'll go through each parameter category and you can choose which ones 
        to modify from the defaults.
        
        Configuration categories include:
        - Data output formats (Nexus, ASCII, binary, etc.)
        - File naming and organization
        - Data compression and storage options
        - Metadata and annotation settings
        - Performance and optimization parameters
        
        Let's start with the data output format configuration.
        """
    
    def get_completion_message(self) -> str:
        """Message shown on successful completion"""
        return """
        ✅ Writeout Parameters configuration completed successfully!
        
        Your output settings have been configured and validated. 
        The system has generated the appropriate CLI parameters for the 
        writeout module that will be used in the simulation execution.
        
        All modules have been configured. The simulation will now be executed.
        """
