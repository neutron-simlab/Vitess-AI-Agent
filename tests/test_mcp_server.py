"""The MCP server: what it advertises, what it runs, and how it refuses.

The pipeline tests use stand-in executables rather than VITESS itself, for the
same reason CP1's do: the real binaries exist only inside the image. What they
exercise is the real command generator, the real process pipeline and the real
catalog -- the stand-in is the physics, not the machinery.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from vitess_ai.mcp.connection import TOOL_NAMES
from vitess_ai.mcp.server import (
    inspect_thread,
    mcp,
    render_plot,
    run_pipeline,
)
from vitess_ai.mcp.settings import ServerSettings
from vitess_ai.modules.catalog import cli_executables, execution_order

THREAD_ID = "11111111-1111-4111-8111-111111111111"
RUN_ID = "22222222-2222-4222-8222-222222222222"
DATA = Path(__file__).parent / "data"


def _settings(tmp_path: Path, script: str = "#!/bin/sh\ncat\n") -> ServerSettings:
    """A project root and a modules root holding one stand-in per catalog row."""
    modules_root = tmp_path / "modules"
    modules_root.mkdir()
    for basename in cli_executables().values():
        binary = modules_root / basename
        binary.write_text(script, encoding="utf-8")
        binary.chmod(0o755)
    project_root = tmp_path / "projects"
    project_root.mkdir()
    return ServerSettings(
        project_root=project_root,
        modules_root=modules_root,
        host="127.0.0.1",
        port=9005,
        timeout_seconds=30,
    )


def _parameters() -> dict[str, dict[str, list[str]]]:
    return {name: {"cli_parameters": ["-a1"]} for name in execution_order()}


def _run_directory(settings: ServerSettings) -> Path:
    return settings.project_root / THREAD_ID / "outputs" / RUN_ID


def test_importing_the_server_does_not_import_the_agent_framework() -> None:
    """This process runs VITESS; it does not run an agent.

    The first-generation catalog dragged LangChain into the MCP server, and two
    hand-maintained fallback tables were written to escape it (CP2). The escape
    is only worth anything if the server stays clear. Run in a subprocess: this
    session has already imported plenty.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import vitess_ai.mcp.server, sys;"
            " print('langchain' in sys.modules, 'deepagents' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).resolve().parents[1],
    )

    assert result.stdout.split() == ["False", "False"]


def test_the_server_advertises_exactly_the_four_tools() -> None:
    """`generate_cli_command` is not among them: CP1 moved it out of MCP."""
    advertised = asyncio.run(mcp.list_tools())

    assert sorted(tool.name for tool in advertised) == sorted(TOOL_NAMES)


def test_the_raw_tools_take_ownership_arguments_and_so_are_never_bound_to_a_model() -> None:
    """Why the application needs a façade, pinned as a test rather than a comment.

    A model that could call these directly could name any thread's directory.
    The schema the server advertises is the schema a bound model would fill in,
    and middleware cannot remove a field from it -- so the guard is that these
    tools stay unbound, and CP3a's façade exposes only what a model may decide.
    """
    advertised = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    arguments = set(advertised["run_simulation"].parameters["properties"])

    assert {"thread_id", "simulation_run_id", "module_results"} <= arguments


