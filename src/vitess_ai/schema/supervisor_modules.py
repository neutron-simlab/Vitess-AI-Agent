"""
supervisor_modules.py - Pydantic Models and Enums for Supervisor
Contains all data models, enums, and type definitions
"""
from typing import Dict, List, Any, Optional
from enum import Enum
from pydantic import BaseModel, Field

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
    welcome_message: str = Field(
        default="""
🤖 **Neutron Simulation Configuration System**

Welcome! I'm your configurable Simulation Supervisor. I'll guide you through 
setting up your neutron simulation with the registered modules.

All modules are independent - you can configure them in any order and skip 
optional ones if needed.

Ready to begin? Type 'start' to begin the configuration process.
        """,
        description="Welcome message shown to users"
    )


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
    current_module: Optional[str] = None
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
        return json.dumps(self.dict(), indent=2)