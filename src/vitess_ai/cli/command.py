"""Build VITESS process argument vectors without invoking a shell."""

from __future__ import annotations

import os
import shlex
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID


COMMON_ARGUMENTS = ("--Z1", "--U1.0e-25", "--G1", "--T0", "--B10000")


def canonical_uuid(value: str, field_name: str) -> str:
    """Return the value if it is a canonical UUID, else raise ``ValueError``.

    Public because the MCP server validates the same two identifiers before
    joining either into a path (03/CP3), and a second copy of "is this a
    UUID" is a second chance to disagree.
    """
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a UUID") from exc
    canonical = str(parsed)
    if value != canonical:
        raise ValueError(f"{field_name} must use canonical lowercase UUID form")
    return canonical


def resolve_executable(modules_path: Path, basename: str) -> Path:
    """Resolve a catalog basename inside the trusted modules root, or raise.

    Public because the MCP server's health route needs exactly this check
    (03/CP3): a second copy of "is this executable really inside $V" is how
    the first-generation agent ended up with two executable mappings that
    disagreed.
    """
    if (
        not basename
        or basename in {".", ".."}
        or Path(basename).name != basename
        or "/" in basename
        or "\\" in basename
        or "$" in basename
    ):
        raise ValueError(f"Invalid VITESS executable basename: {basename!r}")

    modules_root = modules_path.expanduser().resolve(strict=True)
    executable = (modules_root / basename).resolve(strict=True)
    try:
        executable.relative_to(modules_root)
    except ValueError as exc:
        raise ValueError(
            f"VITESS executable {executable} resolves outside {modules_root}"
        ) from exc
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError(f"VITESS executable is not an executable file: {executable}")
    return executable


def _validate_cli_arguments(
    module: str,
    arguments: Any,
    *,
    project_root: Path,
    run_directory: Path,
) -> list[str]:
    if not isinstance(arguments, list) or not arguments:
        raise ValueError(
            f"Module '{module}' has no CLI parameters; expected a non-empty list[str]"
        )
    if any(not isinstance(argument, str) or not argument for argument in arguments):
        raise ValueError(
            f"Module '{module}' CLI parameters must be non-empty string elements"
        )
    for argument in arguments:
        if "\x00" in argument:
            raise ValueError(f"Module '{module}' CLI parameter contains a null byte")
        if not argument.startswith("-") or argument in {"-", "--"}:
            raise ValueError(
                f"Module '{module}' CLI parameter is not a flag-value argument: "
                f"{argument!r}"
            )
        normalized = argument.replace("\\", "/")
        if "../" in normalized or normalized.endswith("/.."):
            raise ValueError(
                f"Module '{module}' CLI parameter contains parent traversal: {argument!r}"
            )
        value = normalized[3:] if normalized.startswith("--") else normalized[2:]
        if "/" in value:
            path = Path(value)
            allowed_root = project_root if path.is_absolute() else run_directory
            resolved = path.resolve() if path.is_absolute() else (run_directory / path).resolve()
            try:
                resolved.relative_to(allowed_root)
            except ValueError as exc:
                raise ValueError(
                    f"Module '{module}' CLI path escapes project_path: {value!r}"
                ) from exc
    return list(arguments)


def _failure(
    message: str,
    *,
    argument_vectors: list[list[str]],
    modules_included: list[str],
) -> dict[str, Any]:
    return {
        "success": False,
        "error": message,
        "message": message,
        "argument_vectors": argument_vectors,
        "modules_included": modules_included,
        "command_parts": len(argument_vectors),
    }


def render_display_command(argument_vectors: Sequence[Sequence[str]]) -> str:
    """Render vectors for humans only; the returned text must never be executed."""
    return " | \\\n".join(shlex.join(list(arguments)) for arguments in argument_vectors)


def generate_cli_command(
    module_results: Mapping[str, Mapping[str, Any]] | None,
    execution_order: Sequence[str] | None,
    *,
    thread_id: str,
    simulation_run_id: str,
    project_path: str | Path,
    modules_path: str | Path,
    module_executables: Mapping[str, str],
) -> dict[str, Any]:
    """Build one argument vector per requested VITESS module.

    ``cli_parameters`` must already be a validated ``list[str]``. Strings are
    deliberately rejected because they cannot be split without reintroducing shell
    parsing and quoting ambiguities.
    """
    canonical_thread_id = canonical_uuid(thread_id, "thread_id")
    canonical_run_id = canonical_uuid(simulation_run_id, "simulation_run_id")
    project_root = Path(project_path).expanduser().resolve()
    run_directory = (
        project_root / canonical_thread_id / "outputs" / canonical_run_id
    ).resolve()
    try:
        run_directory.relative_to(project_root)
    except ValueError as exc:
        raise ValueError("Resolved simulation directory escapes project_path") from exc

    if not module_results:
        return _failure(
            "No module results were provided",
            argument_vectors=[],
            modules_included=[],
        )
    if not execution_order or isinstance(execution_order, (str, bytes)):
        return _failure(
            "A non-empty execution_order is required",
            argument_vectors=[],
            modules_included=[],
        )

    argument_vectors: list[list[str]] = []
    modules_included: list[str] = []
    log_prefix = run_directory / f"log-{canonical_run_id}-"
    modules_root = Path(modules_path)

    for position, module in enumerate(execution_order, start=1):
        if module not in module_results:
            return _failure(
                f"Module '{module}' is missing from module_results",
                argument_vectors=argument_vectors,
                modules_included=modules_included,
            )
        if module not in module_executables:
            return _failure(
                f"Module '{module}' is missing from the executable mapping",
                argument_vectors=argument_vectors,
                modules_included=modules_included,
            )

        module_result = module_results[module]
        if not isinstance(module_result, Mapping):
            return _failure(
                f"Module '{module}' result must be a mapping",
                argument_vectors=argument_vectors,
                modules_included=modules_included,
            )
        try:
            cli_arguments = _validate_cli_arguments(
                module,
                module_result.get("cli_parameters"),
                project_root=project_root,
                run_directory=run_directory,
            )
            executable = resolve_executable(
                modules_root, module_executables[module]
            )
        except (FileNotFoundError, NotADirectoryError, PermissionError, ValueError) as exc:
            return _failure(
                str(exc),
                argument_vectors=argument_vectors,
                modules_included=modules_included,
            )

        argument_vectors.append(
            [
                str(executable),
                *COMMON_ARGUMENTS,
                f"--P{run_directory}",
                f"--N{position}",
                f"--L{log_prefix}{position:02d}",
                *cli_arguments,
            ]
        )
        modules_included.append(module)

    display_command = render_display_command(argument_vectors)
    return {
        "success": True,
        "argument_vectors": argument_vectors,
        "display_command": display_command,
        # Compatibility name for the UI. This is display-only and is never executed.
        "cli_command": display_command,
        "modules_included": modules_included,
        "command_parts": len(argument_vectors),
        "message": f"Generated argument vectors for {len(argument_vectors)} modules",
        "thread_id": canonical_thread_id,
        "simulation_run_id": canonical_run_id,
        "project_path": str(run_directory),
        "log_prefix": str(log_prefix),
    }
