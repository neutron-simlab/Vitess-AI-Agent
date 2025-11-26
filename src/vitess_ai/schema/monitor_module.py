"""
Monitor Module Schemas

This module exports the initial response schemas for Monitor1D and Monitor2D modules.
The actual parameter schemas are defined in monitor1d_module.py and monitor2d_module.py.
"""

from vitess_ai.schema.monitor1d_module import InitialResponseMonitor1D
from vitess_ai.schema.monitor2d_module import InitialResponseMonitor2D

__all__ = ['InitialResponseMonitor1D', 'InitialResponseMonitor2D']

