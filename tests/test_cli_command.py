from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from vitess_ai.cli.command import COMMON_ARGUMENTS, generate_cli_command
from vitess_ai.mcp.execution import execute_pipeline, postprocess_logs


THREAD_ID = "11111111-1111-4111-8111-111111111111"
SIMULATION_RUN_ID = "22222222-2222-4222-8222-222222222222"
EXECUTABLES = {
    "readin": "read_in",
    "guide": "guide_parallel",
    "writeout": "writeout",
    "monitor1d": "monitor1D",
    "monitor2d": "monitor2D",
}


def _make_modules_path(tmp_path: Path) -> Path:
    modules_path = tmp_path / "modules"
    modules_path.mkdir()
    for basename in EXECUTABLES.values():
        executable = modules_path / basename
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
    return modules_path


def _generate(
    tmp_path: Path,
    module_results: dict,
    execution_order: list[str],
    *,
    executable_mapping: dict[str, str] | None = None,
) -> dict:
    return generate_cli_command(
        module_results,
        execution_order,
        thread_id=THREAD_ID,
        simulation_run_id=SIMULATION_RUN_ID,
        project_path=tmp_path / "projects",
        modules_path=_make_modules_path(tmp_path),
        module_executables=executable_mapping or EXECUTABLES,
    )


def test_argument_vector_golden_all_five_modules(tmp_path: Path) -> None:
    module_results = {
        "readin": {
            "cli_parameters": ["-f1", "-F0", "-Ainput file.dat", "-a1.0"]
        },
        "guide": {
            "cli_parameters": ["-Y1", "-Z1", "-w3.0", "-h3.0", "-Sshape.dat"]
        },
        "writeout": {"cli_parameters": ["-Aoutput.dat", "-a1", "-c111111111"]},
        "monitor1d": {"cli_parameters": ["-Omonitor1D.dat", "-X1", "-x100"]},
        "monitor2d": {
            "cli_parameters": ["-Omonitor2D.dat", "-X1", "-Y2", "-x100", "-y50"]
        },
    }
    result = _generate(tmp_path, module_results, list(EXECUTABLES))

    run_directory = (
        (tmp_path / "projects").resolve()
        / THREAD_ID
        / "outputs"
        / SIMULATION_RUN_ID
    )
    log_prefix = run_directory / f"log-{SIMULATION_RUN_ID}-"
    modules_path = (tmp_path / "modules").resolve()
    expected = [
        [
            str(modules_path / "read_in"),
            *COMMON_ARGUMENTS,
            f"--P{run_directory}",
            "--N1",
            f"--L{log_prefix}01",
            "-f1",
            "-F0",
            "-Ainput file.dat",
            "-a1.0",
        ],
        [
            str(modules_path / "guide_parallel"),
            *COMMON_ARGUMENTS,
            f"--P{run_directory}",
            "--N2",
            f"--L{log_prefix}02",
            "-Y1",
            "-Z1",
            "-w3.0",
            "-h3.0",
            "-Sshape.dat",
        ],
        [
            str(modules_path / "writeout"),
            *COMMON_ARGUMENTS,
            f"--P{run_directory}",
            "--N3",
            f"--L{log_prefix}03",
            "-Aoutput.dat",
            "-a1",
            "-c111111111",
        ],
        [
            str(modules_path / "monitor1D"),
            *COMMON_ARGUMENTS,
            f"--P{run_directory}",
            "--N4",
            f"--L{log_prefix}04",
            "-Omonitor1D.dat",
            "-X1",
            "-x100",
        ],
        [
            str(modules_path / "monitor2D"),
            *COMMON_ARGUMENTS,
            f"--P{run_directory}",
            "--N5",
            f"--L{log_prefix}05",
            "-Omonitor2D.dat",
            "-X1",
            "-Y2",
            "-x100",
            "-y50",
        ],
    ]

    assert result["success"] is True
    assert result["argument_vectors"] == expected
    assert result["modules_included"] == list(EXECUTABLES)
    assert all("$" not in element for vector in expected for element in vector)


