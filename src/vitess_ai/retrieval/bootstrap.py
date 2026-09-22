"""Build the VITESS documentation index. Run once, or after the docs change.

    uv run python -m vitess_ai.retrieval.bootstrap

Separate from serving on purpose. Indexing sends every documentation chunk to
the embedding endpoint, which costs time and quota, and a server that did it at
startup would do it on every restart. The serving process degrades gracefully
without an index; this explicit indexing command still exits non-zero when the
requested work fails so automation cannot record a failed build as successful.
"""

from __future__ import annotations

from typing import Any

from juena_core.log import get_logger
from vitess_ai.config import Config
from vitess_ai.retrieval.runtime import (
    build_embedding_function,
    get_rag_collection,
    rag_enabled,
)

logger = get_logger(__name__)

__all__ = ["bootstrap_rag_index", "main"]


def bootstrap_rag_index() -> dict[str, Any]:
    """Create or reuse the Chroma collection over `rag/vitess-rag/data`."""

    if not rag_enabled():
        return {"indexed": False, "message": "VITESS retrieval is switched off."}

    if not Config.RAG_DATA_DIR.exists():
        raise FileNotFoundError(
            f"No VITESS documentation at {Config.RAG_DATA_DIR.resolve()}. "
            "The `rag/vitess-rag` submodule is probably not checked out."
        )
    Config.RAG_PERSIST_PATH.mkdir(parents=True, exist_ok=True)

    if not Config.RAG_REINDEX:
        existing = get_rag_collection(recreate=False)
        count = existing.count()
        if count:
            return {
                "indexed": False,
                "count": count,
                "message": f"Reusing the existing index of {count} chunks.",
            }

    from vitess_rag.chroma import index_markdown_directory

    collection, chunks = index_markdown_directory(
        input_dir=Config.RAG_DATA_DIR,
        persist_path=Config.RAG_PERSIST_PATH,
        collection_name=Config.RAG_COLLECTION,
        embedding_function=build_embedding_function(),
        output_jsonl=None,
        recreate=True,
    )
    return {
        "indexed": True,
        "count": collection.count(),
        "message": f"Indexed {len(chunks)} chunks of VITESS documentation.",
    }


def main() -> int:
    try:
        print(bootstrap_rag_index()["message"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("VITESS documentation indexing failed: %s", exc, exc_info=True)
        print(f"Could not index the VITESS documentation: {exc}")
        print("The application still runs; its documentation tools will say so.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
