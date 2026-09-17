"""Build the guide module specialist."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deepagents.middleware.subagents import CompiledSubAgent

from vitess_ai.agents.specialists.guide.tools import (
    MODULE,
    SPECIALIST_NAME,
    build_tools,
)
from vitess_ai.agents.specialists.module_specialist import build_module_specialist
from vitess_ai.schema import GuideParameters

DESCRIPTION = (
    "Configure the VITESS guide_parallel module: the neutron guide's entrance "
    "and exit cross-section, its length, and the m-value of its coating -- the "
    "optics that carry the beam from the source to the sample. Delegate here "
    "after read-in and before writeout."
)


def build_guide_specialist(
    *,
    project_root: Path,
    gateway: Any,
    summarizer_model: Any,
    fallback_models: list[Any],
) -> CompiledSubAgent:
    return build_module_specialist(
        module=MODULE,
        name=SPECIALIST_NAME,
        description=DESCRIPTION,
        prompt_package="vitess_ai.agents.specialists.guide",
        model=GuideParameters,
        tools=build_tools(project_root=project_root, gateway=gateway),
        summarizer_model=summarizer_model,
        fallback_models=fallback_models,
    )
