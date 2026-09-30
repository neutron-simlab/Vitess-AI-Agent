"""The nine VITESS module specialists, listed one by one.

Nine imports and nine entries. The module catalog is a table of data about the
physics modules, and on purpose it no longer names each module's agent
(``agent_class`` or ``tool_factory``). That field is why reading the catalog
used to load the whole agent framework, and why two hand-kept copies of the
module-to-program list existed to avoid it. Which agent sets up which module is
decided here instead, written out, following JueNA's rule for agents: a
package, an import of its builder, one explicit entry. Nothing is discovered
automatically.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vitess_ai.agents.delegation import ModuleCompiledSubAgent
from vitess_ai.agents.specialists.capture_flux import build_capture_flux_specialist
from vitess_ai.agents.specialists.eval_elast import build_eval_elast_specialist
from vitess_ai.agents.specialists.guide import build_guide_specialist
from vitess_ai.agents.specialists.monitor1d import build_monitor1d_specialist
from vitess_ai.agents.specialists.monitor2d import build_monitor2d_specialist
from vitess_ai.agents.specialists.readin import build_readin_specialist
from vitess_ai.agents.specialists.sample_elasticisotr import (
    build_sample_elasticisotr_specialist,
)
from vitess_ai.agents.specialists.screen import build_screen_specialist
from vitess_ai.agents.specialists.writeout import build_writeout_specialist

__all__ = ["compile_module_specialists", "compile_sweep_specialists"]


def compile_module_specialists(
    *,
    project_root: Path,
    gateway: Any,
    summarizer_model: Any,
    fallback_models: list[Any],
    unattended: bool = False,
) -> list[ModuleCompiledSubAgent]:
    """Compile all nine, in the order the VITESS pipeline runs them.

    Only the two modules that read a user's file take the MCP gateway; the
    other seven read no staged file and have nothing to look at. The sample,
    the screen and eval_elast run only in a simulation that asks for them, but
    their specialists are always compiled: whether one is delegated to is the
    plan's decision, not this list's.

    ``unattended`` compiles the sweep copies -- see
    :func:`compile_sweep_specialists`.
    """

    return [
        build_readin_specialist(
            project_root=project_root,
            gateway=gateway,
            summarizer_model=summarizer_model,
            fallback_models=fallback_models,
            unattended=unattended,
        ),
        build_guide_specialist(
            project_root=project_root,
            gateway=gateway,
            summarizer_model=summarizer_model,
            fallback_models=fallback_models,
            unattended=unattended,
        ),
        build_sample_elasticisotr_specialist(
            project_root=project_root,
            summarizer_model=summarizer_model,
            fallback_models=fallback_models,
            unattended=unattended,
        ),
        build_writeout_specialist(
            project_root=project_root,
            summarizer_model=summarizer_model,
            fallback_models=fallback_models,
            unattended=unattended,
        ),
        build_monitor1d_specialist(
            project_root=project_root,
            summarizer_model=summarizer_model,
            fallback_models=fallback_models,
            unattended=unattended,
        ),
        build_monitor2d_specialist(
            project_root=project_root,
            summarizer_model=summarizer_model,
            fallback_models=fallback_models,
            unattended=unattended,
        ),
        build_capture_flux_specialist(
            project_root=project_root,
            summarizer_model=summarizer_model,
            fallback_models=fallback_models,
            unattended=unattended,
        ),
        build_screen_specialist(
            project_root=project_root,
            summarizer_model=summarizer_model,
            fallback_models=fallback_models,
            unattended=unattended,
        ),
        build_eval_elast_specialist(
            project_root=project_root,
            summarizer_model=summarizer_model,
            fallback_models=fallback_models,
            unattended=unattended,
        ),
    ]


def compile_sweep_specialists(
    *,
    project_root: Path,
    gateway: Any,
    summarizer_model: Any,
    fallback_models: list[Any],
) -> list[ModuleCompiledSubAgent]:
    """The same nine, compiled again for a parameter sweep.

    A second compile, not a second set of agents: `build_chat_model` caches on
    (provider, model, temperature), so this costs tool objects and a prompt
    string. juena-chatbot does the same for its background research copies, and
    for the same reason -- the two sets must stay one graph apart, because an
    unattended specialist that could still reach `ask_user` would block forever
    on nobody.

    The sweep copies differ in exactly two ways: their validation tool takes a
    list, and they have no `ask_user`. The prompt, the model, the checks and the
    schema are the guided specialists'.
    """

    return compile_module_specialists(
        project_root=project_root,
        gateway=gateway,
        summarizer_model=summarizer_model,
        fallback_models=fallback_models,
        unattended=True,
    )
