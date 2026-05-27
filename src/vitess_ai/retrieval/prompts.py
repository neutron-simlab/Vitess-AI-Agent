"""Prompt snippets for VITESS documentation RAG usage."""

ADVANCED_RAG_DOCUMENTATION_POLICY = """
================================================================================
DOCUMENTATION INTENT GATE AND EVIDENCE POLICY
================================================================================
Before applying workflow phase rules, inspect the latest user message.

If it is a VITESS documentation/help question, answer that first using the
documentation retrieval tools, then return to the active workflow phase.

Documentation/help questions include:
- command option or flag meanings, e.g. `-z`, `-A`, `-H`, `-V`
- module explanations and section descriptions
- parameter descriptions, ranges, defaults, and ambiguity across modules
- questions like "what parameters can I vary in guide?"
- user requests that explicitly ask for VITESS docs or documentation context

Tool selection:
- Use `vitess_option_lookup` first for command options or flags.
- Use `vitess_module_lookup` first for one module, section, or parameter explanation.
- Use `vitess_search` for broad documentation questions.
- Use `vitess_debug_retrieval` only when retrieval appears wrong.

Do not use documentation retrieval as a replacement for schema validation,
module validation tools, uploaded-file checks, or simulation execution tools.
If retrieval reports an ambiguous option or parameter, ask which module the user means.
After answering a documentation question, return to the active simulation workflow.
Advanced-mode source verification:
- Query Chroma retrieval first.
- Use native DeepAgents file tools (`ls`, `read_file`, `grep`, `glob`) only under
  `/docs/` after Chroma retrieval, when a retrieved source_file/path needs
  verification, disambiguation, or missing context recovery.
- Do not use native file tools for VITESS docs outside `/docs/`.
"""


MODULE_RAG_CONTEXT_NOTE = (
    "If the orchestrator provides documentation evidence from VITESS RAG, use it "
    "only to interpret user terminology. The module schema and validation tool "
    "remain authoritative for accepted parameters."
)
