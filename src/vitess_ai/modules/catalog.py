"""Which VITESS modules exist, in what order, and what each one accepts.

This is a data table, not a registry. The distinction matters, because JüNA's
rule is that adding an *agent* requires a package, a builder import and one
explicit entry -- no discovery, no registry. That rule is about agents. These
rows are about VITESS physics modules, and four unrelated callers need the same
handful of facts about them: the command generator needs the executable, the
file store needs to know what may be uploaded, the sidebar needs a label and an
order, and the specialists need their own row.

Without this table each of those grows its own copy. Two such copies existed in
the first-generation agent -- ``FALLBACK_MODULE_EXECUTABLES`` in
``mcp/supervisor_tools.py`` and ``FALLBACK_MODULE_TYPES`` in
``server/file_storage.py`` -- and they existed for a reason worth not repeating:
the old catalog carried an ``agent_class``, so importing it imported LangChain,
and a FastMCP server that wanted a five-entry ``{module: executable}`` mapping
dragged in the whole agent framework to get it. The fallbacks were the escape.

So: **this module imports pydantic and nothing else**, and a test asserts that
importing it pulls in neither ``langchain`` nor ``deepagents``. ``agent_class``,
``tool_factory`` and ``validation_tool_patterns`` are gone; the five module
specialists are built by five explicit builders, listed one line each, with
JüNA's rule unchanged.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "DATA_FILE_EXTENSIONS",
    "UploadSchema",
    "ModuleSpec",
    "MODULES",
    "module_spec",
    "execution_order",
    "cli_executables",
    "upload_modules",
]

#: What a neutron data file may be called. Not the instrument file, which has
#: its own list below.
DATA_FILE_EXTENSIONS = ("dat", "txt", "csv", "nxs", "h5")


class UploadSchema(BaseModel):
    """What a module accepts from the user as a file.

    There is deliberately no ``default_filename`` field. Three rows used to
    carry one -- ``writeout``, ``monitor1d`` and ``monitor2d`` -- under an
    upload mode that uploaded nothing; each merely set an output filename that
    the parameter schema already declares, with its own CLI flag and its own
    default. The two copies had already drifted: the sidebar said
    ``output.out`` where ``WriteoutParameters.sOutFileName`` said
    ``output.dat``. The schema owns those names now, and a second copy here is
    the bug that was removed rather than a feature to preserve.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["file_single", "file_multi"]
    label: str
    help: str
    extensions: tuple[str, ...] = Field(min_length=1)
    max_files: int = Field(ge=1)


class ModuleSpec(BaseModel):
    """One VITESS module, described by data alone.

    ``cli_executable`` and ``accepts_upload`` are **independent**, which is why
    neither a single ``kind`` field nor one implying the other would work. Two
    rows prove it: ``instrument`` is uploaded but never executed, and
    ``writeout`` is executed but accepts no upload.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    display_name: str
    description: str
    #: Position in the catalog, and among the executable rows, the order the
    #: VITESS pipeline runs them in. Unique across the table so that sorting is
    #: not left to a tiebreak.
    order: int = Field(ge=1)
    #: A **basename**, never a path: "read_in", not "$V/read_in". The old
    #: catalog stored the latter, a shell variable that expands to nothing
    #: outside a shell. It is resolved against the trusted modules root at
    #: execution time and asserted to be inside it. ``None`` means this row
    #: runs no binary.
    cli_executable: str | None = None
    #: ``None`` means there is nothing to upload for this module.
    accepts_upload: UploadSchema | None = None


MODULES: tuple[ModuleSpec, ...] = (
    ModuleSpec(
        name="readin",
        display_name="Read-in Parameters",
        description="Configure neutron input parameters and initial conditions",
        order=1,
        cli_executable="read_in",
        accepts_upload=UploadSchema(
            mode="file_multi",
            label="Read-in Module Files",
            help="Select up to 3 input files for neutron simulation.",
            extensions=DATA_FILE_EXTENSIONS,
            max_files=3,
        ),
    ),
    # Sits next to the module it feeds -- it supplies read-in's `sInstrInfIn`
    # (`--I`) -- and runs nothing itself. Its `order` therefore positions it in
    # the sidebar only; `execution_order()` skips it because it has no
    # executable, so the pipeline's `--N1`..`--N5` numbering is unaffected.
    ModuleSpec(
        name="instrument",
        display_name="Instrument File",
        description="Upload instrument file used by read-in module (sInstrInfIn).",
        order=2,
        accepts_upload=UploadSchema(
            mode="file_single",
            label="Instrument File",
            help="Select one instrument file (.inf) for neutron simulation.",
            extensions=("inf", "dat", "txt"),
            max_files=1,
        ),
    ),
    ModuleSpec(
        name="guide",
        display_name="Guide Parameters",
        description="Configure neutron guide specifications and geometry",
        order=3,
        cli_executable="guide_parallel",
        accepts_upload=UploadSchema(
            mode="file_single",
            label="Guide Module File",
            help=(
                "Optional: select one guide input file for neutron simulation, "
                "or use default configuration."
            ),
            extensions=DATA_FILE_EXTENSIONS,
            max_files=1,
        ),
    ),
    ModuleSpec(
        name="writeout",
        display_name="Writeout Parameters",
        description="Configure output settings and data formats",
        order=4,
        cli_executable="writeout",
    ),
    ModuleSpec(
        name="monitor1d",
        display_name="Monitor1D Parameters",
        description="Configure 1D monitor parameters for neutron detection",
        order=5,
        cli_executable="monitor1D",
    ),
    ModuleSpec(
        name="monitor2d",
        display_name="Monitor2D Parameters",
        description="Configure 2D monitor parameters for neutron detection",
        order=6,
        cli_executable="monitor2D",
    ),
)

_BY_NAME = {spec.name: spec for spec in MODULES}


def module_spec(name: str) -> ModuleSpec:
    """Return one module's row, or raise.

    Raising is the point. A builder that asks for a row that is not here has
    been misspelled or the table has been edited out from under it, and both
    are broken installs. The first-generation agent degraded through a fallback
    table instead, which is how two copies of the executable mapping came to
    exist and disagree.
    """
    try:
        return _BY_NAME[name]
    except KeyError:
        known = ", ".join(sorted(_BY_NAME))
        raise KeyError(f"Unknown VITESS module {name!r}. Known modules: {known}") from None


def execution_order() -> tuple[str, ...]:
    """The modules that run a binary, in the order the pipeline runs them."""
    return tuple(
        spec.name
        for spec in sorted(MODULES, key=lambda spec: spec.order)
        if spec.cli_executable is not None
    )


def cli_executables() -> dict[str, str]:
    """The ``{module: basename}`` mapping ``generate_cli_command`` requires."""
    return {
        spec.name: spec.cli_executable
        for spec in MODULES
        if spec.cli_executable is not None
    }


def upload_modules() -> tuple[ModuleSpec, ...]:
    """Every row that accepts a file, in catalog order."""
    return tuple(
        spec
        for spec in sorted(MODULES, key=lambda spec: spec.order)
        if spec.accepts_upload is not None
    )
