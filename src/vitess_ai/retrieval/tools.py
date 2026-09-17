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
from langchain_core.tools import BaseTool

from juena_core.log import get_logger
from vitess_ai.retrieval.prompts import SUPERVISOR_RAG_POLICY, SWEEP_RAG_POLICY
from vitess_ai.retrieval.runtime import RagUnavailable, get_rag_collection, rag_enabled

logger = get_logger(__name__)

__all__ = [
    "RAG_TOOL_NAMES",
    "SPECIALIST_RAG_TOOLS",
    "get_rag_tools",
    "orchestrator_documentation",
    "specialist_rag_tools",
]

RAG_TOOL_NAMES = (
    "vitess_search",
    "vitess_option_lookup",
    "vitess_module_lookup",
    "vitess_debug_retrieval",
)

#: What a module specialist gets. `vitess_debug_retrieval` is deliberately not
#: here: it exists to inspect retrieval when retrieval looks wrong, which is the
#: orchestrator's problem and not a thing to hand a specialist whose job is one
#: validation call. 03/CP4 narrowed these specialists from eleven tools to four
#: for that reason, and three documentation tools is already the most that can
#: be justified.
SPECIALIST_RAG_TOOLS = ("vitess_search", "vitess_option_lookup", "vitess_module_lookup")


def _unavailable_message(reason: str) -> str:
    compact_reason = " ".join(reason.split())
    if len(compact_reason) > 500:
        compact_reason = compact_reason[:497] + "..."
    return (
        "RAG_UNAVAILABLE: VITESS documentation retrieval is unavailable. "
        f"{compact_reason} Do not invent what the manual says. Use only any "
        "parameter schema already in your prompt and other server-owned facts, "
        "and say that the documentation could not be consulted."
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


def _guard_query_tool(source: BaseTool) -> BaseTool:
    """Keep one provider failure inside the documentation tool boundary.

    Construction-time degradation is not enough: Chroma embeds every query,
    so an expired key or unavailable endpoint first appears when the model
    invokes an already-bound tool. The wrapper is per call -- one 429 must not
    replace the process-cached real tools with stubs for every later request.
    """

    @tool(source.name, description=source.description)
    def guarded(query: str) -> str:
        try:
            return str(source.invoke({"query": query}))
        except Exception as exc:  # noqa: BLE001 -- provider/Chroma types vary
            logger.warning(
                "VITESS documentation query via %s failed: %s",
                source.name,
                exc,
                exc_info=True,
            )
            # Keep provider internals in the server log above. A bad key can
            # surface from the OpenAI SDK as an unrelated AttributeError, which
            # sends the user toward application code rather than the setting
            # they can fix. The model-facing result names the safe checks that
            # cover both a failed query embedding and a local Chroma failure.
            return _unavailable_message(
                "The query could not be embedded or read from the local index. "
                "Verify BLABLADOR_API_KEY, BLABLADOR_BASE_URL, and that the "
                "VITESS documentation index is readable, then retry. The server "
                "log contains the underlying provider or index error."
            )

    return guarded


def _validated_rag_tools(tools: list[BaseTool]) -> list[BaseTool]:
    """Require the embedded package to provide the surface every prompt names."""
    names = tuple(item.name for item in tools)
    if names != RAG_TOOL_NAMES:
        raise RagUnavailable(
            "The documentation package exposed an unexpected tool set: "
            + ", ".join(names or ("none",))
        )
    return tools


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
        real_tools = _validated_rag_tools(list(create_vitess_tools(collection)))
        return [_guard_query_tool(item) for item in real_tools]
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


def orchestrator_documentation(*, unattended: bool) -> tuple[list[BaseTool], str]:
    """Return an inseparable documentation tool surface and its policy.

    Both graph builders call this themselves. A caller can still build a graph
    while retrieval is unavailable -- it gets the four explanatory stubs --
    but cannot accidentally bind the tools without their return protocol or
    append a prompt that names tools the graph does not have.
    """

    policy = SWEEP_RAG_POLICY if unattended else SUPERVISOR_RAG_POLICY
    return list(get_rag_tools()), policy
