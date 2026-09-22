"""The VITESS module catalog: pure data, no agent imports."""

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
