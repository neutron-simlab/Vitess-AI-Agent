"""Build the read-in module specialist."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deepagents.middleware.subagents import CompiledSubAgent

from vitess_ai.agents.specialists.module_specialist import build_module_specialist
from vitess_ai.agents.specialists.readin.tools import (
    MODULE,
    SPECIALIST_NAME,
    build_tools,
)
from vitess_ai.schema import ReadInParameters

DESCRIPTION = (
    "Configure the VITESS read_in module: which uploaded neutron trajectory "
    "files the simulation reads, their weights, the instrument file and the "
    "input format. This is the first module of every pipeline -- delegate here "
    "before any other module, because everything downstream reads its output."
)


def build_readin_specialist(
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
        prompt_package="vitess_ai.agents.specialists.readin",
        model=ReadInParameters,
        tools=build_tools(project_root=project_root, gateway=gateway),
        summarizer_model=summarizer_model,
        fallback_models=fallback_models,
    )
