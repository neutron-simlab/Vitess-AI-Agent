"""screen: its schema, its tools, its image, and the pipeline it is optional in.

The rules the schema enforces were measured on the VITESS 3.8 binary this
repository builds (6bd0e006), with VITESS's own module tests Screen-1_Flat and
Screen-2_Cylinder. Both test commands reproduce VITESS's reference outputs, and
so do the same runs built from this schema's arguments. The measured numbers are
in the model's validator docstrings.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from juena_core.artifacts import ArtifactStore, set_artifact_store_for_tests
from vitess_ai.agents.advanced_mode.tools import build_batch_tools
from vitess_ai.agents.specialists.screen.tools import build_sweep_tools as screen_sweep
from vitess_ai.agents.specialists.screen.tools import build_tools as screen_tools
from vitess_ai.cli.arguments import parameters_to_arguments
from vitess_ai.mcp.server import render_plot
from vitess_ai.mcp.settings import ServerSettings
from vitess_ai.modules.catalog import cli_executables, execution_order
from vitess_ai.plots import read_monitor_file
from vitess_ai.run import VitessGateway
from vitess_ai.schema import ScreenParameters
from vitess_ai.schema.base import VtDetGeom, VtFormat2D
from vitess_ai.state import SimulationOrderEvent
from vitess_ai.tools import build_vitess_tools, plan_simulation

from doubles import (
    THREAD_ID,
    _swept,
    _validated,
    configured_modules,
    named_tool,
    raw_tools,
    runtime,
    simulation_payload,
    swept_modules,
)

DATA = Path(__file__).parent / "data"
WITH_SCREEN = [
    "readin",
    "guide",
    "writeout",
    "monitor1d",
    "monitor2d",
    "capture_flux",
    "screen",
]


@pytest.fixture
def artifact_store(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts", tmp_path / "audit.jsonl")
    set_artifact_store_for_tests(store)
    yield store
    set_artifact_store_for_tests(None)


def _flags(arguments: list[str]) -> dict[str, str]:
    return {argument[:2]: argument[2:] for argument in arguments}


# ---------------------------------------------------------------------------
# The schema
# ---------------------------------------------------------------------------


def test_every_flag_the_c_module_reads_is_a_field_and_no_other() -> None:
    """screen.c:222-261, OwnInit's `case` letters, all 10 of them."""
    flags = {
        field.json_schema_extra["flag"] for field in ScreenParameters.model_fields.values()
    }

    assert flags == {f"-{letter}" for letter in "OGFwhaADyz"}
    assert len(ScreenParameters.model_fields) == 10


def test_the_schema_defaults_are_the_vitess_gui_s_given_as_flags() -> None:
    """yaml/3.8/modules/screen.yaml, except the file name and the pixels.

    Not the C initialisers (c:31-40): with no geometry the module stops, and a
    screen of width, height and distance 0 is hit by nothing. The GUI's one
    pixel is no image, and its `.pos` file is not one the chat delivers.
    """
    assert parameters_to_arguments(ScreenParameters()) == [
        "-Oscreen.dat", "-G2", "-F1", "-w10.0", "-h10.0",
        "-a-175.0", "-A175.0", "-D100.0", "-y50", "-z50",
    ]


