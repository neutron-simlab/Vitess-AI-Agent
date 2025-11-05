"""
Unified State Management for Server Agents

This module defines the unified state structure that is shared between
the supervisor and all module agents in server mode. This enables
seamless state sharing and centralized interrupt handling.
"""

from __future__ import annotations

from typing import Dict, List, Any, Optional
from enum import Enum
from pydantic import BaseModel
from langgraph.graph import MessagesState
from vitess_ai.schema.base import FillingStage
from vitess_ai.schema.supervisor import SupervisorStage


# =================
# MODULE RESULT CLASSES
# =================

class ModuleStatus(str, Enum):
    """Status of individual modules"""
    COMPLETED = "completed"


class ModuleResult(BaseModel):
    """Result from a completed module agent"""
    module_name: str
    status: ModuleStatus
    parameters: Optional[Dict[str, Any]] = None
    cli_parameters: Optional[str] = None
    error_message: Optional[str] = None
    execution_time: Optional[float] = None
    thread_id: Optional[str] = None
    user_id: Optional[str] = None


class UnifiedState(MessagesState):
    """
    Unified state structure shared between supervisor and all module agents.
    
    This state combines supervisor-level coordination with module-level
    execution details, enabling seamless state sharing during interrupts.
    
    Note: MessagesState is a pre-built TypedDict from LangGraph 1.x that
    automatically handles message accumulation. Additional fields are
    added using type annotations (compatible with LangGraph 1.x).
    
    Defaults should be provided when creating initial state, not in TypedDict
    field definitions (TypedDict doesn't support Pydantic Field defaults).
    """
    
    # Supervisor-level fields
    current_stage: SupervisorStage
    module_results: Dict[str, ModuleResult]
    execution_order: List[str]
    pending_modules: List[str]
    current_agent_thread: str
    user_preferences: Dict[str, Any]
    cli_generation_ready: bool
    cli_command: Optional[str]
    simulation_finish: Optional[bool]
    # Memory / context fields (e.g., running summary)
    context: Dict[str, Any]
    
    # Module-level fields (shared across all modules)
    current_module: Optional[str]
    module_stage: Optional[FillingStage]
    config_mode: str
    validation_status: Optional[bool]
    parameters: Any
    cli_parameters: str
    
    # Common fields
    thread_id: Optional[str]
    user_id: Optional[str]
    error_message: Optional[str]
    
    
    def get_current_module_result(self) -> Optional[ModuleResult]:
        """Get the result for the current module if it exists."""
        if self.current_module and self.current_module in self.module_results:
            return self.module_results[self.current_module]
        return None
    
    def set_current_module_result(self, result: ModuleResult) -> None:
        """Set the result for the current module."""
        if self.current_module:
            updated_results = self.module_results.copy()
            updated_results[self.current_module] = result
            self.module_results = updated_results
    
    def is_module_completed(self, module_name: str) -> bool:
        """Check if a specific module is completed."""
        if module_name in self.module_results:
            result = self.module_results[module_name]
            return result.status == "completed"
        return False
    
    def get_completed_modules(self) -> List[str]:
        """Get list of completed module names."""
        return [
            name for name, result in self.module_results.items()
            if result.status == "completed"
        ]
    
    def get_next_module(self) -> Optional[str]:
        """Get the next module to execute based on execution order."""
        completed = self.get_completed_modules()
        for module in self.execution_order:
            if module not in completed:
                return module
        return None
    
    def is_all_modules_completed(self) -> bool:
        """Check if all modules in execution order are completed."""
        completed = self.get_completed_modules()
        return len(completed) == len(self.execution_order)
    
    def reset_module_state(self) -> None:
        """Reset module-specific state fields."""
        self.current_module = None
        self.module_stage = None
        self.config_mode = ""
        self.validation_status = None
        self.parameters = None
        self.cli_parameters = ""
        self.error_message = None
