"""
Tools for high-throughput agent.

Simplified version that delegates simulation execution to MCP supervisor tools.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from langchain.tools import tool

from vitess_ai.core.config import global_config
from vitess_ai.agents.simulator.tools.readin import readin_params_to_cli
from vitess_ai.agents.simulator.tools.guide import guide_params_to_cli
from vitess_ai.agents.simulator.tools.writeout import writeout_params_to_cli
from vitess_ai.agents.simulator.tools.monitor import monitor1d_params_to_cli, monitor2d_params_to_cli


def _resolve_thread_id(thread_id: str | None = None) -> str | None:
    """Resolve thread id from arg or environment."""
    return thread_id or os.environ.get("THREAD_ID") or os.environ.get("VITESS_THREAD_ID")


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


def _convert_simulation_to_module_results(
    simulation: dict[str, Any],
    execution_order: list[str],
) -> dict[str, Any]:
    """
    Convert a simulation config (JSON parameters) to module_results with cli_parameters.
    
    Args:
        simulation: Dict with module names as keys and JSON parameters as values.
        execution_order: List of module names in execution order.
    
    Returns:
        Dict with module_results containing cli_parameters for each module.
    """
    module_results = {}
    errors = []
    
    for module_name in execution_order:
        params = simulation.get(module_name)
        if not params:
            errors.append(f"Missing parameters for module: {module_name}")
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
    varied_parameters: list[dict[str, Any]],
    thread_id: str | None = None,
    filename: str = "simulation_matrix.json",
) -> dict[str, Any]:
    """
    Write the simulation matrix to a JSON file.

    Args:
        simulations: List of simulation configs with module parameters.
        varied_parameters: List of varied parameter specs.
        thread_id: Optional thread ID.
        filename: Output filename (default: simulation_matrix.json).

    Returns:
        Dictionary with success status and file path.
    """
    resolved_thread_id = _resolve_thread_id(thread_id)
    if not resolved_thread_id:
        return {"success": False, "message": "No thread_id available.", "file_path": None}

    output_dir = Path(global_config.VITESS_PROJECT_PATH) / resolved_thread_id / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = output_dir / filename

    matrix_data = {
        "metadata": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "thread_id": resolved_thread_id,
            "total_simulations": len(simulations),
            "varied_parameters": varied_parameters,
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
        execution_order: Module execution order. Defaults to ["readin", "guide", "writeout"].

    Returns:
        Dictionary with run_specs ready for run_simulation MCP tool.
    """
    resolved_thread_id = _resolve_thread_id(thread_id)
    if not resolved_thread_id:
        return {"success": False, "message": "No thread_id available."}

    if not execution_order:
        execution_order = ["readin", "guide", "writeout"]

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
        conversion = _convert_simulation_to_module_results(sim, execution_order)

        if conversion["success"]:
            run_specs.append({
                "run_name": sim_id,
                "module_results": conversion["module_results"],
                "execution_order": execution_order,
            })
        else:
            errors.extend([f"[{sim_id}] {e}" for e in conversion["errors"]])

    return {
        "success": len(run_specs) > 0,
        "thread_id": resolved_thread_id,
        "total_simulations": len(simulations),
        "converted_runs": len(run_specs),
        "run_specs": run_specs,
        "execution_order": execution_order,
        "errors": errors if errors else None,
        "message": f"Converted {len(run_specs)}/{len(simulations)} simulations to run specs.",
    }


# ============================================================================
# SIMULATION EXECUTION (DELEGATES TO MCP)
# ============================================================================

@tool
async def run_single_simulation(
    module_results: dict[str, Any],
    execution_order: list[str],
    thread_id: str | None = None,
    execute: bool = True,
) -> dict[str, Any]:
    """
    Run a single simulation using the MCP run_simulation tool.

    Args:
        module_results: Dict with module names as keys and {cli_parameters: "..."} as values.
        execution_order: List of module names in execution order.
        thread_id: Optional thread ID.
        execute: Whether to execute (True) or just generate CLI (False).

    Returns:
        Simulation execution result from MCP.
    """
    from vitess_ai.mcp import supervisor_tools

    resolved_thread_id = _resolve_thread_id(thread_id)

    result = await supervisor_tools.run_simulation.fn(
        module_results=module_results,
        execution_order=execution_order,
        execute=execute,
        thread_id=resolved_thread_id,
    )

    return result


@tool
async def run_batch_from_matrix(
    thread_id: str | None = None,
    filename: str = "simulation_matrix.json",
    execution_order: list[str] | None = None,
    execute: bool = True,
) -> dict[str, Any]:
    """
    Run all simulations from a matrix file sequentially.

    Loads the matrix, converts to CLI, and runs each simulation via MCP.

    Args:
        thread_id: Optional thread ID.
        filename: Simulation matrix filename.
        execution_order: Module execution order. Defaults to ["readin", "guide", "writeout"].
        execute: Whether to execute (True) or just generate CLIs (False).

    Returns:
        Dictionary with results for each simulation.
    """
    from vitess_ai.mcp import supervisor_tools

    resolved_thread_id = _resolve_thread_id(thread_id)
    if not resolved_thread_id:
        return {"success": False, "message": "No thread_id available."}

    default_exec_order = execution_order or ["readin", "guide", "writeout"]

    # Step 1: Convert matrix to run specs
    conversion = await convert_matrix_to_run_specs.ainvoke({
        "thread_id": resolved_thread_id,
        "filename": filename,
        "execution_order": default_exec_order,
    })

    if not conversion.get("success"):
        return conversion

    run_specs = conversion.get("run_specs", [])
    if not run_specs:
        return {"success": False, "thread_id": resolved_thread_id, "message": "No run specs generated."}

    # Step 2: Run each simulation sequentially via MCP
    results = []
    succeeded = 0
    failed = 0

    for run_spec in run_specs:
        run_name = run_spec.get("run_name", "unknown")
        module_results = run_spec.get("module_results", {})
        exec_order = run_spec.get("execution_order", default_exec_order)

        try:
            sim_result = await supervisor_tools.run_simulation.fn(
                module_results=module_results,
                execution_order=exec_order,
                execute=execute,
                thread_id=resolved_thread_id,
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
# TOOL EXPORTS
# ============================================================================

def get_high_throughput_tools() -> list[Any]:
    """Return all tools for the high-throughput agent."""
    return [
        list_thread_input_files,
        write_simulation_matrix,
        read_simulation_matrix,
        convert_matrix_to_run_specs,
        run_single_simulation,
        run_batch_from_matrix,
    ]


def get_sim_runner_tools() -> list[Any]:
    """Return tools for the simulation runner subagent."""
    return [
        run_single_simulation,
        run_batch_from_matrix,
    ]


def get_shared_high_throughput_tools() -> list[Any]:
    """Return tools shared by the main high-throughput orchestrator."""
    return [
        list_thread_input_files,
        write_simulation_matrix,
        read_simulation_matrix,
        convert_matrix_to_run_specs,
        run_batch_from_matrix,
    ]
