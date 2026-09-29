"""What the sample_elasticisotr specialist may do."""

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
from vitess_ai.schema import SampleElasticIsotrParameters
from vitess_ai.schema.sample_elasticisotr_module import SHIPPED_DEFAULT

MODULE = "sample_elasticisotr"
SPECIALIST_NAME = "sample_elasticisotr-specialist"

#: `pSmplFileName` names the sample parameter file, which VITESS looks for in
#: the run directory every module is given. Nothing is ever staged there, so
#: the name is only there to satisfy the module (it refuses to start without
#: one), and a plain name is all it may be.
PLAIN_FILENAME_FIELDS = ("pSmplFileName",)


def build_tools(
    *, project_root: Path, documentation_tools: Sequence[BaseTool] = ()
) -> list[BaseTool]:
    """No staged-files tool: this module reads nothing the user uploaded.

    The defaults tool records VITESS's own default sample rather than the
    schema defaults, which are the C initialisers and do not run.
    """
    return [
        build_defaults_tool(
            module=MODULE,
            model=SampleElasticIsotrParameters,
            project_root=project_root,
            output_filename_fields=PLAIN_FILENAME_FIELDS,
            defaults=SHIPPED_DEFAULT,
        ),
        build_validation_tool(
            module=MODULE,
            model=SampleElasticIsotrParameters,
            project_root=project_root,
            output_filename_fields=PLAIN_FILENAME_FIELDS,
        ),
        build_ask_user_tool(SPECIALIST_NAME),
        *documentation_tools,
    ]


def build_sweep_tools(
    *, project_root: Path, documentation_tools: Sequence[BaseTool] = ()
) -> list[BaseTool]:
    """The same checks, over a list, with no `ask_user`: nobody is watching.

    A variant's omitted fields keep VITESS's default sample, so a sweep over
    one value -- the sample's size, say -- needs only that value.
    """
    return [
        build_variants_tool(
            module=MODULE,
            model=SampleElasticIsotrParameters,
            project_root=project_root,
            output_filename_fields=PLAIN_FILENAME_FIELDS,
            defaults=SHIPPED_DEFAULT,
        ),
        *documentation_tools,
    ]
