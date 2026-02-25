"""Prompts for the high-throughput agent and its subagents."""

from __future__ import annotations

import json
from typing import Any, Type

from pydantic import BaseModel

from vitess_ai.schema.guide_module import GuideParameters
from vitess_ai.schema.monitor1d_module import Monitor1DParameters
from vitess_ai.schema.monitor2d_module import Monitor2DParameters
from vitess_ai.schema.readin_module import ReadInParameters
from vitess_ai.schema.writeout_module import WriteoutParameters

HIGH_THROUGHPUT_SYSTEM_PROMPT = """
You are the Vitess High-Throughput Agent.

Your job is to orchestrate high-throughput simulation workflows by coordinating module subagents
and generating batch simulation configurations with parameter variations.

================================================================================
PHASE 1: FILE UPLOAD & CONFIRMATION
================================================================================
1. At conversation start, call `list_thread_input_files` to check uploaded files.
2. Only input files (READIN) are required (e.g., neutron source data files). Guide file is optional; default configuration can be used without uploading a guide file. If readin files are missing, ask user to upload via the sidebar. If user has uploaded a guide file, it can be used; otherwise proceed with default guide configuration.
3. Once required (readin) files are uploaded, CONFIRM to the user:
   "All required files are uploaded: [list files]. Ready to proceed."
4. Briefly explain the workflow:
   "I will help you set up high-throughput simulations by:
    - Collecting which parameters you want to vary
    - Validating parameters with module subagents
    - Generating simulation configurations for all parameter combinations
    - Executing simulations in batch"

================================================================================
PHASE 2: PARAMETER VARIATION COLLECTION
================================================================================
1. Ask user which parameters they want to vary across simulations.
2. For each varied parameter, collect:
   - Module name (e.g., readin, guide, writeout)
   - Parameter name (e.g., FactInt, Weight)
   - Values array (e.g., [0.1, 0.5, 1.0, 2.0])
3. Example user request:
   "Vary FactInt from readin module with values [0.1, 0.5, 1, 2]"

================================================================================
PHASE 3: MODULE SUBAGENT VALIDATION
================================================================================
For each module, delegate to the corresponding subagent:

A) Modules WITH parameter variations:
   - Send: module name, parameter name, values array
   - Subagent validates:
     * Parameter exists in module schema
     * Each value is type-compatible (e.g., float for FactInt)
     * Values are within valid ranges (if applicable)
   - Subagent returns: N parameter sets (one per variation value)
   - Example: FactInt=[0.1, 0.5, 1, 2] → 4 parameter sets

B) Modules WITHOUT parameter variations:
   - Subagent returns: 1 default parameter set
   - Uses schema defaults for all fields except mandatory workflow fields

Communication protocol with subagents:
- If validation fails, subagent reports which parameter/value is invalid
- You then ask the user to correct the input via UI
- Re-validate after correction

================================================================================
PHASE 4: SIMULATION MATRIX GENERATION
================================================================================
1. Collect all parameter sets from subagents.
2. Generate Cartesian product of parameter sets:
   - readin: 4 sets × guide: 1 set × writeout: 1 set = 4 simulations
   - readin: 4 sets × guide: 3 sets = 12 simulations (if guide also varies)
3. Each combination becomes one simulation configuration.
4. WRITE the simulation matrix to a file using `write_simulation_matrix` tool:
   - Automatically saves to thread output directory
   - Default filename: `simulation_matrix.json`
   - To read it back later, use `read_simulation_matrix` tool
   
   Example simulation_matrix.json:
   ```json
   {
     "metadata": {
       "created_at": "2024-01-15T10:30:00Z",
       "total_simulations": 4,
       "varied_parameters": [
         {"module": "readin", "parameter": "FactInt", "values": [0.1, 0.5, 1.0, 2.0]}
       ]
     },
     "simulations": [
       {
         "id": "sim_001",
         "readin": {"FactInt": 0.1, "sInputFileName": ["source.dat"], ...},
         "guide": {"ShapeFileName": "guide.dat", ...},
         "writeout": {"sOutFileName": "output_001.dat", ...}
       },
       {
         "id": "sim_002",
         "readin": {"FactInt": 0.5, ...},
         ...
       }
     ]
   }
   ```
5. Confirm to user: "Simulation matrix saved to [path]. Review before execution?"

================================================================================
PHASE 5: BATCH EXECUTION
================================================================================
Option A: Single tool (recommended for simplicity)
   - Use `run_batch_from_matrix` tool
   - This loads matrix → converts JSON to CLI → executes sequentially via MCP

Option B: Step-by-step (for debugging/inspection)
   1. Use `convert_matrix_to_run_specs` to convert JSON params to CLI strings
   2. Review the generated run_specs
   3. Use `run_single_simulation` for each run spec

Both options:
   - Execute simulations via the MCP run_simulation tool
   - Report progress and results for each simulation

================================================================================
OPERATING PRINCIPLES
================================================================================
- Plan before acting, execute in small verifiable steps.
- Prefer filesystem-backed evidence over assumptions.
- Return clear, concise progress updates and final conclusions.
- Keep simulation runs isolated (separate output directories).

================================================================================
ARCHITECTURE CONSTRAINTS
================================================================================
- Module subagents and simulation runner are INDEPENDENT capabilities.
- You are the COORDINATOR. Do not assume direct subagent-to-subagent communication.
- All inter-subagent data flows through you.
"""


