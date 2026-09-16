"""The catalog is data, and the things that used to make it more than data are gone."""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from importlib.metadata import requires
from pathlib import Path

import pytest
from pydantic import ValidationError

from vitess_ai.cli.command import generate_cli_command
from vitess_ai.modules.catalog import (
    MODULES,
    ModuleSpec,
    UploadSchema,
    cli_executables,
    execution_order,
    module_spec,
    upload_modules,
)
from vitess_ai.schema import (
    Monitor1DParameters,
    Monitor2DParameters,
    WriteoutParameters,
)


EXECUTES = ("readin", "guide", "writeout", "monitor1d", "monitor2d")
UPLOADS = ("readin", "instrument", "guide")
CATALOG = ("readin", "instrument", "guide", "writeout", "monitor1d", "monitor2d")


def test_pydantic_is_a_direct_runtime_dependency() -> None:
    """The catalog imports Pydantic, so the package must declare it itself."""
    dependencies = requires("vitess-ai") or ()
    dependency_names = {
        re.split(r"[<>=!~;\s\[]", requirement, maxsplit=1)[0].lower()
        for requirement in dependencies
    }

    assert "pydantic" in dependency_names


def test_catalog_source_imports_only_typing_and_pydantic() -> None:
    """Do not let a project or agent-framework import recreate the old cycle."""
    source = Path(__file__).parents[1] / "src/vitess_ai/modules/catalog.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imports = {
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (node.names if isinstance(node, ast.Import) else [None])
    }

    assert imports == {"__future__", "typing", "pydantic"}


