"""This deployment's settings, and the one call that hands core its own.

**An application extends core's configuration by not extending it.** Core defines
a frozen `CoreSettings` that reads nothing, and `configure()` installs it once at
startup. This module keeps its own `Config` — its `os.getenv` calls, its defaults
and its `validate_required()` — because what has to be validated here is not what
has to be validated in juena-chatbot's deployment: there is no SAML, no Podman,
and there is a VITESS project volume two containers have to agree about.

`validate_required()` is called by `service.py`, not at import. 01/CP1 exists
because the first-generation `juena` package ran `Config.initialize()` at module
scope, so importing *any* module loaded `.env` and could raise — and `get_logger`,
imported nearly everywhere, imported `Config`. Nothing here runs on import.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

import juena_core
from juena_core.schema.llm_models import BlabladorModelName

__all__ = ["Config", "configure_core"]


def _flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(
        part.strip().lower()
        for part in os.getenv(name, default).split(",")
        if part.strip()
    )


class Config:
    """Read once, at startup, by the process that is about to serve."""

    # -- models -------------------------------------------------------------
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or None
    BLABLADOR_API_KEY = os.getenv("BLABLADOR_API_KEY") or None
    BLABLADOR_BASE_URL = os.getenv(
        "BLABLADOR_BASE_URL", "https://api.helmholtz-blablador.fz-juelich.de/v1"
    )
    DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "blablador")
    DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", BlabladorModelName.GPT_OSS.value)
    OPENAI_DEFAULT_MODEL = os.getenv("OPENAI_DEFAULT_MODEL", "gpt-4o-mini")
    BLABLADOR_DEFAULT_MODEL = os.getenv(
        "BLABLADOR_DEFAULT_MODEL", BlabladorModelName.GPT_OSS.value
    )
    FALLBACK_PROVIDER = os.getenv("FALLBACK_PROVIDER") or None
    MAX_TOKENS = int(os.getenv("MAX_TOKENS", "20000"))
    TIMEOUT_SECONDS = int(os.getenv("TIMEOUT_SECONDS", "120"))
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))

    # -- persistence --------------------------------------------------------
    DATABASE_URL = os.getenv("DATABASE_URL") or None
    DATABASE_POOL_MAX_SIZE = int(os.getenv("DATABASE_POOL_MAX_SIZE", "10"))
    SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "8"))

    # -- this deployment ----------------------------------------------------
    #: The shared volume. Both containers mount it here, so a path written by
    #: one is meaningful to the other; the MCP server reads the same variable.
    VITESS_PROJECT_PATH = Path(os.getenv("VITESS_PROJECT_PATH", "/data/projects"))
    ARTIFACT_ROOT = Path(os.getenv("VITESS_ARTIFACT_ROOT", "/data/artifacts"))
    AUDIT_FILE = Path(
        os.getenv("VITESS_AUDIT_FILE", "/data/artifacts/audit.jsonl")
    )
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_DIR = Path(os.getenv("LOG_DIR", "/tmp/vitess-ai-logs"))
    EXECUTE_TIMEOUT_SECONDS = int(
        os.getenv("VITESS_SIMULATION_TIMEOUT_SECONDS", "3600")
    )

    # -- uploads ------------------------------------------------------------
    #: 100 MB. A trajectory file is the large one; a guide reflectivity table
    #: is a few kilobytes.
    MAX_UPLOAD_BYTES = int(os.getenv("VITESS_MAX_UPLOAD_BYTES", str(100 * 1024 * 1024)))
    UPLOAD_EXTENSIONS = _csv(
        "VITESS_UPLOAD_EXTENSIONS", ".dat,.txt,.csv,.inf,.nxs,.h5"
    )

    # -- serving ------------------------------------------------------------
    #: Container loopback. The API is not published; only the UI port is, and
    #: only on the host's loopback interface. Core refuses to pair a fixed
    #: principal with a reachable API, and this is the fact it checks.
    BIND_HOST = os.getenv("VITESS_BIND_HOST", "127.0.0.1")
    API_PORT = int(os.getenv("VITESS_API_PORT", "9600"))
    API_PUBLISHED = _flag("VITESS_API_PUBLISHED", False)
    UI_PORT = int(os.getenv("UI_PORT", "9601"))
    STREAM_TOOL_PAYLOADS = _flag("STREAM_TOOL_PAYLOADS", False)

    #: The single user of a local deployment, and it must be stable across
    #: restarts: it owns every thread and names the memory namespace. A value
    #: generated per process would orphan yesterday's conversations.
    LOCAL_USER_ID = UUID(
        os.getenv("VITESS_LOCAL_USER_ID", "00000000-0000-4000-8000-000000000001")
    )

    @classmethod
    def validate_required(cls) -> None:
        """Refuse to start on a configuration that cannot work.

        Deliberately short. The first-generation `Config.validate_required`
        printed warnings and carried on, which is how a deployment reaches its
        first conversation before discovering it has no database.
        """
        missing: list[str] = []
        if not cls.DATABASE_URL:
            missing.append("DATABASE_URL (Postgres holds threads and checkpoints)")
        if not (cls.OPENAI_API_KEY or cls.BLABLADOR_API_KEY):
            missing.append("OPENAI_API_KEY or BLABLADOR_API_KEY")
        if missing:
            raise RuntimeError(
                "vitess-ai cannot start; these are unset: " + "; ".join(missing)
            )
        if cls.API_PUBLISHED:
            raise RuntimeError(
                "VITESS_API_PUBLISHED is set, but this deployment authenticates "
                "nobody: every request is the same local principal. Publishing "
                "the API would let anyone on the network act as that user."
            )


def configure_core() -> None:
    """Hand core the ~22 fields it needs, as one frozen value object."""

    juena_core.configure(
        juena_core.CoreSettings(
            OPENAI_API_KEY=Config.OPENAI_API_KEY,
            BLABLADOR_API_KEY=Config.BLABLADOR_API_KEY,
            BLABLADOR_BASE_URL=Config.BLABLADOR_BASE_URL,
            MAX_TOKENS=Config.MAX_TOKENS,
            TIMEOUT_SECONDS=Config.TIMEOUT_SECONDS,
            MAX_RETRIES=Config.MAX_RETRIES,
            DEFAULT_PROVIDER=Config.DEFAULT_PROVIDER,
            DEFAULT_MODEL=Config.DEFAULT_MODEL,
            OPENAI_AVAILABLE_MODELS=None,
            BLABLADOR_AVAILABLE_MODELS=None,
            OPENAI_DEFAULT_MODEL=Config.OPENAI_DEFAULT_MODEL,
            BLABLADOR_DEFAULT_MODEL=Config.BLABLADOR_DEFAULT_MODEL,
            STREAM_TOOL_PAYLOADS=Config.STREAM_TOOL_PAYLOADS,
            DATABASE_URL=Config.DATABASE_URL,
            DATABASE_POOL_MAX_SIZE=Config.DATABASE_POOL_MAX_SIZE,
            SESSION_TTL_HOURS=Config.SESSION_TTL_HOURS,
            SESSION_COOKIE_SECURE=False,
            FALLBACK_PROVIDER=Config.FALLBACK_PROVIDER,
            # Core names this after what it times -- a specialist's execution
            # tool, whichever backend serves it. Here the backend is the MCP
            # server and the thing being timed is a VITESS pipeline.
            EXECUTE_TIMEOUT_SECONDS=Config.EXECUTE_TIMEOUT_SECONDS,
            ARTIFACT_ROOT=Config.ARTIFACT_ROOT,
            AUDIT_FILE=Config.AUDIT_FILE,
            LOG_LEVEL=Config.LOG_LEVEL,
            LOG_DIR=Config.LOG_DIR,
            BIND_HOST=Config.BIND_HOST,
            API_PUBLISHED=Config.API_PUBLISHED,
        )
    )
