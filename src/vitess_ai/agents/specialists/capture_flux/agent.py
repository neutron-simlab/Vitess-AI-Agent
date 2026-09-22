"""Build the capture_flux module specialist."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vitess_ai.agents.delegation import ModuleCompiledSubAgent
from vitess_ai.agents.specialists.capture_flux.tools import (
    MODULE,
    SPECIALIST_NAME,
    build_sweep_tools,
    build_tools,
)
from vitess_ai.agents.specialists.module_specialist import build_module_specialist
from vitess_ai.retrieval import specialist_rag_tools
from vitess_ai.schema import CaptureFluxParameters

DESCRIPTION = (
    "Configure the VITESS capture_flux module: the gold-foil capture flux "
    "(the flux weighted by lambda / lambda_ref, as a gold-foil activation "
    "measures it) -- the reference wavelength, the foil's shape, size and "
    "position, and an optional wavelength window. It passes every neutron on "
    "unchanged. Delegate here last, after the monitors. "
)


def build_capture_flux_specialist(
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
        prompt_package="vitess_ai.agents.specialists.capture_flux",
        model=CaptureFluxParameters,
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
