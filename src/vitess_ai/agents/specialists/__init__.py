"""The five VITESS module specialists, listed explicitly.

Five imports and five entries. The catalog (03/CP2) is a data table about
physics modules and it deliberately no longer carries an ``agent_class`` or a
``tool_factory`` -- that field is why importing the catalog used to drag in the
whole agent framework, and why two hand-maintained copies of the executable
mapping existed to avoid it. Which agent configures which module is decided
here instead, in writing, which is JueNA's rule for agents unchanged: a package,
a builder import, one explicit entry. No discovery, no registry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deepagents.middleware.subagents import CompiledSubAgent

from vitess_ai.agents.specialists.guide import build_guide_specialist
from vitess_ai.agents.specialists.monitor1d import build_monitor1d_specialist
from vitess_ai.agents.specialists.monitor2d import build_monitor2d_specialist
from vitess_ai.agents.specialists.readin import build_readin_specialist
from vitess_ai.agents.specialists.writeout import build_writeout_specialist

__all__ = ["compile_module_specialists"]


def compile_module_specialists(
    *,
    project_root: Path,
    gateway: Any,
    summarizer_model: Any,
    fallback_models: list[Any],
) -> list[CompiledSubAgent]:
    """Compile all five, in the order the VITESS pipeline runs them.

    Only the two modules that read a user's file take the MCP gateway; the
    other three write files and have nothing staged to look at.
    """

    return [
        build_readin_specialist(
            project_root=project_root,
            gateway=gateway,
            summarizer_model=summarizer_model,
            fallback_models=fallback_models,
        ),
        build_guide_specialist(
            project_root=project_root,
            gateway=gateway,
            summarizer_model=summarizer_model,
            fallback_models=fallback_models,
        ),
        build_writeout_specialist(
            project_root=project_root,
            summarizer_model=summarizer_model,
            fallback_models=fallback_models,
        ),
        build_monitor1d_specialist(
            project_root=project_root,
            summarizer_model=summarizer_model,
            fallback_models=fallback_models,
        ),
        build_monitor2d_specialist(
            project_root=project_root,
            summarizer_model=summarizer_model,
            fallback_models=fallback_models,
        ),
    ]
