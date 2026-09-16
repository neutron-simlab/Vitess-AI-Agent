"""The VITESS MCP server: four tools and a health route, over HTTP.

It runs as its own Compose service on the internal network, reachable at
``http://vitess-mcp:9005/mcp`` from the application container and from nowhere
else. Not stdio, which would spawn one copy of this process per client -- all of
them running VITESS binaries into the same project directory -- and would make
standard output the transport, so that one stray ``print`` in a tool corrupts
the protocol silently.

**This module imports no agent framework.** It is reached over HTTP by an
application that has one; it does not need one itself, and a test asserts that
importing it pulls in neither ``langchain`` nor ``deepagents``. Logging is the
standard library's for the same reason.

Two kinds of failure, deliberately different:

*Raised* (``ToolError``) -- the arguments are malformed. Every argument here
comes from trusted application code, never from a model: the application façade
(03/CP3a) is what a model calls, and it fills in the thread, the run id and the
validated parameters itself. A bad one is a bug, and bugs should be loud.

*Returned* (``SimulationResult`` with ``success=False``) -- the simulation ran,
or was refused, and that outcome is what the model needs to read. A simulation
that did not run must never read as one that ran and produced nothing.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from starlette.requests import Request
from starlette.responses import JSONResponse

from vitess_ai.cli.command import canonical_uuid, generate_cli_command
from vitess_ai.mcp.execution import RESULT_FILENAME, execute_pipeline
from vitess_ai.mcp.health import check_health
from vitess_ai.mcp.payloads import (
    FileKind,
    ModuleExecution,
    ModuleUploads,
    PlotResult,
    RunFile,
    RunFolder,
    SimulationResult,
    ThreadInspection,
    UploadedFile,
)
from vitess_ai.mcp.settings import ServerSettings
from vitess_ai.modules.catalog import cli_executables, upload_modules
from vitess_ai.plots import MonitorFileError, read_monitor_file, render_monitor_png
from vitess_ai.schema import Monitor1DParameters, Monitor2DParameters

__all__ = ["mcp", "SETTINGS", "run_pipeline", "inspect_thread", "render_plot"]

logger = logging.getLogger(__name__)

SETTINGS = ServerSettings.from_environment()

mcp = FastMCP("VITESS Simulation Server")

#: The monitor file each plot tool reads unless the caller names another. Taken
#: from the parameter schema, which owns these names (CP2): the catalog used to
#: carry a second copy and the two had already drifted.
DEFAULT_MONITOR_FILENAMES = {
    "monitor1d": Monitor1DParameters.model_fields["fMonitorFilename"].default,
    "monitor2d": Monitor2DParameters.model_fields["fMonitorFilename"].default,
}


# ---------------------------------------------------------------------------
# Paths. Every one of them is built from validated identifiers and checked to
# be inside the project volume before anything reads or writes.
# ---------------------------------------------------------------------------


def _require_uuid(value: str, field_name: str) -> str:
    try:
        return canonical_uuid(value, field_name)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


def _resolve_beneath(root: Path, candidate: Path, *, label: str) -> Path:
    """Resolve ``candidate`` and require it to remain below ``root``.

    The identifiers joined into these paths are canonical UUIDs, but an
    existing directory in the shared volume can still be a symbolic link. A
    lexical ``root / uuid`` check does not protect a later read through that
    link, so every directory boundary is resolved before use.
    """
    trusted_root = root.resolve()
    if candidate.is_symlink():
        raise ToolError(f"{label} must not be a symbolic link")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(trusted_root)
    except ValueError as exc:
        raise ToolError(f"{label} escapes its trusted root") from exc
    return resolved


def _thread_root(settings: ServerSettings, thread_id: str) -> tuple[str, Path]:
    canonical = _require_uuid(thread_id, "thread_id")
    project_root = settings.project_root.expanduser().resolve()
    thread_root = _resolve_beneath(
        project_root,
        project_root / canonical,
        label="Thread directory",
    )
    return canonical, thread_root


def _run_directory(
    settings: ServerSettings, thread_id: str, simulation_run_id: str
) -> tuple[str, str, Path]:
    canonical_thread, thread_root = _thread_root(settings, thread_id)
    canonical_run = _require_uuid(simulation_run_id, "simulation_run_id")
    outputs_root = _resolve_beneath(
        thread_root,
        thread_root / "outputs",
        label="Outputs directory",
    )
    run_directory = _resolve_beneath(
        thread_root,
        outputs_root / canonical_run,
        label="Simulation run directory",
    )
    return canonical_thread, canonical_run, run_directory


def _run_file(run_directory: Path, filename: str) -> Path:
    """Resolve a file the caller named, refusing anything outside the run."""
    if (
        not filename
        or filename in {".", ".."}
        or "\0" in filename
        or "/" in filename
        or "\\" in filename
        or Path(filename).name != filename
    ):
        raise ToolError(f"Not a plain file name: {filename!r}")
    return _resolve_beneath(
        run_directory,
        run_directory / filename,
        label="Run file",
    )


# ---------------------------------------------------------------------------
# Listing what is on the volume
# ---------------------------------------------------------------------------


def _file_kind(relative: Path) -> FileKind:
    if relative.suffix.lower() == ".png":
        return "plot"
    if relative.name == RESULT_FILENAME:
        return "log"
    return "data"


def _describe_files(base: Path, directory: Path) -> tuple[UploadedFile, ...]:
    directory = _resolve_beneath(base, directory, label="Listed directory")
    if not directory.is_dir():
        return ()
    described: list[UploadedFile] = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        stat = path.stat()
        described.append(
            UploadedFile(
                path=str(path.relative_to(base)),
                size_bytes=stat.st_size,
                modified_at=_isoformat(stat.st_mtime),
            )
        )
    return tuple(described)


def _isoformat(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _collect_run_files(run_directory: Path) -> tuple[RunFile, ...]:
    """Every file the run produced, named relative to the run directory.

    Symbolic links are skipped rather than followed: the application resolves
    these paths under its own mount, and a link is the one way a path inside the
    run could point outside the volume.
    """
    if not run_directory.is_dir():
        return ()
    collected: list[RunFile] = []
    for path in sorted(run_directory.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(run_directory)
        collected.append(
            RunFile(
                path=str(relative),
                kind=_file_kind(relative),
                size_bytes=path.stat().st_size,
            )
        )
    return tuple(collected)


# ---------------------------------------------------------------------------
# The three implementations. The tools below are thin wrappers so that these
# can be tested against a temporary project root without a running server.
# ---------------------------------------------------------------------------


def _refused(
    thread_id: str, simulation_run_id: str, message: str
) -> SimulationResult:
    """Nothing was started, and the empty module list says exactly that."""
    return SimulationResult(
        success=False,
        timed_out=False,
        thread_id=thread_id,
        simulation_run_id=simulation_run_id,
        message=message,
    )


def _find_validation_error(module_results: Mapping[str, Any]) -> str | None:
    for module, result in module_results.items():
        if not isinstance(result, Mapping):
            continue
        if result.get("validation_status") is False or "errors" in result:
            return (
                f"Module '{module}' carries a validation error result; only "
                "validated parameters may be executed."
            )
    return None


def run_pipeline(
    settings: ServerSettings,
    *,
    thread_id: str,
    simulation_run_id: str,
    module_results: Mapping[str, Mapping[str, Any]],
    execution_order: Sequence[str],
) -> SimulationResult:
    """Build the argument vectors and run them, reporting what each process did."""
    canonical_thread, canonical_run, run_directory = _run_directory(
        settings, thread_id, simulation_run_id
    )

    refusal = _find_validation_error(module_results)
    if refusal is not None:
        return _refused(canonical_thread, canonical_run, refusal)

    try:
        generated = generate_cli_command(
            module_results,
            execution_order,
            thread_id=canonical_thread,
            simulation_run_id=canonical_run,
            project_path=settings.project_root,
            modules_path=settings.modules_root,
            module_executables=cli_executables(),
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from exc

    if not generated["success"]:
        # CP1's decision: a module that cannot be emitted stops the pipeline.
        # The first-generation tool dropped it and reported success, so a
        # simulation could quietly run without its guide.
        return _refused(canonical_thread, canonical_run, generated["message"])

    try:
        run_directory.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise ToolError(
            f"Simulation run {canonical_run} already exists; run identifiers "
            "must be unique so new evidence cannot be mixed with old files."
        ) from exc
    except OSError as exc:
        raise ToolError(f"Cannot create simulation run directory: {exc}") from exc
    outcome = execute_pipeline(
        generated["argument_vectors"],
        generated["modules_included"],
        run_directory=run_directory,
        log_prefix=generated["log_prefix"],
        timeout_seconds=settings.timeout_seconds,
    )

    modules = tuple(
        ModuleExecution(
            name=module["name"],
            executable=module["executable"],
            exit_code=module["exit_code"],
            started_at=module["started_at"],
            ended_at=module["ended_at"],
            stdout_tail=module["stdout_tail"],
            stderr_tail=module["stderr_tail"],
        )
        for module in outcome["modules"]
    )
    logger.info(
        "Simulation %s for thread %s: success=%s modules=%d",
        canonical_run,
        canonical_thread,
        outcome["success"],
        len(modules),
    )
    return SimulationResult(
        success=outcome["success"],
        timed_out=outcome["timed_out"],
        thread_id=canonical_thread,
        simulation_run_id=canonical_run,
        modules=modules,
        files=_collect_run_files(run_directory),
        message=outcome["message"],
    )


def inspect_thread(settings: ServerSettings, *, thread_id: str) -> ThreadInspection:
    """List the staged inputs and the completed runs for one conversation."""
    canonical_thread, thread_root = _thread_root(settings, thread_id)
    if not thread_root.is_dir():
        return ThreadInspection(
            thread_id=canonical_thread,
            exists=False,
            message="Nothing has been staged or produced for this conversation yet.",
        )

    uploads_root = _resolve_beneath(
        thread_root,
        thread_root / "uploads",
        label="Uploads directory",
    )
    uploads = tuple(
        ModuleUploads(
            module=spec.name,
            files=_describe_files(thread_root, uploads_root / spec.name),
        )
        for spec in upload_modules()
    )

    outputs_root = _resolve_beneath(
        thread_root,
        thread_root / "outputs",
        label="Outputs directory",
    )
    runs: list[RunFolder] = []
    if outputs_root.is_dir():
        # One directory per simulation run. Loose files directly under
        # outputs/ are a first-generation layout that this server never writes.
        for directory in sorted(outputs_root.iterdir()):
            if directory.is_dir() and not directory.is_symlink():
                try:
                    canonical_run = canonical_uuid(
                        directory.name, "simulation_run_id"
                    )
                except ValueError:
                    logger.warning("Ignoring non-run output directory %s", directory)
                    continue
                runs.append(
                    RunFolder(
                        simulation_run_id=canonical_run,
                        files=_describe_files(thread_root, directory),
                    )
                )

    staged = sum(len(upload.files) for upload in uploads)
    return ThreadInspection(
        thread_id=canonical_thread,
        exists=True,
        uploads=uploads,
        runs=tuple(runs),
        message=f"{staged} staged input file(s) and {len(runs)} simulation run(s).",
    )


def render_plot(
    settings: ServerSettings,
    *,
    kind: str,
    thread_id: str,
    simulation_run_id: str,
    filename: str | None = None,
) -> PlotResult:
    """Read a monitor data file from one run and write a PNG beside it."""
    if kind not in DEFAULT_MONITOR_FILENAMES:
        raise ToolError(f"Unknown monitor kind: {kind!r}")
    _, _, run_directory = _run_directory(settings, thread_id, simulation_run_id)
    source = _run_file(run_directory, filename or DEFAULT_MONITOR_FILENAMES[kind])

    if not source.is_file():
        raise ToolError(
            f"No {source.name} in simulation run {simulation_run_id}. Run the "
            "simulation with this monitor before asking for its plot."
        )

    try:
        data = read_monitor_file(source)
    except MonitorFileError as exc:
        raise ToolError(str(exc)) from exc
    if data.kind != kind:
        raise ToolError(
            f"{source.name} is a {data.kind} monitor file, not {kind}"
        )

    destination = source.with_suffix(".png")
    render_monitor_png(data, destination)
    return PlotResult(
        kind=data.kind,
        source=source.name,
        path=destination.name,
        size_bytes=destination.stat().st_size,
        title=data.title,
        x_label=data.x_label,
        y_label=data.y_label,
        message=f"Rendered {destination.name} from {source.name}.",
    )


# ---------------------------------------------------------------------------
# The four tools, and the health route
# ---------------------------------------------------------------------------


@mcp.tool
async def run_simulation(
    thread_id: str,
    simulation_run_id: str,
    module_results: dict[str, dict[str, Any]],
    execution_order: list[str],
) -> SimulationResult:
    """Run one VITESS pipeline and report what every module did.

    Args:
        thread_id: The conversation this simulation belongs to.
        simulation_run_id: Names this run's output directory.
        module_results: Validated parameters per module, each carrying a
            ``cli_parameters`` list.
        execution_order: The modules to run, in pipeline order.
    """
    return await asyncio.to_thread(
        run_pipeline,
        SETTINGS,
        thread_id=thread_id,
        simulation_run_id=simulation_run_id,
        module_results=module_results,
        execution_order=execution_order,
    )


@mcp.tool
async def inspect_thread_folders(thread_id: str) -> ThreadInspection:
    """List the files staged for a conversation and the runs it has produced."""
    return await asyncio.to_thread(inspect_thread, SETTINGS, thread_id=thread_id)


@mcp.tool
async def generate_monitor1d_plot(
    thread_id: str, simulation_run_id: str, filename: str | None = None
) -> PlotResult:
    """Render the 1D monitor data of one simulation run as a PNG."""
    return await asyncio.to_thread(
        render_plot,
        SETTINGS,
        kind="monitor1d",
        thread_id=thread_id,
        simulation_run_id=simulation_run_id,
        filename=filename,
    )


@mcp.tool
async def generate_monitor2d_plot(
    thread_id: str, simulation_run_id: str, filename: str | None = None
) -> PlotResult:
    """Render the 2D monitor data of one simulation run as a PNG."""
    return await asyncio.to_thread(
        render_plot,
        SETTINGS,
        kind="monitor2d",
        thread_id=thread_id,
        simulation_run_id=simulation_run_id,
        filename=filename,
    )


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    """Answer 200 only if VITESS is present and the project volume is writable.

    Compose gates the application on this route, so a mount that did not happen
    stops the stack here instead of surfacing as a failed simulation later.
    """
    report = check_health(SETTINGS)
    status_code = 200 if report.status == "healthy" else 503
    return JSONResponse(report.model_dump(), status_code=status_code)


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info(
        "VITESS MCP server on %s:%d (modules=%s, projects=%s)",
        SETTINGS.host,
        SETTINGS.port,
        SETTINGS.modules_root,
        SETTINGS.project_root,
    )
    mcp.run(transport="http", host=SETTINGS.host, port=SETTINGS.port)


if __name__ == "__main__":
    main()
