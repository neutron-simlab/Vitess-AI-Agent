"""
Tools for advanced mode agent.

Simplified version that delegates simulation execution to MCP supervisor tools.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Optional

from langchain.tools import tool

from vitess_ai.core.config import global_config
from vitess_ai.agents.simulator.tools.readin import readin_params_to_cli
from vitess_ai.agents.simulator.tools.guide import guide_params_to_cli
from vitess_ai.agents.simulator.tools.writeout import writeout_params_to_cli
from vitess_ai.agents.simulator.tools.monitor import monitor1d_params_to_cli, monitor2d_params_to_cli


def _resolve_thread_id(thread_id: str | None = None) -> str | None:
    """Resolve thread id from arg or environment."""
    return thread_id or os.environ.get("THREAD_ID")


# ============================================================================
# MODULE CLI CONVERTERS
# ============================================================================

MODULE_CLI_CONVERTERS = {
    "readin": readin_params_to_cli,
    "guide": guide_params_to_cli,
    "writeout": writeout_params_to_cli,
    "monitor1d": monitor1d_params_to_cli,
    "monitor2d": monitor2d_params_to_cli,
}

# Canonical order for pipeline; used to infer execution_order from matrix when not provided.
# Monitors are last so they receive piped input from writeout.
CANONICAL_EXECUTION_ORDER = ["readin", "guide", "writeout", "monitor1d", "monitor2d"]


def _execution_order_for_simulation(
    simulation: dict[str, Any],
    execution_order: list[str] | None,
) -> list[str]:
    """
    Resolve execution_order for a single simulation.
    When execution_order is None, infer from simulation keys using canonical order.
    When provided, use only modules that are present in this simulation.
    """
    if execution_order is not None:
        return [m for m in execution_order if simulation.get(m)]
    return [m for m in CANONICAL_EXECUTION_ORDER if simulation.get(m)]


def _convert_simulation_to_module_results(
    simulation: dict[str, Any],
    execution_order: list[str],
) -> dict[str, Any]:
    """
    Convert a simulation config (JSON parameters) to module_results with cli_parameters.

    Output filenames (e.g. writeout sOutFileName) can stay as bare names; P is set to
    thread_id/outputs/run_id in the script so binaries resolve them under the run folder.
    """
    module_results = {}
    errors = []

    for module_name in execution_order:
        params = simulation.get(module_name)
        if not params:
            errors.append(f"Missing parameters for module: {module_name}")
            continue

        if isinstance(params, dict) and (
            params.get("validation_status") is False or "errors" in params
        ):
            errors.append(
                f"Module {module_name}: invalid or failed validation result, do not use as parameters"
            )
            continue

        converter = MODULE_CLI_CONVERTERS.get(module_name)
        if not converter:
            errors.append(f"No CLI converter for module: {module_name}")
            continue

        try:
            cli_string = converter(params)
            module_results[module_name] = {
                "parameters": params,
                "cli_parameters": cli_string,
                "validation_status": True,
            }
        except Exception as exc:
            errors.append(f"Failed to convert {module_name} params to CLI: {exc}")

    return {
        "module_results": module_results,
        "errors": errors,
        "success": len(errors) == 0,
    }


# ============================================================================
# MODULE SUBAGENT RESULT (structured contract for orchestrator)
# ============================================================================

def _is_error_shaped_dict(value: Any) -> bool:
    """True if value looks like a validation error payload (dict key checks only, no regex)."""
    if not isinstance(value, dict):
        return False
    return "validation_status" in value or "errors" in value


@tool
def submit_module_result(
    module_name: str,
    validation_passed: bool,
    parameters: dict[str, Any] | list[dict[str, Any]] | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    """
    Report the module result to the orchestrator. Call this after running the module's
    validate_* tool. Return value is always a dictionary the orchestrator can read by key.

    Args:
        module_name: Module name (e.g. readin, guide, writeout).
        validation_passed: True if validation succeeded and parameters are ready for CLI.
        parameters: Validated parameter dict or list of parameter dicts
            (required when validation_passed is True).
        error_message: Error description (required when validation_passed is False).

    Returns:
        Dict with keys: accepted, module, validation_passed, and either parameters or error.
    """
    if validation_passed:
        if not parameters:
            return {
                "accepted": False,
                "module": module_name,
                "validation_passed": False,
                "error": (
                    "parameters must be a non-empty dict or non-empty list of dicts "
                    "when validation_passed is True"
                ),
            }

        if isinstance(parameters, dict):
            return {
                "accepted": True,
                "module": module_name,
                "validation_passed": True,
                "parameters": parameters,
            }

        if isinstance(parameters, list):
            if any(not isinstance(param_set, dict) or not param_set for param_set in parameters):
                return {
                    "accepted": False,
                    "module": module_name,
                    "validation_passed": False,
                    "error": "all items in parameters must be non-empty dicts",
                }
            return {
                "accepted": True,
                "module": module_name,
                "validation_passed": True,
                "parameters": parameters,
            }

        return {
            "accepted": False,
            "module": module_name,
            "validation_passed": False,
            "error": "parameters must be a dict or list of dicts when validation_passed is True",
        }

    if not error_message:
        return {
            "accepted": False,
            "module": module_name,
            "validation_passed": False,
            "error": "error_message is required when validation_passed is False",
        }
    return {
        "accepted": True,
        "module": module_name,
        "validation_passed": False,
        "error": error_message,
    }


# ============================================================================
# FILE LISTING TOOLS
# ============================================================================

@tool
async def list_thread_input_files(thread_id: str | None = None) -> dict[str, Any]:
    """
    List uploaded input files available for a thread.

    Returns a flat list of all uploaded files with module, filename, and path.
    """
    from vitess_ai.mcp import supervisor_tools

    resolved_thread_id = _resolve_thread_id(thread_id)
    inspection = await supervisor_tools.inspect_thread_folders.fn(thread_id=resolved_thread_id)
    if not inspection.get("success"):
        return inspection

    structure = inspection.get("folder_structure", {})
    uploads = (structure.get("uploads") or {}).get("modules", {})

    flattened: list[dict[str, Any]] = []
    for module_name, module_payload in uploads.items():
        module_path = module_payload.get("path")
        for item in module_payload.get("files", []):
            filename = item.get("filename")
            flattened.append(
                {
                    "module": module_name,
                    "filename": filename,
                    "file_size": item.get("file_size"),
                    "modified_at": item.get("modified_at"),
                    "path": str(Path(module_path) / filename) if module_path and filename else None,
                }
            )

    return {
        "success": True,
        "thread_id": resolved_thread_id,
        "upload_modules": sorted(list(uploads.keys())),
        "total_files": len(flattened),
        "files": flattened,
    }


# ============================================================================
# SIMULATION MATRIX I/O
# ============================================================================

@tool
async def write_simulation_matrix(
    simulations: list[dict[str, Any]],
    thread_id: str | None = None,
    filename: str = "simulation_matrix.json",
) -> dict[str, Any]:
    """
    Write the simulation matrix to a JSON file.

    Args:
        simulations: List of simulation configs with module parameters.
        thread_id: Optional thread ID.
        filename: Output filename (default: simulation_matrix.json).

    Returns:
        Dictionary with success status and file path.
    """
    resolved_thread_id = _resolve_thread_id(thread_id)
    if not resolved_thread_id:
        return {"success": False, "message": "No thread_id available.", "file_path": None}

    invalid = []
    missing_required = []
    for i, sim in enumerate(simulations):
        sim_id = sim.get("id", f"sim_{i + 1:03d}")
        for module_name in CANONICAL_EXECUTION_ORDER:
            if sim.get(module_name) is None:
                missing_required.append(f"{sim_id}/{module_name}")
        for module_name, value in sim.items():
            if module_name == "id":
                continue
            if _is_error_shaped_dict(value):
                invalid.append(f"{sim_id}/{module_name}")
    if invalid:
        return {
            "success": False,
            "thread_id": resolved_thread_id,
            "file_path": None,
            "message": f"Simulation matrix contains invalid or error-shaped module data; do not use validation errors as parameters. Invalid entries: {', '.join(invalid)}",
        }
    if missing_required:
        return {
            "success": False,
            "thread_id": resolved_thread_id,
            "file_path": None,
            "message": (
                "Simulation matrix must include all five modules "
                f"(readin, guide, writeout, monitor1d, monitor2d). "
                f"Missing entries: {', '.join(missing_required)}"
            ),
        }

    output_dir = Path(global_config.VITESS_PROJECT_PATH) / resolved_thread_id / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = output_dir / filename

    matrix_data = {
        "metadata": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "thread_id": resolved_thread_id,
            "total_simulations": len(simulations),
        },
        "simulations": simulations,
    }

    try:
        file_path.write_text(json.dumps(matrix_data, indent=2), encoding="utf-8")
        return {
            "success": True,
            "thread_id": resolved_thread_id,
            "file_path": str(file_path),
            "total_simulations": len(simulations),
            "message": f"Simulation matrix saved to {file_path}",
        }
    except Exception as exc:
        return {
            "success": False,
            "thread_id": resolved_thread_id,
            "file_path": str(file_path),
            "message": f"Failed to write simulation matrix: {exc}",
        }


@tool
async def read_simulation_matrix(
    thread_id: str | None = None,
    filename: str = "simulation_matrix.json",
) -> dict[str, Any]:
    """
    Read a simulation matrix from file.

    Args:
        thread_id: Optional thread ID.
        filename: Input filename (default: simulation_matrix.json).

    Returns:
        Dictionary with the simulation matrix data.
    """
    resolved_thread_id = _resolve_thread_id(thread_id)
    if not resolved_thread_id:
        return {"success": False, "message": "No thread_id available.", "file_path": None}

    file_path = Path(global_config.VITESS_PROJECT_PATH) / resolved_thread_id / "outputs" / filename
    if not file_path.exists():
        return {
            "success": False,
            "thread_id": resolved_thread_id,
            "file_path": str(file_path),
            "message": f"Simulation matrix file not found: {file_path}",
        }

    try:
        matrix_data = json.loads(file_path.read_text(encoding="utf-8"))
        return {
            "success": True,
            "thread_id": resolved_thread_id,
            "file_path": str(file_path),
            "matrix": matrix_data,
            "total_simulations": len(matrix_data.get("simulations", [])),
            "message": f"Loaded simulation matrix from {file_path}",
        }
    except Exception as exc:
        return {
            "success": False,
            "thread_id": resolved_thread_id,
            "file_path": str(file_path),
            "message": f"Failed to read simulation matrix: {exc}",
        }


# ============================================================================
# CONVERSION: JSON PARAMS → CLI STRINGS
# ============================================================================

@tool
async def convert_matrix_to_run_specs(
    thread_id: str | None = None,
    filename: str = "simulation_matrix.json",
    execution_order: list[str] | None = None,
) -> dict[str, Any]:
    """
    Convert a simulation matrix (JSON parameters) to run specs with CLI strings.

    Args:
        thread_id: Optional thread ID.
        filename: Simulation matrix filename.
        execution_order: Module execution order. If None, inferred from each simulation's
            keys using canonical order (readin, guide, writeout, monitor1d, monitor2d),
            so monitor modules are included when present in the matrix.

    Returns:
        Dictionary with run_specs ready for run_simulation MCP tool.
    """
    resolved_thread_id = _resolve_thread_id(thread_id)
    if not resolved_thread_id:
        return {"success": False, "message": "No thread_id available."}

    file_path = Path(global_config.VITESS_PROJECT_PATH) / resolved_thread_id / "outputs" / filename
    if not file_path.exists():
        return {
            "success": False,
            "thread_id": resolved_thread_id,
            "file_path": str(file_path),
            "message": f"Simulation matrix file not found: {file_path}",
        }

    try:
        matrix_data = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"success": False, "thread_id": resolved_thread_id, "message": f"Failed to read: {exc}"}

    simulations = matrix_data.get("simulations", [])
    if not simulations:
        return {"success": False, "thread_id": resolved_thread_id, "message": "No simulations in matrix."}

    run_specs = []
    errors = []

    for sim in simulations:
        sim_id = sim.get("id", f"sim_{len(run_specs) + 1:03d}")
        exec_order = _execution_order_for_simulation(sim, execution_order)
        if not exec_order:
            errors.append(f"[{sim_id}] No known modules found in simulation keys: {list(sim.keys())}")
            continue
        conversion = _convert_simulation_to_module_results(sim, exec_order)

        if conversion["success"]:
            run_specs.append({
                "run_name": sim_id,
                "module_results": conversion["module_results"],
                "execution_order": exec_order,
            })
        else:
            errors.extend([f"[{sim_id}] {e}" for e in conversion["errors"]])

    return {
        "success": len(run_specs) > 0,
        "thread_id": resolved_thread_id,
        "total_simulations": len(simulations),
        "converted_runs": len(run_specs),
        "run_specs": run_specs,
        "execution_order": run_specs[0]["execution_order"] if run_specs else [],
        "errors": errors if errors else None,
        "message": f"Converted {len(run_specs)}/{len(simulations)} simulations to run specs.",
    }


# ============================================================================
# SIMULATION EXECUTION (DELEGATES TO MCP)
# ============================================================================

@tool
async def run_batch_from_matrix(
    thread_id: str | None = None,
    filename: str = "simulation_matrix.json",
    execution_order: list[str] | None = None,
    execute: bool = True,
    run_specs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Run 1 to N simulations sequentially via MCP.

    Accepts either in-memory run_specs or a matrix file. When run_specs is
    provided and non-empty, it is used directly (filename is ignored).
    Otherwise the matrix is loaded from filename and converted to run_specs.

    Args:
        thread_id: Optional thread ID. Required when executing.
        filename: Simulation matrix filename (used only when run_specs is not provided).
        execution_order: Module execution order. If None, inferred from each simulation
            in the matrix (can include monitor1d, monitor2d when present).
            Ignored when run_specs is provided.
        execute: Whether to execute (True) or just generate CLIs (False).
        run_specs: Optional list of run specs, each with run_name, module_results,
            execution_order. When provided and non-empty, use this instead of loading
            from filename. Use for single or multiple in-memory runs (e.g. from
            convert_matrix_to_run_specs).

    Returns:
        Dictionary with results for each simulation (total_runs, succeeded, failed, results).
    """
    from vitess_ai.mcp import supervisor_tools

    resolved_thread_id = _resolve_thread_id(thread_id)
    if not resolved_thread_id:
        return {"success": False, "message": "No thread_id available."}

    # Resolve run_specs: either use provided list or load from matrix file
    if run_specs:
        run_specs = list(run_specs)
    if not run_specs:
        # Load matrix and convert to run specs
        conversion = await convert_matrix_to_run_specs.ainvoke({
            "thread_id": resolved_thread_id,
            "filename": filename,
            "execution_order": execution_order,
        })
        if not conversion.get("success"):
            return conversion
        run_specs = conversion.get("run_specs", [])
    if not run_specs:
        return {
            "success": False,
            "thread_id": resolved_thread_id,
            "message": "No run specs to execute. Provide run_specs or ensure matrix file exists at filename.",
        }

    # Run each simulation sequentially via MCP
    results = []
    succeeded = 0
    failed = 0

    for run_spec in run_specs:
        run_name = run_spec.get("run_name", "unknown")
        module_results = run_spec.get("module_results", {})
        exec_order = run_spec.get("execution_order", CANONICAL_EXECUTION_ORDER)

        try:
            sim_result = await supervisor_tools.run_simulation.fn(
                module_results=module_results,
                execution_order=exec_order,
                execute=execute,
                thread_id=resolved_thread_id,
                run_id=run_name,
            )

            run_result = {
                "run_name": run_name,
                "success": sim_result.get("success", False),
                "executed": sim_result.get("executed", False),
                "message": sim_result.get("message", ""),
                "cli_command": sim_result.get("cli_command", ""),
            }

            if sim_result.get("success"):
                succeeded += 1
            else:
                failed += 1
                run_result["error"] = sim_result.get("error")

            results.append(run_result)

        except Exception as exc:
            failed += 1
            results.append({
                "run_name": run_name,
                "success": False,
                "executed": False,
                "message": f"Exception: {exc}",
                "error": str(exc),
            })

    return {
        "success": failed == 0,
        "thread_id": resolved_thread_id,
        "total_runs": len(run_specs),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
        "message": f"Batch complete: {succeeded} succeeded, {failed} failed.",
    }


