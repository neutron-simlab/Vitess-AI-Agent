"""The health route's two checks, which are what Compose gates the app on."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from vitess_ai.mcp.health import check_health
from vitess_ai.mcp.settings import ServerSettings
from vitess_ai.modules.catalog import cli_executables


def _settings(project_root: Path, modules_root: Path) -> ServerSettings:
    return ServerSettings(
        project_root=project_root,
        modules_root=modules_root,
        host="127.0.0.1",
        port=9005,
        timeout_seconds=30,
    )


def _install_modules(modules_root: Path, names: list[str] | None = None) -> None:
    modules_root.mkdir(parents=True, exist_ok=True)
    for basename in names if names is not None else list(cli_executables().values()):
        binary = modules_root / basename
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        binary.chmod(0o755)


def test_a_complete_install_is_healthy(tmp_path: Path) -> None:
    _install_modules(tmp_path / "modules")

    report = check_health(_settings(tmp_path / "projects", tmp_path / "modules"))

    assert report.status == "healthy"
    assert [check.name for check in report.checks] == [
        "vitess_modules",
        "project_volume",
    ]


def test_a_missing_executable_is_unhealthy_and_says_which(tmp_path: Path) -> None:
    """The failure a wrong VITESS mount produces, which a port check cannot see."""
    installed = list(cli_executables().values())
    installed.remove("guide_parallel")
    _install_modules(tmp_path / "modules", installed)

    report = check_health(_settings(tmp_path / "projects", tmp_path / "modules"))
    modules_check = report.checks[0]

    assert report.status == "unhealthy"
    assert modules_check.ok is False
    assert "guide_parallel" in modules_check.detail


def test_an_executable_that_is_not_executable_is_unhealthy(tmp_path: Path) -> None:
    _install_modules(tmp_path / "modules")
    (tmp_path / "modules" / "writeout").chmod(0o644)

    report = check_health(_settings(tmp_path / "projects", tmp_path / "modules"))

    assert report.status == "unhealthy"
    assert "writeout" in report.checks[0].detail


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write to a read-only directory")
def test_a_project_volume_that_cannot_be_written_is_unhealthy(tmp_path: Path) -> None:
    """A volume mounted read-only, or owned by another user: the same symptom."""
    _install_modules(tmp_path / "modules")
    projects = tmp_path / "projects"
    projects.mkdir()
    projects.chmod(0o500)
    try:
        report = check_health(_settings(projects, tmp_path / "modules"))
    finally:
        projects.chmod(0o700)

    assert report.status == "unhealthy"
    assert report.checks[1].ok is False
    assert str(projects) in report.checks[1].detail


def test_the_health_check_leaves_no_probe_file_behind(tmp_path: Path) -> None:
    _install_modules(tmp_path / "modules")
    projects = tmp_path / "projects"

    check_health(_settings(projects, tmp_path / "modules"))

    assert list(projects.iterdir()) == []


def test_concurrent_health_checks_do_not_share_a_probe_filename(tmp_path: Path) -> None:
    _install_modules(tmp_path / "modules")
    projects = tmp_path / "projects"
    settings = _settings(projects, tmp_path / "modules")

    with ThreadPoolExecutor(max_workers=8) as executor:
        reports = list(executor.map(lambda _: check_health(settings), range(32)))

    assert {report.status for report in reports} == {"healthy"}
    assert list(projects.iterdir()) == []


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "0", "-1"])
def test_timeout_must_be_finite_and_positive(value: str) -> None:
    with pytest.raises(ValueError, match="finite positive"):
        ServerSettings.from_environment(
            {"VITESS_SIMULATION_TIMEOUT_SECONDS": value}
        )


def test_port_must_fit_the_tcp_port_range() -> None:
    with pytest.raises(ValueError, match="at most 65535"):
        ServerSettings.from_environment({"VITESS_MCP_PORT": "65536"})
