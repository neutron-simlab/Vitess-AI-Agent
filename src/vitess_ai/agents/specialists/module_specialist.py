"""What the five VITESS module specialists have in common.

Each of the five is an explicit builder in its own package, listing its own
module, its own parameter model and its own `AGENT.md`. What they share is
assembly, and it is shared rather than copied because the first-generation
agent copied it: five `*_params_to_cli` functions that had already drifted, and
five prompts that repeated the same paragraph with one word changed. Sharing
the assembly is the opposite of a registry -- nothing here discovers anything,
and adding a sixth module still means writing a package and adding one line to
`compile_module_specialists`.

This file is the assembly. The pieces it assembles sit beside it:
`module_tools.py` holds the tools the model calls, and `module_middleware.py`
holds the hooks that run around the model's turns.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from juena_core.agents.specialist_runtime import (
    UNATTENDED_NOTICE,
    build_specialist_backend,
    build_specialist_middleware,
    load_markdown,
)
from juena_core.llms_providers import build_chat_model
from juena_core.schema.agents import SpecialistReport
from juena_core.schema.llm_models import BlabladorModelName, Provider
from juena_core.server.agent.runtime_model_middleware import RuntimeModelContext
from vitess_ai.agents.delegation import ModuleCompiledSubAgent
from vitess_ai.agents.specialists.module_middleware import (
    GuidedAskUserMiddleware,
    ModuleReportMiddleware,
)
from vitess_ai.retrieval.prompts import MODULE_RAG_CONTEXT_NOTE
from vitess_ai.state import VitessBridgeState

__all__ = [
    "SPECIALIST_PROVIDER",
    "SPECIALIST_MODEL",
    "SWEEP_NOTICE",
    "FILESYSTEM_TOOLS",
    "FILESYSTEM_TOOL_DESCRIPTIONS",
    "build_module_prompt",
    "build_module_specialist",
]

#: Pinned independently of the UI selection. The model benchmark exercises
#: this role directly; Qwen3.8-Flash-Next is the selected production primary.
SPECIALIST_PROVIDER = Provider.BLABLADOR.value
SPECIALIST_MODEL = BlabladorModelName.QWEN38_FLASH_NEXT.value

#: No filesystem at all. A module specialist's whole job is a conversation and
#: one validation call, and `FilesystemMiddleware` otherwise binds eight tools
#: -- `ls`, `read_file`, `write_file`, `edit_file`, `delete`, `glob`, `grep` and
#: **`execute`** -- which is context spent on tools it will never use and, on a
#: weaker model, an invitation to use them.
#:
#: The allowlist was `("read_file",)` for one checkpoint, on the theory that a
#: later module could read a finding an earlier one recorded. It could not. A
#: `/findings/` file only exists because some specialist called `write_file`,
#: none of these five has it, and without `ls` or `glob` there is no way to
#: discover a path to read either. **These specialists hand off through
#: `module_results`, a typed state channel, not through files** -- so the tool
#: was dead, and the prompt paragraph describing it was teaching the model about
#: something that does not happen. `read_file` is mandatory in any allowlist the
#: middleware accepts, so `None` -- mount the middleware not at all -- is the
#: only way to bind none of them.
FILESYSTEM_TOOLS = None

FILESYSTEM_TOOL_DESCRIPTIONS: dict[str, str] = {}


def build_module_specialist(
    *,
    module: str,
    name: str,
    description: str,
    prompt_package: str,
    model: type[BaseModel],
    tools: list[BaseTool],
    documentation_tools: Sequence[BaseTool] = (),
    summarizer_model: Any,
    fallback_models: list[Any],
    unattended: bool = False,
) -> ModuleCompiledSubAgent:
    """Compile one module specialist from the pieces its own package chose.

    `tools` comes from that package's ``tools.py``, which is where the decision
    of what this module needs belongs -- read-in has staged files to look at,
    monitor2D has none. This function only assembles.

    The returned dictionary carries a ``module`` key beyond the three
    `SubAgentMiddleware` reads. `with_module_delegation_boundary` takes it off
    again; it is what tells the boundary whose configuration this specialist is
    allowed to hand back.
    """

    middleware = build_specialist_middleware(
        backend=build_specialist_backend(),
        summarizer_model=summarizer_model,
        fallback_models=fallback_models,
        filesystem_tool_descriptions=FILESYSTEM_TOOL_DESCRIPTIONS,
        specialist_name=name,
        filesystem_tools=FILESYSTEM_TOOLS,
        unattended=unattended,
    )
    if not unattended:
        middleware.append(GuidedAskUserMiddleware(module=module))
    middleware.append(
        ModuleReportMiddleware(module=module, model=model, unattended=unattended)
    )

    runnable = create_agent(
        model=build_chat_model(
            provider=SPECIALIST_PROVIDER, model=SPECIALIST_MODEL, temperature=0.0
        ),
        tools=tools,
        system_prompt=build_module_prompt(
            prompt_package,
            model,
            documentation_tools=documentation_tools,
            unattended=unattended,
        ),
        middleware=middleware,
        response_format=ToolStrategy(SpecialistReport),
        context_schema=RuntimeModelContext,
        state_schema=VitessBridgeState,
        name=f"vitess_{module}_{'sweep' if unattended else 'specialist'}",
    )
    return {
        "name": name,
        "description": description,
        "runnable": runnable,
        "module": module,
    }


SWEEP_NOTICE = """
This run is part of a **parameter sweep**, not a guided conversation. Everything above
about *what the values mean* -- the ranges, the units, the file rules, the physics, the
defaults -- applies unchanged. What changes is how you are asked and how you answer.