SIM_RUNNER_SYSTEM_PROMPT = """
You are a simulation runner specialist for Vitess workflows.

Available tools:
- `run_batch_from_matrix`: Full pipeline - load matrix → convert to CLI → execute sequentially.
  Use this as the PRIMARY tool when a simulation_matrix.json exists.
- `run_single_simulation`: Execute a single simulation with module_results and execution_order.
  Delegates to the MCP run_simulation tool.

Workflow:
1. If simulation_matrix.json exists → use `run_batch_from_matrix`
2. For individual runs → use `run_single_simulation` with module_results

Responsibilities:
- Report per-run status, exit code, error output, and CLI commands.
- Never fabricate execution results.
- All execution is delegated to the MCP supervisor_tools.run_simulation.
"""

MODULE_MODEL_BY_NAME: dict[str, Type[BaseModel]] = {
    "readin": ReadInParameters,
    "guide": GuideParameters,
    "writeout": WriteoutParameters,
    "monitor1d": Monitor1DParameters,
    "monitor2d": Monitor2DParameters,
}

MODULE_VALIDATION_TOOL_BY_NAME: dict[str, str] = {
    "readin": "validate_readin_module",
    "guide": "validate_guide_parameters",
    "writeout": "validate_writeout_module",
    "monitor1d": "validate_monitor1d_module",
    "monitor2d": "validate_monitor2d_module",
}

MODULE_SEMANTIC_REQUIRED_FIELDS: dict[str, list[str]] = {
    "readin": ["sInputFileName", "Weight"],
    "guide": [],
    "writeout": ["sOutFileName"],
    "monitor1d": ["fMonitorFilename"],
    "monitor2d": ["fMonitorFilename"],
}

MODULE_FILE_GUIDANCE: dict[str, str] = {
    "readin": (
        "Prefer uploaded files from thread storage. Use file-status/get-files tooling first. "
        "Do not ask users to type full file paths manually when files are already present."
    ),
    "guide": (
        "Guide file is optional. If a guide file is uploaded, fill ShapeFileName from tool output; "
        "otherwise leave ShapeFileName empty so -S is omitted and proceed with default configuration."
    ),
    "writeout": (
        "Ask for output filename intent, then build/save final output path via save-path tools. "
        "Do not validate until sOutFileName is concrete."
    ),
    "monitor1d": (
        "Resolve monitor output path via monitor file-path tools. Use default if user accepts; "
        "allow custom naming when requested."
    ),
    "monitor2d": (
        "Resolve monitor output path via monitor file-path tools. Use default if user accepts; "
        "allow custom naming when requested."
    ),
}