def test_importing_the_catalog_does_not_import_the_agent_framework() -> None:
    """The whole reason the two fallback executable tables existed.

    The old catalog carried an `agent_class`, so importing it imported
    LangChain; a FastMCP server that wanted five strings paid for the entire
    agent framework, and two hand-maintained copies of the mapping were written
    to avoid that. Run in a subprocess because this test session has already
    imported plenty -- asking `sys.modules` in-process would prove nothing.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import vitess_ai.modules.catalog, sys;"
            " print('langchain' in sys.modules, 'deepagents' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).resolve().parents[1],
    )

    assert result.stdout.split() == ["False", "False"]


def test_catalog_contains_exactly_the_six_known_modules() -> None:
    """An inert seventh row must not disappear between the capability filters."""
    assert tuple(spec.name for spec in MODULES) == CATALOG


def test_catalog_models_expose_only_the_decided_data_fields() -> None:
    assert tuple(ModuleSpec.model_fields) == (
        "name",
        "display_name",
        "description",
        "order",
        "cli_executable",
        "accepts_upload",
    )
    assert tuple(UploadSchema.model_fields) == (
        "mode",
        "label",
        "help",
        "extensions",
        "max_files",
    )


@pytest.mark.parametrize(
    ("model", "values"),
    [
        (
            ModuleSpec,
            {
                "name": "readin",
                "display_name": "Read-in Parameters",
                "description": "Configure neutron input parameters",
                "order": 1,
                "cli_executable": "read_in",
                "agent_class": object,
            },
        ),
        (
            UploadSchema,
            {
                "mode": "file_single",
                "label": "Output file",
                "help": "Not an upload",
                "extensions": ("dat",),
                "max_files": 1,
                "default_filename": "output.out",
            },
        ),
    ],
)
def test_catalog_models_reject_removed_fields(
    model: type[ModuleSpec] | type[UploadSchema], values: dict[str, object]
) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        model(**values)


def test_executables_are_basenames_not_paths() -> None:
    """`$V/read_in` is a shell variable, and CP1 removed the shell."""
    offenders = [
        spec.name
        for spec in MODULES
        if spec.cli_executable is not None
        and ("/" in spec.cli_executable or "$" in spec.cli_executable)
    ]

    assert not offenders, f"catalog rows carrying a path or a shell variable: {offenders}"


def test_only_the_five_pipeline_modules_run_a_binary() -> None:
    """Named rather than blanket.

    "Every row has an executable" is false -- `instrument` uploads without
    executing -- and a blanket assertion would be weakened to nothing the first
    time it failed. So the set is named.
    """
    assert tuple(sorted(spec.name for spec in MODULES if spec.cli_executable)) == tuple(
        sorted(EXECUTES)
    )
    assert module_spec("instrument").cli_executable is None


def test_exactly_three_rows_accept_an_upload() -> None:
    """`writeout`, `monitor1d` and `monitor2d` left the upload schema entirely.

    They were declared uploads under a `path_only` mode that uploaded nothing:
    each set an output filename the parameter schema already owns. Deleting
    them halves the upload UI and removes a whole UI mode.
    """
    assert tuple(spec.name for spec in upload_modules()) == UPLOADS


def test_the_catalog_declares_no_output_filename() -> None:
    """The schema owns those names, and a second copy here is the removed bug.

    Asserted twice over: no field of `UploadSchema` could hold one, and none of
    the four filenames the old rows carried appears anywhere in the table.
    """
    assert "default_filename" not in UploadSchema.model_fields

    table = json.dumps([spec.model_dump() for spec in MODULES])
    for filename in ("output.out", "output.dat", "monitor1D.dat", "monitor2D.dat"):
        assert filename not in table, f"{filename} is still declared in the catalog"


@pytest.mark.parametrize(
    ("model", "field_name", "flag", "default"),
    [
        (WriteoutParameters, "sOutFileName", "-A", "output.dat"),
        (Monitor1DParameters, "fMonitorFilename", "-O", "monitor1D.dat"),
        (Monitor2DParameters, "fMonitorFilename", "-O", "monitor2D.dat"),
    ],
)
def test_the_schema_still_owns_each_deleted_filename(
    model: type, field_name: str, flag: str, default: str
) -> None:
    """Deleting the rows moved the ownership; it did not drop the values.

    The sidebar's `writeout` default was `output.out` while the schema said
    `output.dat` -- two defaults for one value, in two files, with nothing to
    make them agree. This asserts the surviving one.
    """
    field = model.model_fields[field_name]

    assert field.default == default
    assert field.json_schema_extra["flag"] == flag


def test_execution_order_is_the_pipeline_order() -> None:
    assert execution_order() == EXECUTES


def test_orders_are_unique_so_sorting_needs_no_tiebreak() -> None:
    """The old table gave `guide` and `instrument` the same order.

    Sorting then fell back to the name, which is a coincidence rather than a
    decision, and it silently decides what the sidebar looks like.
    """
    orders = [spec.order for spec in MODULES]

    assert len(set(orders)) == len(orders)
    assert orders == sorted(orders), "MODULES is not written in catalog order"


def test_asking_for_a_row_that_is_not_there_raises() -> None:
    with pytest.raises(KeyError, match="Unknown VITESS module 'monitor3d'"):
        module_spec("monitor3d")


def test_the_catalog_mapping_is_what_the_command_generator_wants(
    tmp_path: Path,
) -> None:
    """The one assertion that would catch the two tables drifting apart again.

    `generate_cli_command` takes its mapping as an argument and stays free of
    configuration, which is right -- but it means nothing checks that the
    catalog can actually supply it. This feeds the real mapping to the real
    generator.
    """
    modules_path = tmp_path / "modules"
    modules_path.mkdir()
    for basename in cli_executables().values():
        binary = modules_path / basename
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        binary.chmod(0o755)

    result = generate_cli_command(
        {name: {"cli_parameters": ["-a1"]} for name in execution_order()},
        list(execution_order()),
        thread_id="11111111-1111-4111-8111-111111111111",
        simulation_run_id="22222222-2222-4222-8222-222222222222",
        project_path=tmp_path / "projects",
        modules_path=modules_path,
        module_executables=cli_executables(),
    )

    assert result["success"] is True
    assert result["modules_included"] == list(EXECUTES)
    assert [Path(vector[0]).name for vector in result["argument_vectors"]] == [
        cli_executables()[name] for name in EXECUTES
    ]


def test_rows_are_frozen() -> None:
    """A data table that a caller can edit at runtime is not a source of truth."""
    with pytest.raises(ValidationError, match="Instance is frozen"):
        module_spec("readin").order = 99
