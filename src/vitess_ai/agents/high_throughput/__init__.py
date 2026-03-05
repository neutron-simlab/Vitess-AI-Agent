"""
High-Throughput Agent package.

The High-Throughput Agent enables batch simulation workflows with parameter
variations. It generates simulation matrices, validates parameters through
module subagents, and executes simulations sequentially via MCP.
"""

from vitess_ai.agents.high_throughput.agent import HighThroughputAgent, create_default_high_throughput
from vitess_ai.agents.high_throughput.tools import (
    get_shared_high_throughput_tools,
    get_sim_runner_tools,
)

__all__ = [
    "HighThroughputAgent",
    "create_default_high_throughput",
    "get_shared_high_throughput_tools",
    "get_sim_runner_tools",
]
