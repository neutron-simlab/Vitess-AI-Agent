"""Build the monitor1d module specialist."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deepagents.middleware.subagents import CompiledSubAgent

from vitess_ai.agents.specialists.module_specialist import build_module_specialist
from vitess_ai.agents.specialists.monitor1d.tools import (
    MODULE,
    SPECIALIST_NAME,
    build_tools,
)
from vitess_ai.schema import Monitor1DParameters

DESCRIPTION = (
    "Configure the VITESS monitor1D module: which single quantity is "
    "measured -- wavelength, a position, a divergence, time of flight -- "
    "over what range and in how many bins. Delegate here after writeout. "
)


def build_monitor1d_specialist(
    *,
    project_root: Path,
    summarizer_model: Any,
    fallback_models: list[Any],
) -> CompiledSubAgent:
    return build_module_specialist(
        module=MODULE,
        name=SPECIALIST_NAME,
        description=DESCRIPTION,
        prompt_package="vitess_ai.agents.specialists.monitor1d",
        model=Monitor1DParameters,
        tools=build_tools(project_root=project_root),
        summarizer_model=summarizer_model,
        fallback_models=fallback_models,
    )
