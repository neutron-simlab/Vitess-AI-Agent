"""What the monitor1d specialist may do."""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import BaseTool

from juena_core.agents.ask_user import build_ask_user_tool
from vitess_ai.agents.specialists.module_specialist import (
    build_validation_tool,
    build_variants_tool,
)
from vitess_ai.schema import Monitor1DParameters

MODULE = "monitor1d"
SPECIALIST_NAME = "monitor1d-specialist"

#: `fMonitorFilename` names a file VITESS *writes*, into the run directory that
#: every module is already given. A plain name is all it can be: a path would
#: either escape the run or land where nothing looks for it, and the plot tools
#: (03/CP3) accept a plain name only.
OUTPUT_FILENAME_FIELDS = ("fMonitorFilename",)


def build_tools(*, project_root: Path) -> list[BaseTool]:
    """No staged-files tool: this module reads nothing the user uploaded."""
    return [
        build_validation_tool(
            module=MODULE,
            model=Monitor1DParameters,
            project_root=project_root,
            output_filename_fields=OUTPUT_FILENAME_FIELDS,
        ),
        build_ask_user_tool(SPECIALIST_NAME),
    ]


def build_sweep_tools(*, project_root: Path) -> list[BaseTool]:
    """The same checks, over a list, with no `ask_user`: nobody is watching."""
    return [
        build_variants_tool(
            module=MODULE,
            model=Monitor1DParameters,
            project_root=project_root,
            output_filename_fields=OUTPUT_FILENAME_FIELDS,
        ),
    ]
