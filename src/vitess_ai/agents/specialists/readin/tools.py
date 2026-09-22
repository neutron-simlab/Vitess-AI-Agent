"""What the read-in specialist may do."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool

from juena_core.agents.ask_user import build_ask_user_tool
from vitess_ai.agents.specialists.module_tools import (
    build_staged_files_tool,
    build_validation_tool,
    build_variants_tool,
)
from vitess_ai.schema import ReadInParameters

MODULE = "readin"
SPECIALIST_NAME = "readin-specialist"

#: Fields whose value must name a file the user actually staged.
#:
#: `sInstrInfIn` is here for a reason worth keeping: its schema default is the
#: bare name ``instrument.inf``, which VITESS would resolve against the run
#: directory, where no such file exists. Requiring a staged path turns a
#: confusing runtime failure into a validation error the specialist can act on.
UPLOAD_FIELDS = {
    "sInputFileName": "readin",
    "sInstrInfIn": "instrument",
    "sTraceFileName": "readin",
}


def build_tools(
    *, project_root: Path, gateway: Any, documentation_tools: Sequence[BaseTool] = ()
) -> list[BaseTool]:
    return [
        build_validation_tool(
            module=MODULE,
            model=ReadInParameters,
            project_root=project_root,
            upload_fields=UPLOAD_FIELDS,
        ),
        build_staged_files_tool(
            module=MODULE,
            gateway=gateway,
            project_root=project_root,
            upload_modules=("readin", "instrument"),
        ),
        build_ask_user_tool(SPECIALIST_NAME),
        *documentation_tools,
    ]


def build_sweep_tools(
    *, project_root: Path, gateway: Any, documentation_tools: Sequence[BaseTool] = ()
) -> list[BaseTool]:
    """The same checks, over a list, with no `ask_user`: nobody is watching."""
    return [
        build_variants_tool(
            module=MODULE,
            model=ReadInParameters,
            project_root=project_root,
            upload_fields=UPLOAD_FIELDS,
        ),
        build_staged_files_tool(
            module=MODULE,
            gateway=gateway,
            project_root=project_root,
            upload_modules=("readin", "instrument"),
        ),
        *documentation_tools,
    ]
