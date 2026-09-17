"""Prompt text about documentation retrieval, kept beside the tools it describes."""

__all__ = ["MODULE_RAG_CONTEXT_NOTE", "ORCHESTRATOR_RAG_POLICY"]

#: Appended to every module specialist's prompt. The last sentence is the whole
#: point: documentation explains what a user meant, and the schema decides what
#: is legal. A specialist that resolves a conflict the other way round would
#: validate against prose.
MODULE_RAG_CONTEXT_NOTE = """
## Looking something up

You have three VITESS documentation tools: `vitess_search` for a broad question,
`vitess_option_lookup` for a command-line flag such as `-z` or `-A`, and
`vitess_module_lookup` for one module, section or parameter.

Use them to understand what the **user** means -- their terminology, a flag they
quoted, a parameter they named loosely. Do not use them to decide what your
module accepts. **The parameter schema below and your validation tool remain
authoritative**; where the documentation and the schema disagree about what is
legal here, the schema is what runs.

If a tool answers `RAG_UNAVAILABLE`, the documentation could not be consulted.
Say so, and answer from the schema.
"""

#: The orchestrator's version, ported from the first-generation advanced-mode
#: prompt. It keeps the intent gate -- answer the documentation question first,
#: then return to the phase you were in -- because a sweep that stops to explain
#: a flag and never resumes is the failure this was written against.
ORCHESTRATOR_RAG_POLICY = """
## Documentation questions

Before applying the workflow rules below, look at the latest user message. If it
is a question about VITESS itself -- what a flag means, what a module does, what
a parameter's range is, "what can I vary in guide?" -- answer that first with the
documentation tools, then return to the phase you were in.

- `vitess_option_lookup` first for a command option or flag.
- `vitess_module_lookup` first for one module, section or parameter.
- `vitess_search` for a broad question.
- `vitess_debug_retrieval` only when retrieval itself looks wrong.

Documentation is not a substitute for a module's schema, its validation tool or
the server's execution evidence. If retrieval reports an option as ambiguous
across modules, ask which module the user means rather than choosing one.
"""
