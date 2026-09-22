"""What the capture_flux specialist may do."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from langchain_core.tools import BaseTool

from juena_core.agents.ask_user import build_ask_user_tool
from vitess_ai.agents.specialists.module_tools import (
    build_defaults_tool,
    build_validation_tool,
    build_variants_tool,
)
from vitess_ai.schema import CaptureFluxParameters

MODULE = "capture_flux"
SPECIALIST_NAME = "capture_flux-specialist"


def build_tools(
    *, project_root: Path, documentation_tools: Sequence[BaseTool] = ()
) -> list[BaseTool]:
    """No staged-files tool and no file name: this module reads and writes no file.

    Its result is two lines in the simulation log, which the server reads back
    into the run result.
    """
    return [
        build_defaults_tool(
            module=MODULE,
            model=CaptureFluxParameters,
            project_root=project_root,
        ),
        build_validation_tool(
            module=MODULE,
            model=CaptureFluxParameters,
            project_root=project_root,
        ),
        build_ask_user_tool(SPECIALIST_NAME),
        *documentation_tools,
    ]


def build_sweep_tools(
    *, project_root: Path, documentation_tools: Sequence[BaseTool] = ()
) -> list[BaseTool]:
    """The same checks, over a list, with no `ask_user`: nobody is watching."""
    return [
        build_variants_tool(
            module=MODULE,
            model=CaptureFluxParameters,
            project_root=project_root,
        ),
        *documentation_tools,
    ]
