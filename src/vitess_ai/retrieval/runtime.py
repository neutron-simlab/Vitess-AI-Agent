"""Connecting vitess-ai to the embedded `vitess_rag` index.

Chroma stays, `vitess-rag` stays a submodule, and **core does not learn about
either** -- the same rule that keeps core away from juena-rag. juena-chatbot
searches its index over HTTP; this one is a directory on disk. Neither belongs
in a library that knows what a specialist report is.

Every import of `vitess_rag` is inside a function. Chroma pulls in ONNX and a
tokenizer, and a deployment that has turned retrieval off should not pay for
them at import.
"""

from __future__ import annotations

from typing import Any

from vitess_ai.config import Config

__all__ = ["RagUnavailable", "build_embedding_function", "get_rag_collection", "rag_enabled"]


class RagUnavailable(RuntimeError):
    """Retrieval cannot answer, and this says why in one sentence."""


def rag_enabled() -> bool:
    return bool(Config.RAG_ENABLED)


def build_embedding_function() -> Any:
    from vitess_rag.embeddings import BlabladorEmbeddingFunction

    return BlabladorEmbeddingFunction(
        model_name=Config.RAG_EMBEDDING_MODEL,
        api_key=Config.BLABLADOR_API_KEY,
        base_url=Config.BLABLADOR_BASE_URL,
    )


def get_rag_collection(recreate: bool = False) -> Any:
    if not rag_enabled():
        raise RagUnavailable("VITESS documentation retrieval is switched off.")

    from vitess_rag.chroma import get_or_create_collection

    Config.RAG_PERSIST_PATH.mkdir(parents=True, exist_ok=True)
    return get_or_create_collection(
        persist_path=Config.RAG_PERSIST_PATH,
        collection_name=Config.RAG_COLLECTION,
        embedding_function=build_embedding_function(),
        recreate=recreate,
    )
