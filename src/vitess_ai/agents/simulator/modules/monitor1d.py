"""
Monitor1D Module Agent - Monitor1D module agent

This agent implements the Monitor1D module functionality using the flat graph
architecture, enabling unified state management.
"""

from vitess_ai.agents.simulator.base_agent import BaseModuleAgent, ModuleBuilder
from vitess_ai.agents.simulator.prompts.monitor1d import MONITOR1D_AGENT_WELCOME, MONITOR1D_AGENT_DEFAULT_PROMPT, MONITOR1D_AGENT_CUSTOM_PROMPT


class Monitor1DModuleAgent(BaseModuleAgent):
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
    
    def get_result_key(self) -> str:
        """Return the key name for storing results"""
        return "monitor1d_params"
    
    @classmethod
    def register_with_supervisor(cls, supervisor) -> None:
        """Register the Monitor1D module with the supervisor"""
        module = ModuleBuilder.create(
            name="monitor1d",
            display_name="Monitor1D Parameters",
            description="Configure 1D monitor parameters for neutron detection",
            agent_class=cls,
            order=4
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
