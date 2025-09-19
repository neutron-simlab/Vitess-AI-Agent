"""
Guide Module Agent Server - Server-optimized guide module agent

This agent implements the guide module functionality using the flat graph
architecture for server mode, enabling unified state management and
centralized interrupt handling.
"""

from typing import Type, List
from pydantic import BaseModel, Field
from vitess_ai.server_agents.base_module_agent_server import BaseModuleAgentServer
from vitess_ai.prompts.guide_module import GUIDE_AGENT_WELCOME, GUIDE_AGENT_PROMPT


class GuideInitialResponse(BaseModel):
    """Schema for parsing initial user response in guide module"""
    response: str = Field(description="User's configuration choice: 'Default Setup', 'Customize', or 'Custom'")


class GuideModuleAgentServer(BaseModuleAgentServer[GuideInitialResponse]):
    """
    Server-optimized guide module agent.
    
    This agent handles neutron guide specifications and geometry
    configuration using a flat graph architecture for server mode.
    """
    
    @property
    def name(self) -> str:
        """Agent name"""
        return "Guide Parameters"
    
    @property
    def module_name(self) -> str:
        """Module name"""
        return "guide"
    
    @property
    def welcome_message(self) -> str:
        """Welcome message for the guide module"""
        return GUIDE_AGENT_WELCOME
    
    @property
    def system_prompt(self) -> str:
        """System prompt for the guide module"""
        return GUIDE_AGENT_PROMPT
    
    def get_initial_response_schema(self) -> Type[GuideInitialResponse]:
        """Return the schema for initial response parsing"""
        return GuideInitialResponse
    
    def get_result_key(self) -> str:
        """Return the key name for storing results"""
        return "guide_params"
    
    def get_default_setup_message(self) -> str:
        """Message shown when user chooses default setup"""
        return """
        You have chosen the default setup configuration for guide parameters. 
        We will use optimal default values for most neutron guide specifications. 
        You'll only need to specify essential parameters that require manual input.
        
        Default guide parameters include:
        - Standard guide geometry (rectangular cross-section)
        - Typical supermirror coating specifications
        - Common guide length and curvature settings
        - Standard guide alignment parameters
        
        The system will guide you through any parameters that need customization.
        """
    
    def get_customize_setup_message(self) -> str:
        """Message shown when user chooses customization"""
        return """
        You have chosen the customize configuration for guide parameters. 
        I'll help you configure the neutron guide specifications step by step. 
        We'll go through each parameter category and you can choose which ones 
        to modify from the defaults.
        
        Configuration categories include:
        - Guide geometry (dimensions, shape, etc.)
        - Supermirror coating specifications
        - Guide length and curvature parameters
        - Alignment and positioning settings
        - Performance optimization parameters
        
        Let's start with the guide geometry configuration.
        """
    
    def get_completion_message(self) -> str:
        """Message shown on successful completion"""
        return """
        ✅ Guide Parameters configuration completed successfully!
        
        Your neutron guide specifications have been configured and validated. 
        The system has generated the appropriate CLI parameters for the 
        guide module that will be used in the simulation execution.
        
        Next, we'll proceed to the writeout parameters configuration.
        """