def test_display_command_golden_is_display_only(tmp_path: Path) -> None:
    result = _generate(
        tmp_path,
        {"readin": {"cli_parameters": ["-f1", "-Ainput file.dat"]}},
        ["readin"],
    )
    run_directory = (
        (tmp_path / "projects").resolve()
        / THREAD_ID
        / "outputs"
        / SIMULATION_RUN_ID
    )
    executable = (tmp_path / "modules" / "read_in").resolve()
    expected = (
        f"{executable} --Z1 --U1.0e-25 --G1 --T0 --B10000 "
        f"--P{run_directory} --N1 "
        f"--L{run_directory}/log-{SIMULATION_RUN_ID}-01 "
        "-f1 '-Ainput file.dat'"
    )

    assert result["display_command"] == expected
    assert result["cli_command"] == expected


def test_missing_module_fails_closed_and_reports_only_emitted_modules(
    tmp_path: Path,
) -> None:
    result = _generate(
        tmp_path,
        {"readin": {"cli_parameters": ["-f1"]}},
        ["readin", "guide"],
    )

    assert result["success"] is False
    assert "guide" in result["error"]
    assert result["modules_included"] == ["readin"]
    assert len(result["argument_vectors"]) == 1


def test_empty_module_results_fail_closed(tmp_path: Path) -> None:
    result = _generate(tmp_path, {}, [])

    assert result["success"] is False
    assert result["modules_included"] == []
    assert result["argument_vectors"] == []


@pytest.mark.parametrize("cli_parameters", [None, "-f1 -F0", []])
def test_missing_or_shell_shaped_cli_parameters_fail_closed(
    tmp_path: Path, cli_parameters: object
) -> None:
    result = _generate(
        tmp_path,
        {"readin": {"cli_parameters": cli_parameters}},
        ["readin"],
    )

    assert result["success"] is False
    assert "readin" in result["error"]


def test_missing_executable_mapping_fails_closed(tmp_path: Path) -> None:
    result = _generate(
        tmp_path,
        {"readin": {"cli_parameters": ["-f1"]}},
        ["readin"],
        executable_mapping={"guide": "guide_parallel"},
    )

    assert result["success"] is False
    assert "executable mapping" in result["error"]


@pytest.mark.parametrize(
    "argument",
    [
        "-Afile with space.dat",
        "-Atitle;touch marker",
        "-A$(touch marker)",
        "-A-leading-dash.dat",
    ],
)
def test_shell_metacharacters_remain_one_argument(
    tmp_path: Path, argument: str
) -> None:
    result = _generate(
        tmp_path,
        {"readin": {"cli_parameters": [argument]}},
        ["readin"],
    )

    assert result["success"] is True
    assert result["argument_vectors"][0][-1] == argument


def test_parent_traversal_parameter_is_rejected(tmp_path: Path) -> None:
    result = _generate(
        tmp_path,
        {"readin": {"cli_parameters": ["-A../outside.dat"]}},
        ["readin"],
    )

    assert result["success"] is False
    assert "parent traversal" in result["error"]


def test_absolute_parameter_path_must_remain_under_project_root(
    tmp_path: Path,
) -> None:
    result = _generate(
        tmp_path,
        {"readin": {"cli_parameters": ["-A/etc/passwd"]}},
        ["readin"],
    )

    assert result["success"] is False
    assert "escapes project_path" in result["error"]


def test_absolute_upload_path_under_project_root_remains_one_argument(
    tmp_path: Path,
) -> None:
    upload = (
        tmp_path
        / "projects"
        / THREAD_ID
        / "uploads"
        / "readin"
        / "input file.dat"
    ).resolve()
    result = _generate(
        tmp_path,
        {"readin": {"cli_parameters": [f"-A{upload}"]}},
        ["readin"],
    )

    assert result["success"] is True
    assert result["argument_vectors"][0][-1] == f"-A{upload}"


@pytest.mark.parametrize("basename", ["$V/read_in", "../read_in", "missing"])
def test_untrusted_or_missing_executable_is_rejected(
    tmp_path: Path, basename: str
) -> None:
    result = _generate(
        tmp_path,
        {"readin": {"cli_parameters": ["-f1"]}},
        ["readin"],
        executable_mapping={"readin": basename},
    )

    assert result["success"] is False
    assert result["modules_included"] == []


