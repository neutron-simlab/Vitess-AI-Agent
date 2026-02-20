"""
Simulator Agent package.

The Simulator Agent orchestrates Vitess module workflows using a supervisor pattern.
It coordinates module-specific subagents (readin, guide, writeout, monitors) to
configure and execute neutron simulations.

Structure:
- supervisor.py: Main SupervisorAgent orchestrator
- base_agent.py: BaseModuleAgent for module agents
- state.py: UnifiedState for graph state management
- middleware.py: Message filtering and thread ID middleware
- tool_wrapper.py: Tool wrapping utilities
- modules/: Module-specific agents (readin, guide, writeout, monitor1d, monitor2d)
- prompts/: System prompts for supervisor and modules
- tools/: Module-specific tools with CLI generation
"""

from vitess_ai.agents.simulator.supervisor import (
    SupervisorAgent,
    create_default_supervisor,
)
from vitess_ai.agents.simulator.base_agent import BaseModuleAgent, ModuleMetadata
from vitess_ai.agents.simulator.state import UnifiedState

# Alias for modular API
SimulatorAgent = SupervisorAgent
create_default_simulator = create_default_supervisor

__all__ = [
    "SupervisorAgent",
    "SimulatorAgent",
    "create_default_supervisor",
    "create_default_simulator",
    "BaseModuleAgent",
    "ModuleMetadata",
    "UnifiedState",
]
