"""
Simulator module tools.

Tools for each Vitess simulation module.
"""

from vitess_ai.agents.simulator.tools.readin import (
    get_readin_tools,
    readin_params_to_cli,
)
from vitess_ai.agents.simulator.tools.guide import (
    get_guide_tools,
    guide_params_to_cli,
)
from vitess_ai.agents.simulator.tools.writeout import (
    get_writeout_tools,
    writeout_params_to_cli,
)
from vitess_ai.agents.simulator.tools.monitor import (
    get_monitor_tools,
    monitor1d_params_to_cli,
    monitor2d_params_to_cli,
)

# Aliases for individual monitor tool access
get_monitor1d_tools = get_monitor_tools
get_monitor2d_tools = get_monitor_tools

__all__ = [
    "get_readin_tools",
    "readin_params_to_cli",
    "get_guide_tools",
    "guide_params_to_cli",
    "get_writeout_tools",
    "writeout_params_to_cli",
    "get_monitor_tools",
    "get_monitor1d_tools",
    "get_monitor2d_tools",
    "monitor1d_params_to_cli",
    "monitor2d_params_to_cli",
]
