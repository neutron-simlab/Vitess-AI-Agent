"""What ``GET /health`` actually checks.

An explicit route, because the alternative -- asking whether something answers
on the MCP port -- proves only that a Python process started. This server exists
to run VITESS binaries into a shared volume, so health is: **the binaries the
catalog names resolve inside the trusted modules root, and the project volume
can be written.** Both are things a misconfigured mount silently breaks.

Compose uses the same route with ``condition: service_healthy``, so a failure
here keeps the application from ever being constructed against a server that
cannot work.
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict

from vitess_ai.cli.command import resolve_executable
from vitess_ai.mcp.settings import ServerSettings
from vitess_ai.modules.catalog import cli_executables

__all__ = ["HealthCheck", "HealthReport", "check_health"]

#: Written and removed by the volume check. Named for what it is, so that a file
#: left behind by a killed process is recognisable rather than mysterious.
PROBE_FILENAME = ".health-probe"


class HealthCheck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    ok: bool
    #: Says what was found, not merely that something was wrong. A health route
    #: whose failure needs a debugging session has not helped.
    detail: str


class HealthReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["healthy", "unhealthy"]
    checks: tuple[HealthCheck, ...]


def _check_modules(settings: ServerSettings) -> HealthCheck:
    missing: list[str] = []
    for module, basename in sorted(cli_executables().items()):
        try:
            resolve_executable(settings.modules_root, basename)
        except (OSError, ValueError) as exc:
            missing.append(f"{module} ({basename}): {exc}")
    if missing:
        return HealthCheck(
            name="vitess_modules",
            ok=False,
            detail=f"{settings.modules_root} is missing executables: "
            + "; ".join(missing),
        )
    return HealthCheck(
        name="vitess_modules",
        ok=True,
        detail=f"{len(cli_executables())} executables resolve under {settings.modules_root}",
    )


def _check_project_volume(settings: ServerSettings) -> HealthCheck:
    probe = settings.project_root / PROBE_FILENAME
    try:
        settings.project_root.mkdir(parents=True, exist_ok=True)
        probe.write_text(str(os.getpid()), encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return HealthCheck(
            name="project_volume",
            ok=False,
            detail=f"{settings.project_root} is not writable: {exc}",
        )
    return HealthCheck(
        name="project_volume",
        ok=True,
        detail=f"{settings.project_root} is writable",
    )


def check_health(settings: ServerSettings) -> HealthReport:
    """Run every check and report. Never raises: an unhealthy server answers."""
    checks = (_check_modules(settings), _check_project_volume(settings))
    status = "healthy" if all(check.ok for check in checks) else "unhealthy"
    return HealthReport(status=status, checks=checks)