@pytest.mark.parametrize(
    ("parameters", "measured"),
    [
        # tests/module_tests/Screen-1_Flat/Test_Screen-1_Flat.sh
        (
            dict(eGeom=VtDetGeom.VT_DET_FLAT, eFormat=VtFormat2D.MATR_CMPT, Height=50,
                 Width=50, Distance=1000, nBinsZ=50, nBinsY=50),
            "-G2 -F2 -h50 -w50 -D1000 -z50 -y50",
        ),
        # tests/module_tests/Screen-2_Cylinder/Test_Screen-2_Cylinder.sh
        (
            dict(eGeom=VtDetGeom.VT_DET_CYL, eFormat=VtFormat2D.MATRIX, Height=50,
                 Distance=100, AngleMin=-180, AngleMax=180, nBinsZ=50, nBinsY=180),
            "-G1 -F0 -h50 -D100 -a-180 -A180 -z50 -y180",
        ),
    ],
)
def test_vitess_s_own_module_tests_are_the_command_lines_that_were_measured(
    parameters: dict[str, Any], measured: str
) -> None:
    """The schema's arguments for each VITESS test are the test's own, plus the
    values the chosen shape ignores at their defaults.

    Run on the binary, both gave output identical to VITESS's reference files --
    the defaults the shape ignores (the angles on a flat screen, the width on a
    cylinder) changed nothing.
    """
    ours = _flags(parameters_to_arguments(ScreenParameters(**parameters)))
    assert ours.pop("-O") == "screen.dat"
    ignored = {"-a", "-A"} if parameters["eGeom"] == VtDetGeom.VT_DET_FLAT else {"-w"}
    for flag in ignored:
        ours.pop(flag)

    assert {flag: float(value) for flag, value in ours.items()} == {
        flag: float(value) for flag, value in _flags(measured.split()).items()
    }


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"eGeom": VtDetGeom.VT_NO_DET_GEOM}, "eGeom must be VT_DET_FLAT"),
        ({"eFormat": VtFormat2D.NO_2D_FORMAT}, "eFormat must be one of"),
        ({"Width": 0.0}, "a flat screen needs Width greater than 0"),
        ({"Height": 0.0}, "greater than 0"),
        ({"Distance": 0.0}, "greater than 0"),
        ({"Distance": -1000.0}, "greater than 0"),
        ({"nBinsY": 0}, "greater than 0"),
        ({"nBinsZ": 0}, "greater than 0"),
        ({"eGeom": VtDetGeom.VT_DET_CYL, "AngleMin": 10.0, "AngleMax": 10.0}, "AngleMin < AngleMax"),
        ({"eGeom": VtDetGeom.VT_DET_CYL, "AngleMin": 30.0, "AngleMax": -30.0}, "AngleMin < AngleMax"),
        ({"eGeom": VtDetGeom.VT_DET_CYL, "AngleMin": 0.0, "AngleMax": 360.0}, "AngleMax <= 180"),
        ({"eGeom": VtDetGeom.VT_DET_CYL, "AngleMin": -270.0, "AngleMax": 90.0}, "-180 <= AngleMin"),
        ({"AngleMin": -30.0, "AngleMax": 30.0}, "would be ignored for a VT_DET_FLAT"),
        ({"eGeom": VtDetGeom.VT_DET_CYL, "Width": 50.0}, "Width would be ignored"),
        ({"OutFileName": ""}, "at least 1 character"),
    ],
)
def test_a_screen_vitess_would_misread_is_refused(
    changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        ScreenParameters(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"eGeom": VtDetGeom.VT_DET_CYL},
        {"eGeom": VtDetGeom.VT_DET_CYL, "AngleMin": -180.0, "AngleMax": 180.0},
        {"eGeom": VtDetGeom.VT_DET_CYL, "Width": 0.0},
        {"AngleMin": 0.0, "AngleMax": 0.0},
        {"nBinsY": 1, "nBinsZ": 1},
        {"eFormat": VtFormat2D.MATR_INT},
    ],
)
def test_the_neighbouring_valid_screen_is_accepted(changes: dict[str, Any]) -> None:
    ScreenParameters(**changes)


# ---------------------------------------------------------------------------
# The specialist's tools
# ---------------------------------------------------------------------------


def test_the_image_file_must_be_a_name_not_a_path(tmp_path: Path) -> None:
    tool = named_tool(screen_tools(project_root=tmp_path), "validate_screen_parameters")

    with pytest.raises(AssertionError, match="plain file name"):
        _validated(tool, {"OutFileName": "../elsewhere/screen.dat"})
    assert "screen" in _validated(tool, {"OutFileName": "detector.dat"})


def test_a_sweep_variant_keeps_the_defaults_it_omits(tmp_path: Path) -> None:
    tool = named_tool(screen_sweep(project_root=tmp_path), "validate_screen_variants")

    (variant,) = _swept(tool, [{"Distance": 200.0}])["screen"]

    assert variant["parameters"]["Distance"] == 200.0
    assert variant["parameters"]["Width"] == ScreenParameters().Width
    assert variant["parameters"]["nBinsY"] == ScreenParameters().nBinsY


# ---------------------------------------------------------------------------
# The image
# ---------------------------------------------------------------------------


def _settings(tmp_path: Path) -> ServerSettings:
    modules_root = tmp_path / "modules"
    modules_root.mkdir()
    for basename in cli_executables().values():
        (modules_root / basename).write_text("#!/bin/sh\ncat\n", encoding="utf-8")
    project_root = tmp_path / "projects"
    project_root.mkdir()
    return ServerSettings(
        project_root=project_root,
        modules_root=modules_root,
        host="127.0.0.1",
        port=9005,
        timeout_seconds=30,
    )


