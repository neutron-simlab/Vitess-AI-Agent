"""Execute a VITESS pipeline from argument vectors without a shell."""

from __future__ import annotations

import subprocess
import tempfile
import time
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Sequence

__all__ = ["RESULT_FILENAME", "execute_pipeline", "postprocess_logs"]

#: What the concatenated VITESS logs are called, inside the run directory.
#: Named once here because the server reports files by name and would
#: otherwise carry its own copy of the string.
RESULT_FILENAME = "result.txt"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tail(stream: BinaryIO, limit: int) -> str:
    stream.flush()
    stream.seek(0, 2)
    size = stream.tell()
    stream.seek(max(0, size - limit))
    return stream.read().decode("utf-8", errors="replace")


def _stop_processes(
    processes: Sequence[subprocess.Popen[bytes]], grace_seconds: float
) -> None:
    survivors = [process for process in processes if process.poll() is None]
    for process in survivors:
        process.terminate()

    deadline = time.monotonic() + max(0.0, grace_seconds)
    for process in survivors:
        if process.poll() is not None:
            continue
        try:
            process.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            pass

    survivors = [process for process in processes if process.poll() is None]
    for process in survivors:
        process.kill()
    for process in survivors:
        process.wait()


def postprocess_logs(run_directory: str | Path, log_prefix: str | Path) -> Path:
    """Concatenate and remove only this simulation's scoped VITESS log files."""
    run_root = Path(run_directory).resolve()
    prefix = Path(log_prefix).resolve()
    if prefix.parent != run_root:
        raise ValueError("log_prefix must be directly beneath run_directory")

    log_files = sorted(
        path
        for path in run_root.glob(f"{prefix.name}??")
        if path.is_file() and path.resolve().parent == run_root
    )
    result_file = run_root / RESULT_FILENAME
    result_file.unlink(missing_ok=True)
    with result_file.open("wb") as result_stream:
        for log_file in log_files:
            result_stream.write(log_file.read_bytes())
    for log_file in log_files:
        log_file.unlink()
    return result_file


def execute_pipeline(
    argument_vectors: Sequence[Sequence[str]],
    module_names: Sequence[str],
    *,
    run_directory: str | Path,
    log_prefix: str | Path,
    timeout_seconds: float = 3600,
    termination_grace_seconds: float = 0.5,
    tail_bytes: int = 8192,
) -> dict[str, Any]:
    """Pipe processes together and succeed only when every process exits zero."""
    if not argument_vectors:
        raise ValueError("argument_vectors must not be empty")
    if len(argument_vectors) != len(module_names):
        raise ValueError("module_names must align one-to-one with argument_vectors")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    run_root = Path(run_directory).resolve()
    run_root.mkdir(parents=True, exist_ok=True)
    processes: list[subprocess.Popen[bytes]] = []
    started_at: list[str] = []
    timed_out = False

    with ExitStack() as stack:
        final_stdout = stack.enter_context(tempfile.TemporaryFile())
        stderr_streams = [
            stack.enter_context(tempfile.TemporaryFile()) for _ in argument_vectors
        ]
        previous_stdout: BinaryIO | None = None
        try:
            for index, arguments in enumerate(argument_vectors):
                started_at.append(_utc_now())
                process = subprocess.Popen(
                    list(arguments),
                    cwd=run_root,
                    stdin=previous_stdout,
                    stdout=(
                        subprocess.PIPE
                        if index < len(argument_vectors) - 1
                        else final_stdout
                    ),
                    stderr=stderr_streams[index],
                    shell=False,
                )
                processes.append(process)
                if previous_stdout is not None:
                    previous_stdout.close()
                previous_stdout = process.stdout
        except BaseException:
            if previous_stdout is not None:
                previous_stdout.close()
            _stop_processes(processes, termination_grace_seconds)
            raise
        finally:
            if previous_stdout is not None:
                previous_stdout.close()

        deadline = time.monotonic() + timeout_seconds
        try:
            for process in processes:
                process.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            timed_out = True
            _stop_processes(processes, termination_grace_seconds)

        ended_at = _utc_now()
        stdout_tail = _tail(final_stdout, tail_bytes)
        module_evidence = []
        for index, (module_name, arguments, process, stderr_stream) in enumerate(
            zip(module_names, argument_vectors, processes, stderr_streams, strict=True)
        ):
            module_evidence.append(
                {
                    "name": module_name,
                    "executable": str(arguments[0]),
                    "pid": process.pid,
                    "exit_code": process.returncode,
                    "started_at": started_at[index],
                    "ended_at": ended_at,
                    "stdout_tail": (
                        stdout_tail if index == len(argument_vectors) - 1 else ""
                    ),
                    "stderr_tail": _tail(stderr_stream, tail_bytes),
                }
            )

    result_file = postprocess_logs(run_root, log_prefix)
    success = not timed_out and all(
        evidence["exit_code"] == 0 for evidence in module_evidence
    )
    return {
        "success": success,
        "timed_out": timed_out,
        "modules": module_evidence,
        "result_file": str(result_file),
        "message": (
            "Simulation pipeline completed successfully"
            if success
            else "Simulation pipeline timed out"
            if timed_out
            else "One or more VITESS modules failed"
        ),
    }
