"""VITESS documentation retrieval: an embedded Chroma index over the manual."""

from vitess_ai.retrieval.bootstrap import bootstrap_rag_index
from vitess_ai.retrieval.prompts import (
    MODULE_RAG_CONTEXT_NOTE,
    ORCHESTRATOR_RAG_POLICY,
)
from vitess_ai.retrieval.runtime import RagUnavailable, get_rag_collection, rag_enabled
from vitess_ai.retrieval.tools import (
    SPECIALIST_RAG_TOOLS,
    get_rag_tools,
    specialist_rag_tools,
)

__all__ = [
    "MODULE_RAG_CONTEXT_NOTE",
    "bootstrap_rag_index",
    "ORCHESTRATOR_RAG_POLICY",
    "RagUnavailable",
    "SPECIALIST_RAG_TOOLS",
    "get_rag_collection",
    "get_rag_tools",
    "rag_enabled",
    "specialist_rag_tools",
]
