"""Build the monitor2d module specialist."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deepagents.middleware.subagents import CompiledSubAgent

from vitess_ai.agents.specialists.module_specialist import build_module_specialist
from vitess_ai.agents.specialists.monitor2d.tools import (
    MODULE,
    SPECIALIST_NAME,
    build_tools,
)
from vitess_ai.schema import Monitor2DParameters

DESCRIPTION = (
    "Configure the VITESS monitor2D module: which two quantities are "
    "measured against each other, over what ranges, on what grid, and in "
    "which of the five file layouts. Delegate here last. "
)


def build_monitor2d_specialist(
    *,
    project_root: Path,
    summarizer_model: Any,
    fallback_models: list[Any],
) -> CompiledSubAgent:
    return build_module_specialist(
        module=MODULE,
        name=SPECIALIST_NAME,
        description=DESCRIPTION,
        prompt_package="vitess_ai.agents.specialists.monitor2d",
        model=Monitor2DParameters,
        tools=build_tools(project_root=project_root),
        summarizer_model=summarizer_model,
        fallback_models=fallback_models,
    )
