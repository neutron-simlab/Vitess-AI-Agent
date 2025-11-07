"""
Guide Module Agent - Guide module agent

This agent implements the guide module functionality using the flat graph
architecture, enabling unified state management and
centralized interrupt handling.
"""

from typing import Type
from vitess_ai.server_agents.base_module_agent import BaseModuleAgent
from vitess_ai.prompts.guide_module import GUIDE_AGENT_WELCOME, GUIDE_AGENT_DEFAULT_PROMPT, GUIDE_AGENT_CUSTOM_PROMPT
from vitess_ai.schema.guide_module import InitialResponseGuide


class GuideModuleAgent(BaseModuleAgent[InitialResponseGuide]):
    """
    Guide module agent.
    
    This agent handles neutron guide specifications and geometry
    configuration using a flat graph architecture.
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
    def default_prompt(self) -> str:
        """Default prompt for the guide module"""
        return GUIDE_AGENT_DEFAULT_PROMPT
    
    @property
    def custom_prompt(self) -> str:
        """Custom prompt for the guide module"""
        return GUIDE_AGENT_CUSTOM_PROMPT
    
    def get_initial_response_schema(self) -> Type[InitialResponseGuide]:
        """Return the schema for initial response parsing"""
        return InitialResponseGuide
    
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
    
    def get_completion_message(self, state: dict = None) -> str:
        """Message shown on successful completion"""
        # Get next module using base class helper
        next_module_name = self._get_next_module_name(state)
        
        # Map module names to display names
        module_display_map = {
            'readin': 'Read-in Parameters',
            'guide': 'Guide Parameters',
            'writeout': 'Writeout Parameters'
        }
        
        if next_module_name:
            next_module_display = module_display_map.get(
                next_module_name, 
                next_module_name.replace('_', ' ').title()
            )
            next_message = f"Next, we'll proceed to the {next_module_display.lower()} configuration."
        else:
            next_message = "Next, we'll proceed to the simulation execution."
        
        message = f"""✅ Guide Parameters configuration completed successfully!

Your neutron guide specifications have been configured and validated. 
The system has generated the appropriate CLI parameters for the 
guide module that will be used in the simulation execution.

{next_message}"""
        return message

