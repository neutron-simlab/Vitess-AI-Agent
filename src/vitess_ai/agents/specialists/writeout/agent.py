"""Build the writeout module specialist."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deepagents.middleware.subagents import CompiledSubAgent

from vitess_ai.agents.specialists.module_specialist import build_module_specialist
from vitess_ai.agents.specialists.writeout.tools import (
    MODULE,
    SPECIALIST_NAME,
    build_tools,
)
from vitess_ai.schema import WriteoutParameters

DESCRIPTION = (
    "Configure the VITESS writeout module: which trajectory columns are "
    "recorded, in what format, with which filters, and under what file "
    "name. It records the beam without disturbing it. Delegate here after "
    "the guide and before the monitors. "
)


def build_writeout_specialist(
    *,
    project_root: Path,
    summarizer_model: Any,
    fallback_models: list[Any],
) -> CompiledSubAgent:
    return build_module_specialist(
        module=MODULE,
        name=SPECIALIST_NAME,
        description=DESCRIPTION,
        prompt_package="vitess_ai.agents.specialists.writeout",
        model=WriteoutParameters,
        tools=build_tools(project_root=project_root),
        summarizer_model=summarizer_model,
        fallback_models=fallback_models,
    )
