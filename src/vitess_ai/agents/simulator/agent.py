"""
Simulator Agent module.

Re-exports SupervisorAgent as SimulatorAgent for the modular agents API.
The actual implementation lives in vitess_ai.server_agents.supervisor.
"""

from vitess_ai.agents.simulator.supervisor import (
    SupervisorAgent,
    create_default_supervisor as _create_default_supervisor,
)

# Alias for modular API
SimulatorAgent = SupervisorAgent


async def create_default_simulator(*args, **kwargs):
    """Create a default simulator agent with standard modules."""
    return await _create_default_supervisor(*args, **kwargs)


__all__ = ["SimulatorAgent", "create_default_simulator"]