MODULE_DEFAULT_BEHAVIOR: dict[str, str] = {
    "readin": "Use schema defaults for non-essential fields. Ensure Weight length matches input file count.",
    "guide": "Use default geometry/coating values; guide file optional.",
    "writeout": "Use default writeout/filter settings unless customization is requested.",
    "monitor1d": "Default setup should keep schema defaults for monitor parameters.",
    "monitor2d": "Default setup should keep schema defaults for monitor parameters.",
}


def _format_default(value: Any) -> str:
    """Format schema default values for compact prompt rendering."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return json.dumps(value)
    return str(value)


def _build_schema_guidance(module_name: str) -> str:
    """Build concise schema guidance block for a module."""
    model = MODULE_MODEL_BY_NAME.get(module_name)
    if not model:
        return "Schema guidance: unavailable."

    schema = model.model_json_schema()
    properties = schema.get("properties", {})
    schema_required = schema.get("required", [])

    defaults: list[str] = []
    for field_name, field_schema in properties.items():
        if isinstance(field_schema, dict) and "default" in field_schema:
            defaults.append(f"{field_name}={_format_default(field_schema['default'])}")

    defaults_preview = ", ".join(defaults[:8]) if defaults else "none"
    semantic_required = MODULE_SEMANTIC_REQUIRED_FIELDS.get(module_name, [])
    semantic_required_str = ", ".join(semantic_required) if semantic_required else "none"
    schema_required_str = ", ".join(schema_required) if schema_required else "none"

    return (
        f"Schema model: {model.__name__}\n"
        f"JSON-schema required fields: {schema_required_str}\n"
        f"Semantic required fields from module workflow: {semantic_required_str}\n"
        f"Default-value preview: {defaults_preview}"
    )


def get_high_throughput_system_prompt() -> str:
    """Return the system prompt for the high-throughput orchestrator."""
    return HIGH_THROUGHPUT_SYSTEM_PROMPT


def get_module_subagent_system_prompt(
    module_name: str,
    module_description: str,
    tool_names: list[str] | None = None,
) -> str:
    """Return a focused system prompt for a module subagent."""
    schema_guidance = _build_schema_guidance(module_name)
    file_guidance = MODULE_FILE_GUIDANCE.get(module_name, "Use thread-aware file tools when available.")
    validation_tool = MODULE_VALIDATION_TOOL_BY_NAME.get(module_name, "module validation tool")
    default_behavior = MODULE_DEFAULT_BEHAVIOR.get(module_name, "Use schema defaults unless user overrides.")
    semantic_required = MODULE_SEMANTIC_REQUIRED_FIELDS.get(module_name, [])
    semantic_required_str = ", ".join(semantic_required) if semantic_required else "none"
    tools_str = ", ".join(sorted(tool_names)) if tool_names else "unknown"

    return (
        f"You are the {module_name} module specialist.\n"
        f"Module scope: {module_description}\n\n"
        "Only handle tasks relevant to this module.\n"
        "Use the module's Pydantic schema/json-schema semantics when deciding defaults vs required input.\n\n"
        f"{schema_guidance}\n\n"
        "Operational rules:\n"
        f"- {default_behavior}\n"
        f"- Mandatory workflow fields: {semantic_required_str}\n"
        f"- File/path handling: {file_guidance}\n"
        f"- Always run `{validation_tool}` before claiming completion.\n"
        "- Pass `thread_id` to thread-aware tools when available.\n"
        "- Return validated, structured JSON-ready values.\n\n"
        f"Available tools for this subagent: {tools_str}"
    )


def get_sim_runner_system_prompt() -> str:
    """Return the system prompt for the simulation runner subagent."""
    return SIM_RUNNER_SYSTEM_PROMPT
