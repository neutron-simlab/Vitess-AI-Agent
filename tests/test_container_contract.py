"""Static guards for the parts of the image contract unit tests can prove."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_every_architecture_builds_the_same_pinned_vitess_revision() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    revision = re.search(r"^ARG VITESS_COMMIT=([0-9a-f]{40})$", dockerfile, re.MULTILINE)

    assert revision is not None
    assert "VITESS_TARBALL_URL" not in dockerfile
    assert "TARGETARCH" not in dockerfile
    assert 'git -C /vitess-src fetch --depth 1 origin "${VITESS_COMMIT}"' in dockerfile


def test_the_build_tool_is_versioned_instead_of_floating_on_latest() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert re.search(r"^ARG UV_VERSION=\d+\.\d+\.\d+$", dockerfile, re.MULTILINE)
    assert "ghcr.io/astral-sh/uv:latest" not in dockerfile


def test_starlette_is_direct_because_the_server_imports_its_response_types() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependency_names = {
        re.split(r"[<>=!~;\s\[]", requirement, maxsplit=1)[0].lower()
        for requirement in project["project"]["dependencies"]
    }

    assert "starlette" in dependency_names


def test_mcp_startup_does_not_depend_on_an_external_update_check() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "FASTMCP_CHECK_FOR_UPDATES=off" in compose


def test_rag_query_limits_from_dotenv_reach_the_application_container() -> None:
    """A documented Compose setting that is not forwarded is a false control."""
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert (
        "VITESS_RAG_QUERY_TIMEOUT_SECONDS=${VITESS_RAG_QUERY_TIMEOUT_SECONDS:-20}"
        in compose
    )
    assert "VITESS_RAG_MAX_RETRIES=${VITESS_RAG_MAX_RETRIES:-1}" in compose


def test_langsmith_settings_from_dotenv_reach_the_application_container() -> None:
    """Tracing configured in `.env` must cross the Compose boundary."""

    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "LANGSMITH_TRACING=${LANGSMITH_TRACING:-false}" in compose
    assert "LANGSMITH_API_KEY=${LANGSMITH_API_KEY:-}" in compose
    assert "LANGSMITH_PROJECT=${LANGSMITH_PROJECT:-vitess-ai}" in compose
    assert (
        "LANGSMITH_ENDPOINT=${LANGSMITH_ENDPOINT:-https://api.smith.langchain.com}"
        in compose
    )
