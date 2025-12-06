"""
supervisor_modules.py - Pydantic Models and Enums for Supervisor
Contains all data models, enums, and type definitions
"""
from typing import Dict, List, Any, Optional, Literal, Union, Type
from enum import Enum
from pydantic import BaseModel, Field, create_model

class SupervisorStage(str, Enum):
    """Overall supervisor stages"""
    WELCOME = "welcome"
    MODULE_EXECUTION = "module_execution"
    COMPLETION = "completion"
    ERROR = "error"


class SupervisorConfig(BaseModel):
    """Configuration for the supervisor agent"""
    provider:str = Field(default='openai')
    model: str = Field(default='gpt-4o-mini-2024-07-18')
    # Note: Welcome message is now handled by get_supervisor_welcome_message() in prompts/supervisor.py


class ExecutionPlan(BaseModel):
    """Execution plan for modules"""
    execution_order: List[str]
    total_modules: int
    modules_info: List[Dict[str, Any]] = Field(default=[])
    error: Optional[str] = None


class SupervisorStatus(BaseModel):
    """Current status of the supervisor"""
    status: str  # "not_initialized", "not_started", "in_progress", "completed", "error"
    current_stage: str
    completed_modules: List[str] = Field(default=[])
    execution_order: List[str] = Field(default=[])
    error_message: Optional[str] = None
    available_modules: List[Dict[str, Any]] = Field(default=[])


class ConfigurationExport(BaseModel):
    """Exported configuration structure"""
    simulation_configuration: Dict[str, Dict[str, Any]]
    metadata: Dict[str, Any]
    
    def to_json(self) -> str:
        """Export as JSON string"""
        import json
        return json.dumps(self.model_dump(), indent=2)


def create_routing_decision_model(module_names: List[str]) -> Type[BaseModel]:
    """
    Dynamically create a RoutingDecision Pydantic model with Literal types
    based on available module names.
    
    Args:
        module_names: List of registered module names (e.g., ["readin", "guide", "writeout"])
        
    Returns:
        A Pydantic model class with type-safe Literal fields for target_module
    """
    # Create all possible target module values: modules + "simulation" + None
    all_options = module_names + ["simulation"]
    valid_options = set(all_options + [None])
    
    # Create Literal type dynamically
    # For runtime creation, construct Literal with values
    if all_options:
        try:
            # Use __class_getitem__ to create Literal type (Python 3.9+)
            # Note: Literal expects values as separate arguments, but __class_getitem__ accepts tuple
            TargetModuleLiteral = Literal.__class_getitem__(tuple(all_options))
            # Make it Optional (Union with None)
            TargetModuleType = Union[TargetModuleLiteral, None]
        except (TypeError, AttributeError):
            # Fallback: use Optional[str] and add validator
            TargetModuleType = Optional[str]
    else:
        # Fallback if no modules
        TargetModuleType = Optional[str]
    
    # Create action type
    ActionType = Literal["route_to_module", "route_to_simulation"]
    
    # Define field annotations
    field_definitions = {
        'target_module': (
            TargetModuleType,
            Field(
                description=f"Module name to route to. Valid options: {all_options + ['None']}. Use None or 'simulation' for simulation routing.",
                default=None
            )
        ),
        'action': (
            ActionType,
            Field(
                description="Action type: 'route_to_module' to route to a module, 'route_to_simulation' to route to simulation",
                default="route_to_module"
            )
        ),
        'reasoning': (
            str,
            Field(
                description="LLM's reasoning for this routing decision, explaining why this route was chosen",
                default=""
            )
        ),
        'greeting_message': (
            Optional[str],
            Field(
                description="Optional greeting message for first interaction (replaces formal welcome message). Leave None if not first interaction.",
                default=None
            )
        )
    }
    
    # Create the model dynamically
    RoutingDecision = create_model(
        'RoutingDecision',
        **field_definitions
    )
    
    # Add docstring
    RoutingDecision.__doc__ = f"""
    Routing decision made by the supervisor LLM.
    
    Dynamically created with module options: {module_names}
    Valid target_module values: {all_options + ['None']}
    """
    
    return RoutingDecision