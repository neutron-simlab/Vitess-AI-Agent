"""Build the screen module specialist."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vitess_ai.agents.delegation import ModuleCompiledSubAgent
from vitess_ai.agents.specialists.module_specialist import build_module_specialist
from vitess_ai.agents.specialists.screen.tools import (
    MODULE,
    SPECIALIST_NAME,
    build_sweep_tools,
    build_tools,
)
from vitess_ai.retrieval import specialist_rag_tools
from vitess_ai.schema import ScreenParameters

DESCRIPTION = (
    "Configure the VITESS screen module: an ideal detector surface, flat or "
    "cylindrical, that writes a 2D image of where the neutrons hit it -- its "
    "shape, size and distance from the frame origin, its angular range, its "
    "pixels and the image file. Delegate here only when plan_simulation "
    "included the screen, which runs after capture_flux. "
)


def build_screen_specialist(
    *,
    project_root: Path,
    summarizer_model: Any,
    fallback_models: list[Any],
    unattended: bool = False,
) -> ModuleCompiledSubAgent:
    """Compile this module's specialist.

    ``unattended`` compiles the copy a parameter sweep delegates to: it
    validates a list of configurations instead of one and has no
    ``ask_user``, because a sweep nobody is watching cannot have its
    question answered. Same prompt, same checks, same model.
    """
    documentation = specialist_rag_tools()
    return build_module_specialist(
        module=MODULE,
        name=SPECIALIST_NAME,
        description=DESCRIPTION,
        prompt_package="vitess_ai.agents.specialists.screen",
        model=ScreenParameters,
        tools=(
            build_sweep_tools(
                project_root=project_root, documentation_tools=documentation
            )
            if unattended
            else build_tools(
                project_root=project_root, documentation_tools=documentation
            )
        ),
        documentation_tools=documentation,
        summarizer_model=summarizer_model,
        fallback_models=fallback_models,
        unattended=unattended,
    )
