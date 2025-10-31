"""
ReadIn Module Agent - Readin module agent

This agent implements the readin module functionality using the flat graph
architecture, enabling unified state management and
centralized interrupt handling.
"""

from typing import Type
from vitess_ai.server_agents.base_module_agent import BaseModuleAgent
from vitess_ai.prompts.readin_module import READIN_AGENT_WELCOME, READIN_AGENT_PROMPT
from vitess_ai.schema.readin_module import InitialResponseReadIn


class ReadInModuleAgent(BaseModuleAgent[InitialResponseReadIn]):
    """
    Readin module agent.
    
    This agent handles neutron input parameters and initial conditions
    configuration using a flat graph architecture.
    """
    
    @property
    def name(self) -> str:
        """Agent name"""
        return "Read-in Parameters"
    
    @property
    def module_name(self) -> str:
        """Module name"""
        return "readin"
    
    @property
    def welcome_message(self) -> str:
        """Welcome message for the readin module"""
        return READIN_AGENT_WELCOME
    
    @property
    def system_prompt(self) -> str:
        """System prompt for the readin module"""
        return READIN_AGENT_PROMPT
    
    def get_initial_response_schema(self) -> Type[InitialResponseReadIn]:
        """Return the schema for initial response parsing"""
        return InitialResponseReadIn
    
    def get_result_key(self) -> str:
        """Return the key name for storing results"""
        return "readin_params"
    
    def get_default_setup_message(self) -> str:
        """Message shown when user chooses default setup"""
        return """
        You have chosen the default setup configuration for readin parameters. 
        We will use optimal default values for most neutron input parameters. 
        You'll only need to specify essential parameters that require manual input.
        
        Default readin parameters include:
        - Standard neutron source configuration
        - Typical energy range settings
        - Common beam geometry parameters
        - Standard time-of-flight settings
        
        The system will guide you through any parameters that need customization.
        """
    
    def get_customize_setup_message(self) -> str:
        """Message shown when user chooses customization"""
        return """
        You have chosen the customize configuration for readin parameters. 
        I'll help you configure the neutron input parameters step by step. 
        We'll go through each parameter category and you can choose which ones 
        to modify from the defaults.
        
        Configuration categories include:
        - Neutron source parameters (energy, flux, etc.)
        - Beam geometry (divergence, size, etc.)
        - Time-of-flight settings
        - Sample environment parameters
        - Data acquisition settings
        
        Let's start with the neutron source configuration.
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
        
        message = f"""Read-in Parameters configuration completed successfully!

Your neutron input parameters have been configured and validated. 
The system has generated the appropriate CLI parameters for the 
readin module that will be used in the simulation execution.

{next_message}"""
        return message