def test_non_executable_module_file_is_rejected(tmp_path: Path) -> None:
    modules_path = _make_modules_path(tmp_path)
    (modules_path / "read_in").chmod(0o644)

    result = generate_cli_command(
        {"readin": {"cli_parameters": ["-f1"]}},
        ["readin"],
        thread_id=THREAD_ID,
        simulation_run_id=SIMULATION_RUN_ID,
        project_path=tmp_path / "projects",
        modules_path=modules_path,
        module_executables=EXECUTABLES,
    )

    assert result["success"] is False
    assert "not an executable file" in result["error"]


@pytest.mark.parametrize(
    ("field", "value"),
    [("thread_id", "../thread"), ("simulation_run_id", "not-a-uuid")],
)
def test_untrusted_identifiers_are_rejected(
    tmp_path: Path, field: str, value: str
) -> None:
    modules_path = _make_modules_path(tmp_path)
    arguments = {
        "thread_id": THREAD_ID,
        "simulation_run_id": SIMULATION_RUN_ID,
        field: value,
    }
    with pytest.raises(ValueError, match=field):
        generate_cli_command(
            {"readin": {"cli_parameters": ["-f1"]}},
            ["readin"],
            project_path=tmp_path / "projects",
            modules_path=modules_path,
            module_executables=EXECUTABLES,
            **arguments,
        )


def _python(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def _execute(tmp_path: Path, vectors: list[list[str]], names: list[str]) -> dict:
    run_directory = tmp_path / "run"
    return execute_pipeline(
        vectors,
        names,
        run_directory=run_directory,
        log_prefix=run_directory / "log-test-",
        timeout_seconds=2,
        termination_grace_seconds=0.1,
    )


def test_pipeline_fails_when_early_module_fails(tmp_path: Path) -> None:
    result = _execute(
        tmp_path,
        [
            _python("raise SystemExit(7)"),
            _python("import sys; sys.stdin.buffer.read()"),
        ],
        ["readin", "guide"],
    )

    assert result["success"] is False
    assert [module["exit_code"] for module in result["modules"]] == [7, 0]


def test_pipeline_fails_when_middle_module_fails(tmp_path: Path) -> None:
    result = _execute(
        tmp_path,
        [
            _python("import sys; sys.stdout.write('neutrons')"),
            _python("import sys; sys.stdin.buffer.read(); raise SystemExit(9)"),
            _python("import sys; sys.stdin.buffer.read()"),
        ],
        ["readin", "guide", "writeout"],
    )

    assert result["success"] is False
    assert [module["exit_code"] for module in result["modules"]] == [0, 9, 0]


def test_timeout_terminates_every_surviving_child(tmp_path: Path) -> None:
    run_directory = tmp_path / "run"
    result = execute_pipeline(
        [
            _python("import time; time.sleep(30)"),
            _python("import time; time.sleep(30)"),
        ],
        ["readin", "guide"],
        run_directory=run_directory,
        log_prefix=run_directory / "log-test-",
        timeout_seconds=0.1,
        termination_grace_seconds=0.1,
    )

    assert result["success"] is False
    assert result["timed_out"] is True
    for module in result["modules"]:
        assert module["exit_code"] is not None
        with pytest.raises(ProcessLookupError):
            os.kill(module["pid"], 0)


def test_postprocessing_is_scoped_to_one_run(tmp_path: Path) -> None:
    run_directory = tmp_path / "run"
    run_directory.mkdir()
    prefix = run_directory / "log-run-"
    (run_directory / "log-run-01").write_bytes(b"first\n")
    (run_directory / "log-run-02").write_bytes(b"second\n")
    unrelated = run_directory / "log-other-01"
    unrelated.write_bytes(b"keep\n")
    (run_directory / "result.txt").write_bytes(b"stale\n")

    result_file = postprocess_logs(run_directory, prefix)

    assert result_file.read_bytes() == b"first\nsecond\n"
    assert not (run_directory / "log-run-01").exists()
    assert not (run_directory / "log-run-02").exists()
    assert unrelated.read_bytes() == b"keep\n"
