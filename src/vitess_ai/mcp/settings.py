"""Where the MCP server finds VITESS and where it is allowed to write.

Two paths and a listening address, read from the environment once at startup
and then frozen. Both paths are also mount points in ``docker-compose.yml``,
which is the only place they are set in a real deployment.

Deliberately not `juena_core.config`: this process runs no agent, and core's
settings carry provider keys, a database URL and an artifact root that mean
nothing here. Reading four variables directly is smaller than the seam that
would share them.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

__all__ = ["ServerSettings"]

DEFAULT_PROJECT_PATH = "/data/projects"
DEFAULT_MODULES_PATH = "/vitess/MODULES"
DEFAULT_PORT = 9005


@dataclass(frozen=True)
class ServerSettings:
    """The MCP server's whole configuration."""

    #: The shared volume. Every path this server reads or writes is beneath it,
    #: and the application container mounts the same volume at the same path.
    project_root: Path
    #: The directory holding the VITESS executables -- ``$V`` in the shell
    #: scripts the first-generation agent generated. Nothing outside it runs.
    modules_root: Path
    host: str
    port: int
    #: How long one pipeline may run before every process in it is stopped.
    timeout_seconds: float

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> "ServerSettings":
        """Read the settings, converting and rejecting rather than defaulting.

        A bad number raises here, at startup, rather than at the first
        simulation an hour later.
        """
        env = os.environ if environment is None else environment
        return cls(
            project_root=Path(
                env.get("VITESS_PROJECT_PATH") or DEFAULT_PROJECT_PATH
            ).expanduser(),
            modules_root=Path(
                env.get("VITESS_MODULES_PATH") or DEFAULT_MODULES_PATH
            ).expanduser(),
            host=env.get("VITESS_MCP_HOST") or "0.0.0.0",
            port=_port(env, "VITESS_MCP_PORT", DEFAULT_PORT),
            timeout_seconds=_positive_float(
                env, "VITESS_SIMULATION_TIMEOUT_SECONDS", 3600.0
            ),
        )


def _positive_int(environment: Mapping[str, str], name: str, default: int) -> int:
    raw = environment.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")
    return value


def _port(environment: Mapping[str, str], name: str, default: int) -> int:
    value = _positive_int(environment, name, default)
    if value > 65535:
        raise ValueError(f"{name} must be at most 65535, got {value}")
    return value


def _positive_float(environment: Mapping[str, str], name: str, default: float) -> float:
    raw = environment.get(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number, got {value}")
    return value