def test_a_pipeline_runs_every_module_and_reports_each_exit_code(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    result = run_pipeline(
        settings,
        thread_id=THREAD_ID,
        simulation_run_id=RUN_ID,
        module_results=_parameters(),
        execution_order=list(execution_order()),
    )

    assert result.success is True
    assert result.timed_out is False
    assert [module.name for module in result.modules] == list(execution_order())
    assert {module.exit_code for module in result.modules} == {0}
    # Resolved paths, not "$V/read_in": the evidence names the file that ran.
    assert all(
        module.executable.startswith(str(settings.modules_root))
        for module in result.modules
    )


def test_produced_files_are_named_relative_to_the_run_directory(tmp_path: Path) -> None:
    """The application resolves them under its own mount of the same volume."""
    settings = _settings(tmp_path, script="#!/bin/sh\ncat > /dev/null\nprintf x > output.dat\n")

    result = run_pipeline(
        settings,
        thread_id=THREAD_ID,
        simulation_run_id=RUN_ID,
        module_results=_parameters(),
        execution_order=list(execution_order()),
    )

    listed = {file.path: file for file in result.files}
    assert "output.dat" in listed
    assert listed["output.dat"].kind == "data"
    assert listed["output.dat"].size_bytes == 1
    assert listed["result.txt"].kind == "log"
    assert all(not Path(file.path).is_absolute() for file in result.files)


def test_a_failing_module_fails_the_simulation_with_its_exit_code(tmp_path: Path) -> None:
    settings = _settings(tmp_path, script="#!/bin/sh\ncat > /dev/null\nexit 3\n")

    result = run_pipeline(
        settings,
        thread_id=THREAD_ID,
        simulation_run_id=RUN_ID,
        module_results=_parameters(),
        execution_order=list(execution_order()),
    )

    assert result.success is False
    assert {module.exit_code for module in result.modules} == {3}


def test_a_module_missing_from_the_parameters_runs_nothing(tmp_path: Path) -> None:
    """CP1's correction, reaching the tool result.

    The first-generation tool logged the missing module, dropped it, and
    returned success with the dropped module still listed as included. A guide
    could disappear from the beamline and the run would read as a success.
    """
    settings = _settings(tmp_path)
    parameters = _parameters()
    del parameters["guide"]

    result = run_pipeline(
        settings,
        thread_id=THREAD_ID,
        simulation_run_id=RUN_ID,
        module_results=parameters,
        execution_order=list(execution_order()),
    )

    assert result.success is False
    assert "guide" in result.message
    assert result.modules == ()
    assert not _run_directory(settings).exists()


def test_a_validation_error_payload_is_refused_before_anything_starts(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    parameters = _parameters()
    parameters["writeout"] = {"cli_parameters": ["-a1"], "errors": ["sOutFileName"]}

    result = run_pipeline(
        settings,
        thread_id=THREAD_ID,
        simulation_run_id=RUN_ID,
        module_results=parameters,
        execution_order=list(execution_order()),
    )

    assert result.success is False
    assert "writeout" in result.message
    assert result.modules == ()
    assert not _run_directory(settings).exists()


@pytest.mark.parametrize(
    "thread_id",
    ["../etc", "not-a-uuid", "11111111-1111-4111-8111-11111111111Z", ""],
)
def test_an_identifier_that_is_not_a_uuid_raises(tmp_path: Path, thread_id: str) -> None:
    """Raised, not returned: these arrive from trusted code, so this is a bug."""
    settings = _settings(tmp_path)

    with pytest.raises(ToolError, match="thread_id"):
        run_pipeline(
            settings,
            thread_id=thread_id,
            simulation_run_id=RUN_ID,
            module_results=_parameters(),
            execution_order=list(execution_order()),
        )


def test_inspection_lists_the_upload_slots_the_catalog_declares(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    staged = settings.project_root / THREAD_ID / "uploads" / "readin"
    staged.mkdir(parents=True)
    (staged / "beam.dat").write_text("data", encoding="utf-8")

    inspection = inspect_thread(settings, thread_id=THREAD_ID)

    assert inspection.exists is True
    assert [upload.module for upload in inspection.uploads] == ["readin", "instrument", "guide"]
    readin = inspection.uploads[0]
    assert [file.path for file in readin.files] == ["uploads/readin/beam.dat"]
    assert readin.files[0].size_bytes == 4


def test_inspection_of_a_thread_with_nothing_in_it_is_not_an_error(tmp_path: Path) -> None:
    inspection = inspect_thread(_settings(tmp_path), thread_id=THREAD_ID)

    assert inspection.exists is False
    assert inspection.uploads == ()
    assert inspection.runs == ()


def test_inspection_lists_one_entry_per_simulation_run(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    run_directory = _run_directory(settings)
    run_directory.mkdir(parents=True)
    (run_directory / "monitor1D.dat").write_text("x", encoding="utf-8")

    inspection = inspect_thread(settings, thread_id=THREAD_ID)

    assert [run.simulation_run_id for run in inspection.runs] == [RUN_ID]
    assert [file.path for file in inspection.runs[0].files] == [
        f"outputs/{RUN_ID}/monitor1D.dat"
    ]


def test_a_plot_is_rendered_from_the_filename_the_schema_owns(tmp_path: Path) -> None:
    """No filename argument, so the default is the one being exercised."""
    settings = _settings(tmp_path)
    run_directory = _run_directory(settings)
    run_directory.mkdir(parents=True)
    shutil.copy(DATA / "monitor1D.dat", run_directory / "monitor1D.dat")

    plot = render_plot(
        settings, kind="monitor1d", thread_id=THREAD_ID, simulation_run_id=RUN_ID
    )

    assert plot.source == "monitor1D.dat"
    assert plot.path == "monitor1D.png"
    assert (run_directory / "monitor1D.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert plot.size_bytes == (run_directory / "monitor1D.png").stat().st_size


def test_asking_for_a_plot_of_a_run_that_produced_none_is_an_error(tmp_path: Path) -> None:
    """Not an empty plot. A monitor that did not run produced no data."""
    settings = _settings(tmp_path)
    _run_directory(settings).mkdir(parents=True)

    with pytest.raises(ToolError, match="monitor1D.dat"):
        render_plot(
            settings, kind="monitor1d", thread_id=THREAD_ID, simulation_run_id=RUN_ID
        )


def test_a_plot_filename_that_is_a_path_is_refused(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _run_directory(settings).mkdir(parents=True)

    with pytest.raises(ToolError, match="plain file name"):
        render_plot(
            settings,
            kind="monitor1d",
            thread_id=THREAD_ID,
            simulation_run_id=RUN_ID,
            filename="../../../etc/passwd",
        )


def test_asking_the_1d_tool_for_a_2d_file_is_refused(tmp_path: Path) -> None:
    """The file says which monitor wrote it, and a mismatch is a wrong answer."""
    settings = _settings(tmp_path)
    run_directory = _run_directory(settings)
    run_directory.mkdir(parents=True)
    shutil.copy(DATA / "monitor2D-F1.dat", run_directory / "monitor1D.dat")

    with pytest.raises(ToolError, match="monitor2d monitor file"):
        render_plot(
            settings, kind="monitor1d", thread_id=THREAD_ID, simulation_run_id=RUN_ID
        )


def test_the_result_is_json_serialisable_because_it_crosses_a_container_boundary(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)

    result = run_pipeline(
        settings,
        thread_id=THREAD_ID,
        simulation_run_id=RUN_ID,
        module_results=_parameters(),
        execution_order=list(execution_order()),
    )

    payload = json.loads(result.model_dump_json())
    assert payload["simulation_run_id"] == RUN_ID
    assert len(payload["modules"]) == len(execution_order())
