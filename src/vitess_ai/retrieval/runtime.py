"""Runtime helpers for connecting Vitess AI to ``vitess_rag``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vitess_ai.core.config import global_config


class RagUnavailableError(RuntimeError):
    """Raised when documentation RAG cannot be initialized."""


def is_rag_enabled() -> bool:
    return bool(global_config.VITESS_RAG_ENABLED)


def build_embedding_function() -> Any:
    from vitess_rag.embeddings import BlabladorEmbeddingFunction

    return BlabladorEmbeddingFunction(
        model_name=global_config.VITESS_RAG_EMBEDDING_MODEL,
        api_key=global_config.BLABLADOR_API_KEY,
        base_url=global_config.BLABLADOR_BASE_URL,
    )


def get_rag_collection(recreate: bool = False) -> Any:
    if not is_rag_enabled():
        raise RagUnavailableError("VITESS RAG is disabled.")

    from vitess_rag.chroma import get_or_create_collection

    persist_path = Path(global_config.VITESS_RAG_PERSIST_PATH)
    persist_path.mkdir(parents=True, exist_ok=True)

    return get_or_create_collection(
        persist_path=persist_path,
        collection_name=global_config.VITESS_RAG_COLLECTION,
        embedding_function=build_embedding_function(),
        recreate=recreate,
    )
