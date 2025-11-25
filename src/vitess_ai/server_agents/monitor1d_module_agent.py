"""
Monitor1D Module Agent - Monitor1D module agent

This agent implements the Monitor1D module functionality using the flat graph
architecture, enabling unified state management and
centralized interrupt handling.
"""

from typing import Type
from vitess_ai.server_agents.base_module_agent import BaseModuleAgent
from vitess_ai.prompts.monitor1d_module import MONITOR1D_AGENT_WELCOME, MONITOR1D_AGENT_DEFAULT_PROMPT, MONITOR1D_AGENT_CUSTOM_PROMPT
from vitess_ai.schema.monitor1d_module import InitialResponseMonitor1D


class Monitor1DModuleAgent(BaseModuleAgent[InitialResponseMonitor1D]):
    """
    Monitor1D module agent.
    
    This agent handles 1D monitor parameter configuration
    using a flat graph architecture.
    """
    
    @property
    def name(self) -> str:
        """Agent name"""
        return "Monitor1D Parameters"
    
    @property
    def module_name(self) -> str:
        """Module name"""
        return "monitor1d"
    
    @property
    def welcome_message(self) -> str:
        """Welcome message for the Monitor1D module"""
        return MONITOR1D_AGENT_WELCOME
    
    @property
    def default_prompt(self) -> str:
        """Default prompt for the Monitor1D module"""
        return MONITOR1D_AGENT_DEFAULT_PROMPT
    
    @property
    def custom_prompt(self) -> str:
        """Custom prompt for the Monitor1D module"""
        return MONITOR1D_AGENT_CUSTOM_PROMPT
    
    def get_initial_response_schema(self) -> Type[InitialResponseMonitor1D]:
        """Return the schema for initial response parsing"""
        return InitialResponseMonitor1D
    
    def get_result_key(self) -> str:
        """Return the key name for storing results"""
        return "monitor1d_params"
    
    def get_default_setup_message(self) -> str:
        """Message shown when user chooses default setup"""
        return """
        You have chosen the default setup configuration for Monitor1D parameters. 
        We will use optimal default values for most 1D monitor specifications. 
        You'll only need to specify essential parameters that require manual input.
        
        Default Monitor1D parameters include:
        - Standard monitor file output (monitor1D.dat)
        - Default binning configuration (100 bins)
        - Standard weight and filtering settings
        - Common parameter monitoring options
        
        The system will guide you through any parameters that need customization.
        """
    
    def get_customize_setup_message(self) -> str:
        """Message shown when user chooses customization"""
        return """
        You have chosen the customize configuration for Monitor1D parameters. 
        I'll help you configure the 1D monitor specifications step by step. 
        We'll go through each parameter category and you can choose which ones 
        to modify from the defaults.
        
        Configuration categories include:
        - Monitor file configuration
        - Parameter selection (x-axis parameter)
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
        
        message = f"""✅ Monitor1D Parameters configuration completed successfully!

Your 1D monitor specifications have been configured and validated. 
The system has generated the appropriate CLI parameters for the 
Monitor1D module that will be used in the simulation execution.

{next_message}"""
        return message

