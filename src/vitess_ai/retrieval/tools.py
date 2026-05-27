"""LangChain tool adapters for VITESS documentation RAG."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from langchain.tools import tool

from vitess_ai.core.log import get_logger
from vitess_ai.retrieval.runtime import RagUnavailableError, get_rag_collection, is_rag_enabled

logger = get_logger(__name__)


def _unavailable_message(reason: str) -> str:
    return f"RAG_UNAVAILABLE: VITESS documentation retrieval is unavailable. {reason}"


def _build_unavailable_tools(reason: str) -> list[Any]:
    @tool
    def vitess_search(query: str) -> str:
        """General search over VITESS documentation."""
        _ = query
        return _unavailable_message(reason)

    @tool
    def vitess_option_lookup(query: str) -> str:
        """Specialized lookup for VITESS command-line options like -z or -A."""
        _ = query
        return _unavailable_message(reason)

    @tool
    def vitess_module_lookup(query: str) -> str:
        """Focused lookup for VITESS modules, sections, and parameters."""
        _ = query
        return _unavailable_message(reason)

    @tool
    def vitess_debug_retrieval(query: str) -> str:
        """Debug retrieval over VITESS documentation."""
        _ = query
        return _unavailable_message(reason)

    return [
        vitess_search,
        vitess_option_lookup,
        vitess_module_lookup,
        vitess_debug_retrieval,
    ]


@lru_cache(maxsize=1)
def get_rag_tools() -> list[Any]:
    """Return VITESS documentation RAG tools, or stubs if RAG is unavailable."""
    if not is_rag_enabled():
        return []

    try:
        from vitess_rag.tools import create_vitess_tools

        collection = get_rag_collection(recreate=False)
        if collection.count() == 0:
            return _build_unavailable_tools("The configured Chroma collection is empty.")
        return list(create_vitess_tools(collection))
    except RagUnavailableError as exc:
        logger.warning("VITESS RAG is unavailable: %s", exc)
        return _build_unavailable_tools(str(exc))
    except Exception as exc:
        logger.warning("Failed to initialize VITESS RAG tools: %s", exc, exc_info=True)
        return _build_unavailable_tools(str(exc))
