"""The list of VITESS modules: plain data, with no agent code imported."""

from vitess_ai.modules.catalog import (
    MODULES,
    ModuleSpec,
    UploadSchema,
    cli_executables,
    execution_order,
    module_spec,
    upload_modules,
)

__all__ = [
    "MODULES",
    "ModuleSpec",
    "UploadSchema",
    "cli_executables",
    "execution_order",
    "module_spec",
    "upload_modules",
]
