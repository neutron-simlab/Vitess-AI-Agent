"""Build the eval_elast module specialist."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vitess_ai.agents.delegation import ModuleCompiledSubAgent
from vitess_ai.agents.specialists.eval_elast.tools import (
    MODULE,
    SPECIALIST_NAME,
    build_sweep_tools,
    build_tools,
)
from vitess_ai.agents.specialists.module_specialist import build_module_specialist
from vitess_ai.retrieval import specialist_rag_tools
from vitess_ai.schema import EvalElastParameters

DESCRIPTION = (
    "Configure the VITESS eval_elast module: a 1D spectrum of elastic scattering "
    "-- the intensity against scattering angle, momentum transfer Q, d-spacing "
    "or wavelength difference -- its range and binning, the wavelength (a "
    "reference wavelength or time of flight), and which neutrons count. "
    "Delegate here only when plan_simulation included eval_elast, which runs "
    "last. "
)


def build_eval_elast_specialist(
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
        prompt_package="vitess_ai.agents.specialists.eval_elast",
        model=EvalElastParameters,
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
