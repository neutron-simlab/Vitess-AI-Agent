"""VITESS documentation retrieval: an embedded Chroma index over the manual."""

from vitess_ai.retrieval.bootstrap import bootstrap_rag_index
from vitess_ai.retrieval.prompts import (
    MODULE_RAG_CONTEXT_NOTE,
    RAG_ANSWER_PROTOCOL,
    SUPERVISOR_RAG_POLICY,
    SWEEP_RAG_POLICY,
)
from vitess_ai.retrieval.runtime import RagUnavailable, get_rag_collection, rag_enabled
from vitess_ai.retrieval.tools import (
    RAG_TOOL_NAMES,
    SPECIALIST_RAG_TOOLS,
    get_rag_tools,
    orchestrator_documentation,
    specialist_rag_tools,
)

__all__ = [
    "MODULE_RAG_CONTEXT_NOTE",
    "bootstrap_rag_index",
    "RAG_ANSWER_PROTOCOL",
    "RagUnavailable",
    "RAG_TOOL_NAMES",
    "SPECIALIST_RAG_TOOLS",
    "SUPERVISOR_RAG_POLICY",
    "SWEEP_RAG_POLICY",
    "get_rag_collection",
    "get_rag_tools",
    "orchestrator_documentation",
    "rag_enabled",
    "specialist_rag_tools",
]
