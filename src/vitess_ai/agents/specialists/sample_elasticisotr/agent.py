"""Build the sample_elasticisotr module specialist."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vitess_ai.agents.delegation import ModuleCompiledSubAgent
from vitess_ai.agents.specialists.module_specialist import build_module_specialist
from vitess_ai.agents.specialists.sample_elasticisotr.tools import (
    MODULE,
    SPECIALIST_NAME,
    build_sweep_tools,
    build_tools,
)
from vitess_ai.retrieval import specialist_rag_tools
from vitess_ai.schema import SampleElasticIsotrParameters

DESCRIPTION = (
    "Configure the VITESS sample_elasticisotr module: an elastic sample that "
    "scatters isotropically into a band of directions -- its shape (cuboid, "
    "cylinder, sphere, hollow cylinder) and size, its scattering and absorption "
    "coefficients, its position and orientation, the mean scattering direction "
    "and angular ranges, and the output frame. Delegate here only when "
    "plan_simulation included the sample, right after the guide. "
)


def build_sample_elasticisotr_specialist(
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
        prompt_package="vitess_ai.agents.specialists.sample_elasticisotr",
        model=SampleElasticIsotrParameters,
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
