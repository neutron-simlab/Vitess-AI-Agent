"""
Monitor2D Module Agent - Monitor2D module agent

This agent implements the Monitor2D module functionality using the flat graph
architecture, enabling unified state management and
centralized interrupt handling.
"""

from typing import Type
from vitess_ai.server_agents.base_module_agent import BaseModuleAgent
from vitess_ai.prompts.monitor2d_module import MONITOR2D_AGENT_WELCOME, MONITOR2D_AGENT_DEFAULT_PROMPT, MONITOR2D_AGENT_CUSTOM_PROMPT
from vitess_ai.schema.monitor2d_module import InitialResponseMonitor2D


class Monitor2DModuleAgent(BaseModuleAgent[InitialResponseMonitor2D]):
    """
    Monitor2D module agent.
    
    This agent handles 2D monitor parameter configuration
    using a flat graph architecture.
    """
    
    @property
    def name(self) -> str:
        """Agent name"""
        return "Monitor2D Parameters"
    
    @property
    def module_name(self) -> str:
        """Module name"""
        return "monitor2d"
    
    @property
    def welcome_message(self) -> str:
        """Welcome message for the Monitor2D module"""
        return MONITOR2D_AGENT_WELCOME
    
    @property
    def default_prompt(self) -> str:
        """Default prompt for the Monitor2D module"""
        return MONITOR2D_AGENT_DEFAULT_PROMPT
    
    @property
    def custom_prompt(self) -> str:
        """Custom prompt for the Monitor2D module"""
        return MONITOR2D_AGENT_CUSTOM_PROMPT
    
    def get_initial_response_schema(self) -> Type[InitialResponseMonitor2D]:
        """Return the schema for initial response parsing"""
        return InitialResponseMonitor2D
    
    def get_result_key(self) -> str:
        """Return the key name for storing results"""
        return "monitor2d_params"
    
    def get_default_setup_message(self) -> str:
        """Message shown when user chooses default setup"""
        return """
        You have chosen the default setup configuration for Monitor2D parameters. 
        We will use optimal default values for most 2D monitor specifications. 
        You'll only need to specify essential parameters that require manual input.
        
        Default Monitor2D parameters include:
        - Standard monitor file output (monitor2D.dat)
        - Default binning configuration (100x100 bins)
        - Standard weight and filtering settings
        - Common parameter monitoring options
        
        The system will guide you through any parameters that need customization.
        """
    
    def get_customize_setup_message(self) -> str:
        """Message shown when user chooses customization"""
        return """
        You have chosen the customize configuration for Monitor2D parameters. 
        I'll help you configure the 2D monitor specifications step by step. 
        We'll go through each parameter category and you can choose which ones 
        to modify from the defaults.
        
        Configuration categories include:
        - Monitor file configuration and output format
        - Parameter selection (x-axis and y-axis parameters)
        - Binning and range configuration
        - Weight and filtering settings
        - Filter parameters
        - Polarisation analysis options
        
        Let's start with the parameter selection configuration.
        """
    
    def get_completion_message(self, state: dict = None) -> str:
        """Message shown on successful completion"""
        # Get next module using base class helper
        next_module_name = self._get_next_module_name(state)
        
        # Map module names to display names
        module_display_map = {
            'readin': 'Read-in Parameters',
            'guide': 'Guide Parameters',
            'monitor1d': 'Monitor1D Parameters',
            'monitor2d': 'Monitor2D Parameters',
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
        
        message = f"""✅ Monitor2D Parameters configuration completed successfully!

Your 2D monitor specifications have been configured and validated. 
The system has generated the appropriate CLI parameters for the 
Monitor2D module that will be used in the simulation execution.

{next_message}"""
        return message

