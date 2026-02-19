"""
Central module catalog for graph registration, UI metadata, and upload behavior.

This module is the single source of truth for module registration metadata so
new modules can be added once and consumed consistently by:
- Supervisor graph registration
- Tool loading and validation detection
- Configuration endpoints
- Streamlit upload UI
- CLI executable mapping
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from vitess_ai.server_agents.base_module_agent import ModuleBuilder, ModuleMetadata
from vitess_ai.server_agents.readin_module_agent import ReadInModuleAgent
from vitess_ai.server_agents.guide_module_agent import GuideModuleAgent
from vitess_ai.server_agents.monitor1d_module_agent import Monitor1DModuleAgent
from vitess_ai.server_agents.monitor2d_module_agent import Monitor2DModuleAgent
from vitess_ai.server_agents.writeout_module_agent import WriteoutModuleAgent
from vitess_ai.tools import (
    get_guide_tools,
    get_monitor_tools,
    get_readin_tools,
    get_writeout_tools,
)


DEFAULT_DATA_FILE_EXTENSIONS = ["dat", "txt", "csv", "nxs", "h5"]


def _build_graph_modules() -> list[ModuleMetadata]:
    """Build default graph-enabled module metadata."""
    return [
        ModuleBuilder.create(
            name="readin",
            display_name="Read-in Parameters",
            description="Configure neutron input parameters and initial conditions",
            agent_class=ReadInModuleAgent,
            order=1,
            tool_factory=get_readin_tools,
            validation_tool_patterns=["validate_readin_module"],
            cli_executable="$V/read_in",
            upload_schema_sidebar={
                "mode": "file_multi",
                "label": "Read-in Module Files",
                "help": "Select up to 3 input files for neutron simulation.",
                "extensions": DEFAULT_DATA_FILE_EXTENSIONS,
                "max_files": 3,
            },
        ),
        ModuleBuilder.create(
            name="guide",
            display_name="Guide Parameters",
            description="Configure neutron guide specifications and geometry",
            agent_class=GuideModuleAgent,
            order=2,
            tool_factory=get_guide_tools,
            validation_tool_patterns=["validate_guide_parameters"],
            cli_executable="$V/guide_parallel",
            upload_schema_sidebar={
                "mode": "file_single",
                "label": "Guide Module File",
                "help": "Select one guide input file for neutron simulation.",
                "extensions": DEFAULT_DATA_FILE_EXTENSIONS,
                "max_files": 1,
            },
        ),
        ModuleBuilder.create(
            name="writeout",
            display_name="Writeout Parameters",
            description="Configure output settings and data formats",
            agent_class=WriteoutModuleAgent,
            order=3,
            tool_factory=get_writeout_tools,
            validation_tool_patterns=["validate_writeout_module"],
            cli_executable="$V/writeout",
            upload_schema_sidebar={
                "mode": "path_only",
                "label": "Writeout Save Path",
                "help": "Set an output path for writeout results.",
                "default_filename": "output.out",
                "button_text": "Save Path",
            },
        ),
        ModuleBuilder.create(
            name="monitor1d",
            display_name="Monitor1D Parameters",
            description="Configure 1D monitor parameters for neutron detection",
            agent_class=Monitor1DModuleAgent,
            order=4,
            tool_factory=get_monitor_tools,
            validation_tool_patterns=["validate_monitor1d_module"],
            cli_executable="$V/monitor1D",
            upload_schema_sidebar={
                "mode": "path_only",
                "label": "Monitor1D Output File Path",
                "help": "Set an output path for Monitor1D results.",
                "default_filename": "monitor1D.dat",
                "button_text": "Save Path",
            },
        ),
        ModuleBuilder.create(
            name="monitor2d",
            display_name="Monitor2D Parameters",
            description="Configure 2D monitor parameters for neutron detection",
            agent_class=Monitor2DModuleAgent,
            order=5,
            tool_factory=get_monitor_tools,
            validation_tool_patterns=["validate_monitor2d_module"],
            cli_executable="$V/monitor2D",
            upload_schema_sidebar={
                "mode": "path_only",
                "label": "Monitor2D Output File Path",
                "help": "Set an output path for Monitor2D results.",
                "default_filename": "monitor2D.dat",
                "button_text": "Save Path",
            },
        )
    ]


# Upload-only entries are not graph modules, but still appear in file UI/storage.
_AUXILIARY_UPLOAD_MODULES: list[dict[str, Any]] = [
    {
        "name": "instrument",
        "display_name": "Instrument File",
        "description": "Upload instrument file used by read-in module (sInstrInfIn).",
        "order": 2,
        "optional": True,
        "agent_enabled": False,
        "upload_schema_sidebar": {
            "mode": "file_single",
            "label": "Instrument File",
            "help": "Select one instrument file (.inf) for neutron simulation.",
            "extensions": ["inf", "dat", "txt"],
            "max_files": 1,
        },
    }
]


@lru_cache(maxsize=1)
def _cached_graph_modules() -> tuple[ModuleMetadata, ...]:
    modules = sorted(_build_graph_modules(), key=lambda m: m.order)
    return tuple(modules)


def get_graph_module_metadata() -> list[ModuleMetadata]:
    """Return graph-enabled modules as ModuleMetadata list."""
    return list(_cached_graph_modules())


def _module_to_info(module: ModuleMetadata) -> dict[str, Any]:
    return {
        "name": module.name,
        "display_name": module.display_name,
        "description": module.description,
        "optional": module.optional,
        "order": module.order,
        "agent_enabled": True,
        "upload_schema_sidebar": module.upload_schema_sidebar,
        "validation_tool_patterns": module.validation_tool_patterns,
        "cli_executable": module.cli_executable,
    }


def get_graph_modules_info() -> list[dict[str, Any]]:
    """Return graph module info dictionaries for API/UI use."""
    return [_module_to_info(module) for module in get_graph_module_metadata()]


def get_upload_modules_info(include_auxiliary: bool = True) -> list[dict[str, Any]]:
    """
    Return modules that can appear in upload UI.

    Includes graph modules with upload_schema_sidebar and optional upload-only entries.
    """
    modules = [
        _module_to_info(module)
        for module in get_graph_module_metadata()
        if module.upload_schema_sidebar
    ]
    if include_auxiliary:
        modules.extend(_AUXILIARY_UPLOAD_MODULES)
    return sorted(modules, key=lambda m: (m.get("order", 999), m.get("name", "")))


def get_upload_module_names(include_auxiliary: bool = True) -> list[str]:
    """Return upload module names used for storage validation and UI filtering."""
    return [m["name"] for m in get_upload_modules_info(include_auxiliary=include_auxiliary)]


def get_cli_executable_mapping() -> dict[str, str]:
    """Return module-to-executable mapping for CLI generation."""
    mapping: dict[str, str] = {}
    for module in get_graph_module_metadata():
        if module.cli_executable:
            mapping[module.name] = module.cli_executable
    return mapping
