"""
Simulator prompts.

System prompts for the supervisor and module agents.
"""

from vitess_ai.agents.simulator.prompts.supervisor import (
    get_simulation_execution_prompt,
    get_post_simulation_response_prompt,
    get_supervisor_routing_prompt,
)
from vitess_ai.agents.simulator.prompts.readin import (
    READIN_AGENT_WELCOME,
    READIN_AGENT_DEFAULT_PROMPT,
    READIN_AGENT_CUSTOM_PROMPT,
)
from vitess_ai.agents.simulator.prompts.guide import (
    GUIDE_AGENT_WELCOME,
    GUIDE_AGENT_DEFAULT_PROMPT,
    GUIDE_AGENT_CUSTOM_PROMPT,
)
from vitess_ai.agents.simulator.prompts.writeout import (
    WRITEOUT_AGENT_WELCOME,
    WRITEOUT_AGENT_DEFAULT_PROMPT,
    WRITEOUT_AGENT_CUSTOM_PROMPT,
)
from vitess_ai.agents.simulator.prompts.monitor1d import (
    MONITOR1D_AGENT_WELCOME,
    MONITOR1D_AGENT_DEFAULT_PROMPT,
    MONITOR1D_AGENT_CUSTOM_PROMPT,
)
from vitess_ai.agents.simulator.prompts.monitor2d import (
    MONITOR2D_AGENT_WELCOME,
    MONITOR2D_AGENT_DEFAULT_PROMPT,
    MONITOR2D_AGENT_CUSTOM_PROMPT,
)

__all__ = [
    # Supervisor prompts
    "get_simulation_execution_prompt",
    "get_post_simulation_response_prompt",
    "get_supervisor_routing_prompt",
    # ReadIn
    "READIN_AGENT_WELCOME",
    "READIN_AGENT_DEFAULT_PROMPT",
    "READIN_AGENT_CUSTOM_PROMPT",
    # Guide
    "GUIDE_AGENT_WELCOME",
    "GUIDE_AGENT_DEFAULT_PROMPT",
    "GUIDE_AGENT_CUSTOM_PROMPT",
    # WriteOut
    "WRITEOUT_AGENT_WELCOME",
    "WRITEOUT_AGENT_DEFAULT_PROMPT",
    "WRITEOUT_AGENT_CUSTOM_PROMPT",
    # Monitor1D
    "MONITOR1D_AGENT_WELCOME",
    "MONITOR1D_AGENT_DEFAULT_PROMPT",
    "MONITOR1D_AGENT_CUSTOM_PROMPT",
    # Monitor2D
    "MONITOR2D_AGENT_WELCOME",
    "MONITOR2D_AGENT_DEFAULT_PROMPT",
    "MONITOR2D_AGENT_CUSTOM_PROMPT",
]
