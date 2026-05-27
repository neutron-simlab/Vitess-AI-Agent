"""Bootstrap the persistent VITESS documentation RAG index."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vitess_ai.core.config import global_config
from vitess_ai.core.log import get_logger
from vitess_ai.retrieval.runtime import build_embedding_function, get_rag_collection, is_rag_enabled

logger = get_logger(__name__)


def bootstrap_rag_index() -> dict[str, Any]:
    """Create or reuse the configured VITESS documentation Chroma index."""
    if not is_rag_enabled():
        return {"success": True, "skipped": True, "message": "VITESS RAG is disabled."}

    input_dir = Path(global_config.VITESS_RAG_DATA_DIR)
    persist_path = Path(global_config.VITESS_RAG_PERSIST_PATH)
    persist_path.mkdir(parents=True, exist_ok=True)

    if not input_dir.exists():
        raise FileNotFoundError(f"VITESS RAG data directory not found: {input_dir.resolve()}")

    if not global_config.VITESS_RAG_REINDEX:
        collection = get_rag_collection(recreate=False)
        count = collection.count()
        if count > 0:
            return {
                "success": True,
                "skipped": True,
                "count": count,
                "message": f"Reusing existing VITESS RAG collection with {count} documents.",
            }

    from vitess_rag.chroma import index_markdown_directory

    collection, chunks = index_markdown_directory(
        input_dir=input_dir,
        persist_path=persist_path,
        collection_name=global_config.VITESS_RAG_COLLECTION,
        embedding_function=build_embedding_function(),
        output_jsonl=None,
        recreate=True,
    )

    return {
        "success": True,
        "skipped": False,
        "chunks": len(chunks),
        "count": collection.count(),
        "message": f"Indexed {len(chunks)} VITESS RAG chunks.",
    }


def main() -> None:
    try:
        result = bootstrap_rag_index()
        print(f"[OK] {result['message']}")
    except Exception as exc:
        logger.warning("VITESS RAG bootstrap failed: %s", exc, exc_info=True)
        print(f"[WARN] VITESS RAG bootstrap failed: {exc}")
        print("   Continuing startup without a ready RAG index.")


if __name__ == "__main__":
    main()
