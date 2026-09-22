"""Fixtures every v2 test module may use.

Core reads nothing on import -- `juena_core.config.settings()` raises until an
application calls `configure()`, which is 01/CP1's whole point -- so anything
that builds a chat model or a middleware stack needs settings installed first.
This installs a set that reaches no network and touches no database.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from juena_core import config as config_module
from juena_core.config import CoreSettings
from juena_core.schema.llm_models import BlabladorModelName


def make_settings(**overrides: object) -> CoreSettings:
    values: dict[str, object] = {
        "OPENAI_API_KEY": None,
        "BLABLADOR_API_KEY": "test-key-not-used",
        "BLABLADOR_BASE_URL": "https://blablador.invalid/v1",
        "MAX_TOKENS": 10_000,
        "TIMEOUT_SECONDS": 60,
        "MAX_RETRIES": 3,
        "DEFAULT_PROVIDER": "blablador",
        "DEFAULT_MODEL": BlabladorModelName.GPT_OSS.value,
        "OPENAI_AVAILABLE_MODELS": None,
        "BLABLADOR_AVAILABLE_MODELS": None,
        "OPENAI_DEFAULT_MODEL": "gpt-4o-mini",
        "BLABLADOR_DEFAULT_MODEL": BlabladorModelName.GPT_OSS.value,
        "STREAM_TOOL_PAYLOADS": False,
        "DATABASE_URL": None,
        "DATABASE_POOL_MAX_SIZE": 5,
        "SESSION_TTL_HOURS": 8,
        "SESSION_COOKIE_SECURE": False,
        "FALLBACK_PROVIDER": None,
        "EXECUTE_TIMEOUT_SECONDS": 600,
        "ARTIFACT_ROOT": Path("/tmp/vitess-ai-test-artifacts"),
        "AUDIT_FILE": Path("/tmp/vitess-ai-test-artifacts/audit.jsonl"),
        "LOG_LEVEL": "INFO",
        "LOG_DIR": Path("/tmp/vitess-ai-test-logs"),
        "BIND_HOST": "127.0.0.1",
        "API_PUBLISHED": False,
    }
    values.update(overrides)
    return CoreSettings(**values)  # type: ignore[arg-type]


@pytest.fixture
def configured(monkeypatch):
    """Install core settings process-wide for one test."""

    config = make_settings()
    monkeypatch.setattr(config_module, "_settings", config)
    return config


@pytest.fixture
def offline_model(configured):
    """A real `BaseChatModel` that is never called.

    `create_summarization_middleware` type-checks its model, so `None` will not
    do. This one points at an unreachable base URL: if a test ever does reach
    the network, it fails rather than quietly costing money.
    """
    from juena_core.llms_providers import build_chat_model

    return build_chat_model(
        provider="blablador", model=configured.DEFAULT_MODEL, temperature=0.0
    )


@pytest.fixture(autouse=True, scope="session")
def _documentation_retrieval_is_off_in_tests():
    """No test opens Chroma, and none depends on a developer's API key.

    The degradation path is still the real one: `get_rag_tools` returns its four
    `RAG_UNAVAILABLE` tools, with the names the prompts name. What is switched
    off is the branch that would build an embedding function and create a Chroma
    directory inside the checkout -- which is what happens on a machine that has
    `BLABLADOR_API_KEY` exported, and not on one that does not. A suite whose
    tool surface depends on the developer's environment is not a suite.
    """
    from vitess_ai.config import Config
    from vitess_ai.retrieval import tools as retrieval_tools

    previous = Config.RAG_ENABLED
    Config.RAG_ENABLED = False
    retrieval_tools.get_rag_tools.cache_clear()
    yield
    Config.RAG_ENABLED = previous
    retrieval_tools.get_rag_tools.cache_clear()