**There is no user to ask.** You have no `ask_user` tool, and nobody is watching this
run. Every instruction above that says "ask the user", "offer the choice" or "wait for
the user to provide" becomes, here: **use the schema default**, unless the objective
you were given says otherwise. If the objective does not mention a parameter, it keeps
its default. Do not stop to ask; there is nothing to stop for.

**You own parameter interpretation.** The objective gives you intent --
"vary FactInt with values [0.1, 0.5, 1, 2]", "the guide's eGuideShapeY should be
linear" -- and it is your job to turn that into valid override objects. Include only
values the objective explicitly requests or the workflow requires (such as the staged
READIN path). Omit every other field so Pydantic supplies its schema default. Do not
copy, restate, or improve omitted defaults. If the objective is genuinely ambiguous,
choose the reading the schema supports, say which reading you chose in your report,
and record it under `limitations`.

**You validate a list, not one object.** Your validation tool is
`validate_{module}_variants` and it takes `parameter_sets` -- every configuration this
module should sweep over.

- If the objective names values to vary, produce **one override object per value**.
  Include the varied value and any explicit fixed customization; let omitted fields
  retain their schema defaults.
- If this specialist was invoked for exact defaults, send exactly `[{{}}]`. Never expand
  the defaults into a model-authored object.

**Either every set is valid or none are recorded.** A partly validated list would run
the sets that happened to pass while the objective asked for more, and the missing runs
would be invisible in the results. So if one set fails, fix it and call the tool again
with the whole list. Do not drop the failing set and continue.

**Your report is the deliverable.** Say how many configurations you recorded and what
varies between them. Put anything you could not settle in `limitations` -- an honest gap
there is worth far more than a guess, because the orchestrator can act on a gap and
cannot act on a guess.
"""


def build_module_prompt(
    prompt_package: str,
    model: type[BaseModel],
    *,
    documentation_tools: Sequence[BaseTool] = (),
    unattended: bool = False,
) -> str:
    """The authored prompt, followed by the module's own parameter schema.

    The first-generation prompts interpolated `model_json_schema()` into a
    Python f-string, which is why they could not be read as prose and why the
    schema and the instructions drifted apart. The prose is `AGENT.md` now and
    the schema is appended at build time, so the schema is by construction the
    one the validation tool will enforce.
    """
    authored = load_markdown(prompt_package, "AGENT.md")
    # One argument governs both the bound tools and the matching policy. A
    # direct builder call with no documentation tools therefore cannot produce
    # a prompt that tells the model to call something absent.
    if documentation_tools:
        authored = f"{authored}\n{MODULE_RAG_CONTEXT_NOTE}"
    if unattended:
        module = prompt_package.rsplit(".", 1)[-1]
        authored = (
            f"{authored}\n## Running unattended\n\n{UNATTENDED_NOTICE}\n"
            f"\n## This run is a sweep\n{SWEEP_NOTICE.format(module=module)}"
        )
    schema = json.dumps(model.model_json_schema(), indent=2)
    return (
        f"{authored}\n## The parameter schema you must satisfy\n\n"
        f"This is `{model.__name__}`, and it is what your validation tool "
        "checks against. Field descriptions begin with the VITESS command-line "
        "flag the value becomes.\n\n"
        f"```json\n{schema}\n```\n"
    )
