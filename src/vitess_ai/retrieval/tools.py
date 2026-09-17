"""The documentation tools, and what happens when there is no documentation.

**Degrading is the design, not an accident.** When the collection is empty or
Chroma will not open, this returns tools that answer `RAG_UNAVAILABLE: ...`
rather than returning nothing. The difference matters at the far end: a model
whose tool list changed between one conversation and the next has no way to say
"I could not look that up" -- it simply stops mentioning the documentation, and
the user cannot tell an unanswerable question from an unasked one. It is the
same choice 03/CP3 made for the MCP gateway: keep the tool bound and report the
outage per request.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from langchain.tools import tool

from juena_core.log import get_logger
from vitess_ai.retrieval.runtime import RagUnavailable, get_rag_collection, rag_enabled

logger = get_logger(__name__)

__all__ = ["SPECIALIST_RAG_TOOLS", "get_rag_tools", "specialist_rag_tools"]

#: What a module specialist gets. `vitess_debug_retrieval` is deliberately not
#: here: it exists to inspect retrieval when retrieval looks wrong, which is the
#: orchestrator's problem and not a thing to hand a specialist whose job is one
#: validation call. 03/CP4 narrowed these specialists from eleven tools to four
#: for that reason, and three documentation tools is already the most that can
#: be justified.
SPECIALIST_RAG_TOOLS = ("vitess_search", "vitess_option_lookup", "vitess_module_lookup")


def _unavailable_message(reason: str) -> str:
    return (
        f"RAG_UNAVAILABLE: VITESS documentation retrieval is unavailable. {reason} "
        "Answer from the parameter schema you were given, and say that the "
        "documentation could not be consulted."
    )


def _unavailable_tools(reason: str) -> list[Any]:
    @tool
    def vitess_search(query: str) -> str:
        """General search over VITESS documentation."""
        _ = query
        return _unavailable_message(reason)

    @tool
    def vitess_option_lookup(query: str) -> str:
        """Look up a VITESS command-line option such as -z or -A."""
        _ = query
        return _unavailable_message(reason)

    @tool
    def vitess_module_lookup(query: str) -> str:
        """Look up a VITESS module, section or parameter."""
        _ = query
        return _unavailable_message(reason)

    @tool
    def vitess_debug_retrieval(query: str) -> str:
        """Inspect what retrieval returns, when retrieval looks wrong."""
        _ = query
        return _unavailable_message(reason)

    return [vitess_search, vitess_option_lookup, vitess_module_lookup, vitess_debug_retrieval]


@lru_cache(maxsize=1)
def get_rag_tools() -> list[Any]:
    """The four documentation tools, or four that explain why they cannot answer.

    Cached because opening Chroma costs seconds and the answer cannot change
    within a process: the index is read-only here, written by `bootstrap`.
    """
    if not rag_enabled():
        return _unavailable_tools("It is switched off in this deployment.")

    try:
        from vitess_rag.tools import create_vitess_tools

        collection = get_rag_collection(recreate=False)
        if collection.count() == 0:
            return _unavailable_tools("The documentation index is empty.")
        return list(create_vitess_tools(collection))
    except RagUnavailable as exc:
        logger.warning("VITESS documentation retrieval is unavailable: %s", exc)
        return _unavailable_tools(str(exc))
    except Exception as exc:  # noqa: BLE001 -- see the docstring above
        # Broad on purpose: Chroma, ONNX and the embedding endpoint each have
        # their own failure types, and every one of them means the same thing
        # to the model. The alternative is an import-time crash in a deployment
        # that would otherwise work without documentation.
        logger.warning("Could not build VITESS documentation tools: %s", exc, exc_info=True)
        return _unavailable_tools(str(exc))


def specialist_rag_tools() -> list[Any]:
    """The subset a module specialist is bound, in a fixed order."""

    available = {item.name: item for item in get_rag_tools()}
    return [available[name] for name in SPECIALIST_RAG_TOOLS if name in available]