# ============================================================================
# PLOT GENERATION
# ============================================================================

def _get_outputs_dir(thread_id: str | None, run_id: str | None) -> dict[str, Any]:
    """Resolve thread_id and run_id to outputs directory path. Returns error dict or dict with 'outputs_dir'."""
    resolved_thread_id = _resolve_thread_id(thread_id)
    if not resolved_thread_id:
        return {
            "success": False,
            "error": "No thread_id available.",
            "plot_data": {},
            "message": "No thread_id provided and not available in environment.",
        }
    outputs_dir = Path(global_config.VITESS_PROJECT_PATH) / resolved_thread_id / "outputs"
    if run_id:
        outputs_dir = outputs_dir / run_id
    if not outputs_dir.exists():
        return {
            "success": False,
            "error": f"Output directory not found: {outputs_dir}",
            "plot_data": {},
            "message": f"Directory {outputs_dir} does not exist.",
        }
    return {"success": True, "outputs_dir": outputs_dir}


@tool(response_format="content_and_artifact")
async def generate_plot_1d(
    thread_id: str | None = None,
    run_id: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Generate an interactive Monitor1D plot from simulation output.

    Looks for monitor1D.dat in the run output directory and returns plot_data
    suitable for UI rendering (same shape as simulator plots).

    The plot data is returned as an artifact (not visible to the LLM) so that
    large Plotly JSON payloads do not consume the context window.

    Args:
        thread_id: Optional thread ID. If not provided, uses THREAD_ID from environment.
        run_id: Optional run ID (e.g. sim_001). If set, looks in outputs/run_id/;
                if None, looks in thread outputs/ (flat, single-run case).

    Returns:
        Tuple of (content_for_llm, artifact_dict).
        artifact_dict has success, plot_data (monitor1d with plot_json, title, etc.).
    """
    out = _get_outputs_dir(thread_id, run_id)
    if not out.get("success"):
        return (out.get("message", "Failed to resolve output directory."), out)

    outputs_dir: Path = out["outputs_dir"]
    try:
        from vitess_ai.plots.vitess_plot import read_mfile_plotly
    except ImportError as e:
        return (
            f"Could not load plotting library: {e}",
            {"success": False, "error": str(e), "plot_data": {}},
        )

    monitor1d_file = outputs_dir / "monitor1D.dat"
    if not monitor1d_file.exists():
        return (
            "monitor1D.dat not found in output directory.",
            {"success": True, "plot_data": {}},
        )

    result = read_mfile_plotly(str(monitor1d_file))
    if not result.get("success"):
        msg = result.get("error", "Failed to generate Monitor1D plot.")
        return (msg, {"success": False, "error": msg, "plot_data": {}})

    plot_data = {
        "monitor1d": {
            "plot_json": result["plot_json"],
            "title": result.get("title", "Monitor1D Results"),
            "xaxis": result.get("xaxis", "x"),
            "yaxis": result.get("yaxis", "Intensity [n/s]"),
            "plot_type": "monitor1d",
        }
    }
    return (
        "The plot has been generated and is displayed in the UI. No further action needed.",
        {"success": True, "plot_data": plot_data},
    )


@tool(response_format="content_and_artifact")
async def generate_plot_2d(
    thread_id: str | None = None,
    run_id: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Generate an interactive Monitor2D plot from simulation output.

    Looks for monitor2D.dat in the run output directory and returns plot_data
    suitable for UI rendering (same shape as simulator plots).

    The plot data is returned as an artifact (not visible to the LLM) so that
    large Plotly JSON payloads do not consume the context window.

    Args:
        thread_id: Optional thread ID. If not provided, uses THREAD_ID from environment.
        run_id: Optional run ID (e.g. sim_001). If set, looks in outputs/run_id/;
                if None, looks in thread outputs/ (flat, single-run case).

    Returns:
        Tuple of (content_for_llm, artifact_dict).
        artifact_dict has success, plot_data (monitor2d with plot_json, title, etc.).
    """
    out = _get_outputs_dir(thread_id, run_id)
    if not out.get("success"):
        return (out.get("message", "Failed to resolve output directory."), out)

    outputs_dir: Path = out["outputs_dir"]
    try:
        from vitess_ai.plots.vitess_plot import read_mfile_plotly
    except ImportError as e:
        return (
            f"Could not load plotting library: {e}",
            {"success": False, "error": str(e), "plot_data": {}},
        )

    monitor2d_file = outputs_dir / "monitor2D.dat"
    if not monitor2d_file.exists():
        return (
            "monitor2D.dat not found in output directory.",
            {"success": True, "plot_data": {}},
        )

    result = read_mfile_plotly(str(monitor2d_file))
    if not result.get("success"):
        msg = result.get("error", "Failed to generate Monitor2D plot.")
        return (msg, {"success": False, "error": msg, "plot_data": {}})

    plot_data = {
        "monitor2d": {
            "plot_json": result["plot_json"],
            "title": result.get("title", "Monitor2D Results"),
            "xaxis": result.get("xaxis", "x"),
            "yaxis": result.get("yaxis", "y"),
            "plot_type": "monitor2d",
        }
    }
    return (
        "The plot has been generated and is displayed in the UI. No further action needed.",
        {"success": True, "plot_data": plot_data},
    )


# ============================================================================
# TOOL EXPORTS
# ============================================================================

def get_sim_runner_tools() -> list[Any]:
    """Return tools for the simulation runner subagent.

    Plot tools (generate_plot_1d, generate_plot_2d) are intentionally excluded
    so that only the main deep agent runs them. That way the ToolMessage
    (including the artifact with plot_data) is emitted by the main agent and
    streams to the UI correctly.
    """
    return [
        run_batch_from_matrix,
    ]


def get_shared_advanced_mode_tools() -> list[Any]:
    """Return tools shared by the main advanced mode orchestrator."""
    return [
        list_thread_input_files,
        write_simulation_matrix,
        read_simulation_matrix,
        convert_matrix_to_run_specs,
        run_batch_from_matrix,
        generate_plot_1d,
        generate_plot_2d,
    ]
