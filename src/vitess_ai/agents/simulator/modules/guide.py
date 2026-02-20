"""
Guide Module Agent - Guide module agent

This agent implements the guide module functionality using the flat graph
architecture, enabling unified state management.
"""

from vitess_ai.agents.simulator.base_agent import BaseModuleAgent, ModuleBuilder
from vitess_ai.agents.simulator.prompts.guide import GUIDE_AGENT_WELCOME, GUIDE_AGENT_DEFAULT_PROMPT, GUIDE_AGENT_CUSTOM_PROMPT
from vitess_ai.core.config import global_config


class GuideModuleAgent(BaseModuleAgent):
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
    
    def get_result_key(self) -> str:
        """Return the key name for storing results"""
        return "guide_params"
    
    @classmethod
    def register_with_supervisor(cls, supervisor) -> None:
        """Register the guide module with the supervisor"""
        module = ModuleBuilder.create(
            name="guide",
            display_name="Guide Parameters",
            description="Configure neutron guide specifications and geometry",
            agent_class=cls,
            order=2
        )
        supervisor.register_module(module)
    
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

