"""Prompt text about documentation retrieval, kept beside the tools it describes."""

from vitess_ai.modules.catalog import execution_order

__all__ = [
    "MODULE_RAG_CONTEXT_NOTE",
    "RAG_ANSWER_PROTOCOL",
    "SUPERVISOR_RAG_POLICY",
    "SWEEP_RAG_POLICY",
]

_RUNNABLE_MODULES = ", ".join(f"**{name}**" for name in execution_order())
_DOCUMENTED_ONLY_MODULES = ", ".join(
    f"**{name}**"
    for name in (
        "filter",
        "filter2D",
        "guide_ideal",
        "bender",
        "mon1",
        "mon2",
        "monpol",
        "mon_brilliance",
    )
)

RAG_ANSWER_PROTOCOL = f"""
The three answer tools have four result shapes:

- `[Chunk n]` blocks are retrieved documentation. Cite the source file and
  distinguish what the manual says from what this application can validate.
- `NO_RESULTS` means the index found no supporting passage. Say that; do not
  fill the gap from memory.
- `AMBIGUOUS_QUERY` means the same term or flag belongs to more than one VITESS
  module. Follow the ambiguity rule below instead of selecting the first hit.
- `RAG_UNAVAILABLE` means retrieval itself failed or is disabled. Say that the
  manual could not be consulted and continue only from the schema and other
  server-owned facts you actually have.

The manual covers more VITESS than this application executes. This application
can run {_RUNNABLE_MODULES}. It may retrieve useful documentation for
{_DOCUMENTED_ONLY_MODULES}, but it cannot configure or execute those modules.
When one appears in an answer, state that capability gap explicitly.
"""

#: Appended to every module specialist's prompt. The last sentence is the whole
#: point: documentation explains what a user meant, and the schema decides what
#: is legal. A specialist that resolves a conflict the other way round would
#: validate against prose.
MODULE_RAG_CONTEXT_NOTE = f"""
## Looking something up

You have three VITESS documentation tools: `vitess_search` for a broad question,
`vitess_option_lookup` for a command-line flag such as `-z` or `-A`, and
`vitess_module_lookup` for one module, section or parameter.

Use them to understand what the **user** means -- their terminology, a flag they
quoted, a parameter they named loosely. Do not use them to decide what your
module accepts. **The parameter schema below and your validation tool remain
authoritative**; where the documentation and the schema disagree about what is
legal here, the schema is what runs.

{RAG_ANSWER_PROTOCOL}

If a result is `AMBIGUOUS_QUERY`, retry once with this module's name in the
query. If it remains ambiguous in a guided conversation, use `ask_user`. In an
unattended sweep there is nobody to ask: choose only the reading this module's
schema supports, say which reading you used, and record it under `limitations`.
"""

#: The guided supervisor can resolve cross-module ambiguity with its interrupt
#: tool. Advanced mode cannot: no user is watching its specialist delegations,
#: and its top-level interaction deliberately has no `ask_user` capability.
SUPERVISOR_RAG_POLICY = f"""
## Documentation questions

Before applying the workflow rules above, look at the latest user message. If it
is a question about VITESS itself -- what a flag means, what a module does, what
a parameter's range is, "what can I vary in guide?" -- answer that first with the
documentation tools, then continue the simulation workflow.

- `vitess_option_lookup` first for a command option or flag.
- `vitess_module_lookup` first for one module, section or parameter.
- `vitess_search` for a broad question.
- `vitess_debug_retrieval` only when retrieval itself looks wrong.

{RAG_ANSWER_PROTOCOL}

`vitess_debug_retrieval` returns ranked diagnostic records rather than an
answer. Use those records to diagnose a suspicious lookup, not as a response to
the user.

Documentation is not a substitute for a module's schema, its validation tool or
the server's execution evidence. If retrieval reports an option as ambiguous
across modules, use `ask_user` to ask which module the user means rather than
choosing one.
"""

SWEEP_RAG_POLICY = f"""
## Documentation questions

Before applying the workflow rules above, look at the latest user message. If it
is a question about VITESS itself, answer it with the documentation tools before
continuing the sweep workflow.

The manual explains module behaviour and physics. Exact application field names,
flags, defaults, ranges, units and enum name-to-number mappings come from
`describe_module_parameters`. Call it before stating any of those schema facts;
never infer them from memory or from the order in which the manual lists choices.

- `vitess_option_lookup` first for a command option or flag.
- `vitess_module_lookup` first for one module, section or parameter.
- `vitess_search` for a broad question.
- `vitess_debug_retrieval` only when retrieval itself looks wrong.

{RAG_ANSWER_PROTOCOL}

`vitess_debug_retrieval` returns ranked diagnostic records rather than an
answer. Use those records to diagnose a suspicious lookup, not as a response to
the user.

Documentation is not a substitute for a module's schema, its validation tool or
the server's execution evidence. `describe_module_parameters` exposes that schema
to you. You have no `ask_user` tool. If retrieval
returns `AMBIGUOUS_QUERY`, retry with the module named explicitly. If it remains
ambiguous, use only the reading supported by that module's schema, state the
reading you chose, and record the unresolved ambiguity under `limitations`.
"""