@pytest.mark.parametrize(
    ("fixture", "x_label", "shape"),
    [
        ("screen-flat.dat", "pos_y [cm]", (10, 10)),
        ("screen-cylinder.dat", "scat_angle [deg]", (5, 12)),
    ],
)
def test_the_screen_image_is_rendered_by_the_2d_plot_tool(
    fixture: str, x_label: str, shape: tuple[int, int], tmp_path: Path
) -> None:
    """Written by VITESS's own screen binary (tests/data/README.md).

    The screen writes the header of a 2D monitor, so the 2D plot tool renders
    it once it is given the file name -- no plot code of its own.
    """
    data = read_monitor_file(DATA / fixture)
    assert data.kind == "monitor2d"
    assert data.x_label == x_label
    assert data.y_label == "pos_z [cm]"
    assert data.intensity.shape == shape
    assert data.intensity.sum() > 0

    settings = _settings(tmp_path)
    run_id = str(uuid4())
    run_directory = settings.project_root / THREAD_ID / "outputs" / run_id
    run_directory.mkdir(parents=True)
    shutil.copy(DATA / fixture, run_directory / "screen.dat")

    plot = render_plot(
        settings,
        kind="monitor2d",
        thread_id=THREAD_ID,
        simulation_run_id=run_id,
        filename="screen.dat",
    )

    assert plot.path == "screen.png"
    assert (run_directory / "screen.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_2d_plot_tool_says_it_renders_the_screen_image(tmp_path: Path) -> None:
    tools = build_vitess_tools(VitessGateway(raw_tools()), project_root=tmp_path)

    assert "screen image" in named_tool(tools, "generate_monitor2d_plot").description


# ---------------------------------------------------------------------------
# The guided pipeline
# ---------------------------------------------------------------------------


def _screen_result(tmp_path: Path, **changes: Any) -> dict[str, Any]:
    return _validated(
        named_tool(screen_tools(project_root=tmp_path), "validate_screen_parameters"),
        changes,
    )


def _planned_state(planned: list[str], results: dict[str, Any]) -> dict[str, Any]:
    return {
        "planned_execution_order": planned,
        "simulation_order_events": [
            SimulationOrderEvent(kind="plan", execution_order=tuple(planned)).model_dump(
                mode="json"
            ),
            *[
                SimulationOrderEvent(kind="configured", module=module).model_dump(mode="json")
                for module in planned
            ],
        ],
        "module_results": results,
    }


def _run(tmp_path: Path, state: dict[str, Any], calls: list[dict]) -> Any:
    def payload(call: dict) -> dict:
        calls.append(call)
        return simulation_payload(
            thread_id=call["args"]["thread_id"],
            simulation_run_id=call["args"]["simulation_run_id"],
            modules=list(call["args"]["execution_order"]),
        )

    facade = build_vitess_tools(
        VitessGateway(raw_tools(run_simulation=payload)), project_root=tmp_path
    )
    return asyncio.run(
        named_tool(facade, "run_simulation").coroutine(runtime=runtime(state=state))
    )


def test_the_plan_has_a_screen_only_when_asked_for_and_then_after_capture_flux() -> None:
    without = plan_simulation.func(runtime=runtime())
    with_screen = plan_simulation.func(runtime=runtime(), include_optional=["screen"])

    assert "screen" not in without.update["planned_execution_order"]
    assert with_screen.update["planned_execution_order"] == WITH_SCREEN


def test_a_run_with_the_screen_runs_it_after_capture_flux(
    tmp_path: Path, artifact_store: ArtifactStore
) -> None:
    results = {**configured_modules(tmp_path), **_screen_result(tmp_path)}
    calls: list[dict] = []

    command = _run(tmp_path, _planned_state(WITH_SCREEN, results), calls)

    assert command.update["messages"][0].status == "success"
    assert list(calls[0]["args"]["execution_order"]) == WITH_SCREEN
    assert calls[0]["args"]["module_results"]["screen"]["cli_parameters"] == (
        parameters_to_arguments(ScreenParameters())
    )


def test_a_screen_configured_under_an_earlier_plan_does_not_block_a_run_without_it(
    tmp_path: Path, artifact_store: ArtifactStore
) -> None:
    results = {**configured_modules(tmp_path), **_screen_result(tmp_path)}
    calls: list[dict] = []

    command = _run(tmp_path, _planned_state(list(execution_order()), results), calls)

    assert command.update["messages"][0].status == "success"
    assert "screen" not in calls[0]["args"]["execution_order"]


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------


def test_the_batch_runs_an_untouched_screen_with_its_defaults_last(
    tmp_path: Path, artifact_store: ArtifactStore
) -> None:
    """Through both real sweep tools: each entry's pipeline comes from the entry."""
    calls: list[dict] = []

    def payload(call: dict) -> dict:
        calls.append(call)
        return simulation_payload(
            thread_id=call["args"]["thread_id"],
            simulation_run_id=call["args"]["simulation_run_id"],
            modules=list(call["args"]["execution_order"]),
        )

    tools = build_batch_tools(
        VitessGateway(raw_tools(run_simulation=payload)), project_root=tmp_path
    )
    planned = named_tool(tools, "write_simulation_matrix").func(
        runtime=runtime(state={"module_variants": swept_modules(tmp_path)}),
        combination="paired",
        run_names=["with screen"],
        include_optional=["screen"],
    )
    (entry,) = planned.update["simulation_plan"]
    assert list(entry["modules"]) == WITH_SCREEN
    assert entry["modules"]["screen"]["parameters"] == ScreenParameters().model_dump(mode="json")

    asyncio.run(
        named_tool(tools, "run_batch_from_matrix").coroutine(
            runtime=runtime(state={"simulation_plan": planned.update["simulation_plan"]})
        )
    )

    assert list(calls[0]["args"]["execution_order"]) == WITH_SCREEN
