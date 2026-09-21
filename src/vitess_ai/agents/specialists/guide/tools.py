"""What the guide specialist may do."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool

from juena_core.agents.ask_user import build_ask_user_tool
from vitess_ai.agents.specialists.module_specialist import (
    build_defaults_tool,
    build_staged_files_tool,
    build_validation_tool,
    build_variants_tool,
)
from vitess_ai.schema import GuideParameters

MODULE = "guide"
SPECIALIST_NAME = "guide-specialist"

#: Optional: an empty `ShapeFileName` means "no guide file, use the dimensions",
#: and the converter omits `-S` entirely. Only a value that is set has to name a
#: staged upload.
UPLOAD_FIELDS = {"ShapeFileName": "guide"}


def build_tools(
    *, project_root: Path, gateway: Any, documentation_tools: Sequence[BaseTool] = ()
) -> list[BaseTool]:
    return [
        build_defaults_tool(
            module=MODULE,
            model=GuideParameters,
            project_root=project_root,
            upload_fields=UPLOAD_FIELDS,
        ),
        build_validation_tool(
            module=MODULE,
            model=GuideParameters,
            project_root=project_root,
            upload_fields=UPLOAD_FIELDS,
        ),
        build_staged_files_tool(
            module=MODULE, gateway=gateway, project_root=project_root
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
            model=GuideParameters,
            project_root=project_root,
            upload_fields=UPLOAD_FIELDS,
        ),
        build_staged_files_tool(
            module=MODULE, gateway=gateway, project_root=project_root
        ),
        *documentation_tools,
    ]
