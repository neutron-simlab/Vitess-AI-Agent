"""
Writeout Module Agent - Writeout module agent

This agent implements the writeout module functionality using the flat graph
architecture, enabling unified state management.
"""

from vitess_ai.agents.simulator.base_agent import BaseModuleAgent, ModuleBuilder
from vitess_ai.agents.simulator.prompts.writeout import WRITEOUT_AGENT_WELCOME, WRITEOUT_AGENT_DEFAULT_PROMPT, WRITEOUT_AGENT_CUSTOM_PROMPT


class WriteoutModuleAgent(BaseModuleAgent):
    """
    Writeout module agent.
    
    This agent handles output settings and data formats configuration
    using a flat graph architecture.
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
    def default_prompt(self) -> str:
        """Default prompt for the writeout module"""
        return WRITEOUT_AGENT_DEFAULT_PROMPT
    
    @property
    def custom_prompt(self) -> str:
        """Custom prompt for the writeout module"""
        return WRITEOUT_AGENT_CUSTOM_PROMPT
    
    def get_result_key(self) -> str:
        """Return the key name for storing results"""
        return "writeout_params"
    
    @classmethod
    def register_with_supervisor(cls, supervisor) -> None:
        """Register the writeout module with the supervisor"""
        module = ModuleBuilder.create(
            name="writeout",
            display_name="Writeout Parameters",
            description="Configure output settings and data formats",
            agent_class=cls,
            order=3
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
            next_message = "All modules have been configured. The simulation will now be executed."
        
        message = f"""✅ Writeout Parameters configuration completed successfully!

Your output settings have been configured and validated. 
The system has generated the appropriate CLI parameters for the 
writeout module that will be used in the simulation execution.

{next_message}"""
        return message
