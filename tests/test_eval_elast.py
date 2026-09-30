"""eval_elast: its schema, its tools, its spectrum, and the pipeline it is optional in.

The rules the schema enforces were measured on the VITESS 3.8 binary this
repository builds (6bd0e006), with VITESS's own module tests EvalElast-1 to -4.
Built from this schema's arguments, each test reproduces every data row of
VITESS's reference output. The measured numbers are in the model's validator
docstrings.
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
from vitess_ai.agents.specialists.eval_elast.tools import (
    build_sweep_tools as eval_elast_sweep,
)
from vitess_ai.agents.specialists.eval_elast.tools import (
    build_tools as eval_elast_tools,
)
from vitess_ai.agents.specialists.sample_elasticisotr.tools import (
    build_tools as sample_tools,
)
from vitess_ai.agents.specialists.screen.tools import build_tools as screen_tools
from vitess_ai.cli.arguments import parameters_to_arguments
from vitess_ai.mcp.server import render_plot
from vitess_ai.mcp.settings import ServerSettings
from vitess_ai.modules.catalog import SAMPLE_MODULE, cli_executables, execution_order
from vitess_ai.plots import read_monitor_file
from vitess_ai.run import VitessGateway
from vitess_ai.schema import EvalElastParameters
from vitess_ai.schema.base import VtAxis, VtEvalPar
from vitess_ai.schema.eval_elast_module import MAX_BINS, logarithmic_bin_count
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
BASE = ["readin", "guide", "writeout", "monitor1d", "monitor2d", "capture_flux"]
EVERYTHING = [
    "readin",
    "guide",
    "sample_elasticisotr",
    "writeout",
    "monitor1d",
    "monitor2d",
    "capture_flux",
    "screen",
    "eval_elast",
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


def test_every_flag_the_c_module_reads_is_a_field_except_peak_integration() -> None:
    """eval_elast.c:339-437, OwnInit's 21 `case` letters, less -O and -I.

    -O and -I are the optional peak integration: an intensity file written from
    an info file of peak ranges. The info file would be an upload, and the
    current sample has no peaks, so they are left out on purpose.
    """
    flags = {
        field.json_schema_extra["flag"]
        for field in EvalElastParameters.model_fields.values()
    }

    assert flags == {f"-{letter}" for letter in "koOInmMRdrpcwtAlDTeEC"} - {"-O", "-I"}
    assert len(EvalElastParameters.model_fields) == 19


def test_the_schema_defaults_are_the_vitess_gui_s_given_as_flags() -> None:
    """yaml/3.8/modules/eval_elast.yaml, except the evaluation parameter.

    Not the C initialisers (c:46-72): evaluation parameter 0 and 0 bins count
    nothing. The GUI's d-spacing at 2 Å puts VITESS's default sample above 82 Å,
    outside its 0-10 Å range, so the default bins by scattering angle instead.
    """
    assert parameters_to_arguments(EvalElastParameters()) == [
        "-k3", "-oeval_elast.dat", "-n100", "-m0.0", "-M10.0", "-R0.0", "-d0.0",
        "-r2.0", "-p1", "-c0", "-w0", "-t1", "-A-1", "-T0.0", "-C-1",
    ]


WINDOW = dict(EvalTimeMin=-1e10, EvalTimeMax=1e10)
TOF = dict(bTOF=True, TotLength=2101, DetDist=100)


@pytest.mark.parametrize(
    ("parameters", "measured"),
    [
        # tests/module_tests/EvalElast-*/Test_EvalElast-*.sh, less -o and --Fno_file
        (
            dict(eKind=VtEvalPar.VT_EVAL_ANGLE, nBins=180, MinX=0, MaxX=180, LmbdRef=1.5,
                 bPathCor=False, **WINDOW),
            "-k3 -n180 -m0 -M180 -r1.5 -p1 -c0 -A-1 -w0 -t0 -T0.0 -e-1.e10 -E1.e10 -C-1",
        ),
        (
            dict(eKind=VtEvalPar.VT_EVAL_Q, nBins=180, MinX=0, MaxX=10, TimeOffset=0.2,
                 **TOF, **WINDOW),
            "-k2 -n180 -m0 -M10 -p1 -c0 -A-1 -w1 -t1 -l2101 -D100 -T0.2 -e-1.e10 -E1.e10 -C-1",
        ),
        (
            dict(eKind=VtEvalPar.VT_EVAL_DSP, nBins=400, MinX=0, MaxX=8, TimeOffset=0.2,
                 **TOF, **WINDOW),
            "-k1 -n400 -m0 -M8 -p1 -c0 -A-1 -w1 -t1 -l2101 -D100 -T0.2 -e-1.e10 -E1.e10 -C-1",
        ),
        (
            dict(eKind=VtEvalPar.VT_EVAL_LMBD, nBins=250, MinX=0, MaxX=0.25, **TOF, **WINDOW),
            "-k4 -n250 -m0 -M0.25 -p1 -c0 -A-1 -w1 -t1 -l2101 -D100 -T0.0 -e-1.e10 -E1.e10 -C-1",
        ),
    ],
)
def test_vitess_s_own_module_tests_are_the_command_lines_that_were_measured(
    parameters: dict[str, Any], measured: str
) -> None:
    """The schema's arguments for each VITESS test are the test's own, plus the
    values a mode ignores at their defaults: -R0 and -d0, and -r with TOF.

    Run on the binary, all four gave every data row of VITESS's reference file.
    """
    ours = _flags(parameters_to_arguments(EvalElastParameters(**parameters)))
    assert ours.pop("-o") == "eval_elast.dat"
    assert ours.pop("-R") == "0.0" and ours.pop("-d") == "0.0"
    if parameters.get("bTOF"):
        assert ours.pop("-r") == "2.0"

    assert {flag: float(value) for flag, value in ours.items()} == {
        flag: float(value) for flag, value in _flags(measured.split()).items()
    }


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"eKind": VtEvalPar.VT_NO_EVAL}, "eKind must name what to bin by"),
        ({"MinX": 10.0}, "MinX must be smaller than MaxX"),
        ({"MinX": 10.0, "MaxX": 0.0}, "MinX must be smaller than MaxX"),
        ({"nBins": 0}, "greater than or equal to 1"),
        ({"nBins": 10001}, "less than or equal to 10000"),
        ({"LogProz": -5.0}, "greater than or equal to 0"),
        ({"LogProz": 5.0}, "needs MinX greater than 0"),
        ({"LogProz": 0.05, "MinX": 1.0, "MaxX": 180.0}, "more than 10000 bins"),
        ({"LogProz": 5.0, "MinX": 1.0, "nBins": 7}, "nBins would be ignored"),
        ({"DeadSpot": -5.0}, "greater than or equal to 0"),
        ({"eScatAxis": VtAxis.X_AXIS}, "X_AXIS stops the module"),
        ({"EvalTimeMin": 5.0, "EvalTimeMax": 1.0}, "EvalTimeMin must be smaller"),
        ({"nColour": -2}, "greater than or equal to -1"),
        ({"eKind": VtEvalPar.VT_EVAL_Q, "LmbdRef": 0.0}, "needs LmbdRef greater than 0"),
        ({"eKind": VtEvalPar.VT_EVAL_DSP, "LmbdRef": 0.0}, "needs LmbdRef greater than 0"),
        ({"eKind": VtEvalPar.VT_EVAL_LMBD, "LmbdRef": 0.0}, "needs LmbdRef greater than 0"),
        ({"TotLength": 2101.0}, "TotLength would be ignored without TOF"),
        ({"DetDist": 100.0}, "DetDist would be ignored without TOF"),
        ({"bTOF": True}, "TOF \\(bTOF\\) needs TotLength"),
        ({"bTOF": True, "TotLength": 0.0}, "greater than 0"),
        ({"bTOF": True, "TotLength": 2101.0}, "needs DetDist"),
        (
            {"bTOF": True, "TotLength": 2101.0, "bPathCor": False, "DetDist": 100.0},
            "DetDist would be ignored without path correction",
        ),
        ({**TOF, "LmbdRef": 5.0}, "LmbdRef would be ignored with TOF"),
        ({"EvalFileName": ""}, "at least 1 character"),
    ],
)
def test_a_spectrum_vitess_would_misread_is_refused(
    changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        EvalElastParameters(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        # Measured: the angle does not use the reference wavelength.
        {"LmbdRef": 0.0},
        {"LogProz": 5.0, "MinX": 1.0, "MaxX": 180.0},
        {"nBins": 10000},
        {**TOF},
        {**TOF, "LmbdRef": 0.0},
        {"bTOF": True, "TotLength": 2101.0, "bPathCor": False},
        # Measured: a negative offset is a shift like any other.
        {"TimeOffset": -0.2},
        {"EvalTimeMin": 5.0},
        {"eScatAxis": VtAxis.Y_AXIS},
        {"eScatAxis": VtAxis.Z_AXIS},
        {"nColour": 0},
        # Without TOF, path correction changes nothing either way (measured).
        {"bPathCor": False},
    ],
)
def test_the_neighbouring_valid_spectrum_is_accepted(changes: dict[str, Any]) -> None:
    EvalElastParameters(**changes)


@pytest.mark.parametrize("axis", [VtAxis.Y_AXIS, VtAxis.Z_AXIS])
@pytest.mark.parametrize("kind", [VtEvalPar.VT_EVAL_ANGLE, VtEvalPar.VT_EVAL_Q, VtEvalPar.VT_EVAL_DSP])
def test_dead_spot_cannot_silently_remove_the_negative_side(axis, kind) -> None:
    # Binary check: neutrons at -10 and +10 degrees both count with -d0;
    # with -d1 only +10 counts, for either planar scattering axis.
    with pytest.raises(ValidationError, match="removes every negative scattering angle"):
        EvalElastParameters(eScatAxis=axis, eKind=kind, MinX=-20, MaxX=20, DeadSpot=1)


@pytest.mark.parametrize("axis", [VtAxis.Y_AXIS, VtAxis.Z_AXIS])
@pytest.mark.parametrize("kind", [VtEvalPar.VT_EVAL_ANGLE, VtEvalPar.VT_EVAL_Q, VtEvalPar.VT_EVAL_DSP])
def test_signed_ranges_without_a_dead_spot_and_one_sided_cutoffs_remain_valid(axis, kind) -> None:
    EvalElastParameters(eScatAxis=axis, eKind=kind, MinX=-20, MaxX=20, DeadSpot=0)
    EvalElastParameters(eScatAxis=axis, eKind=kind, MinX=0, MaxX=20, DeadSpot=1)


def test_negative_wavelength_difference_is_not_a_negative_scattering_angle() -> None:
    EvalElastParameters(eScatAxis=VtAxis.Y_AXIS, eKind=VtEvalPar.VT_EVAL_LMBD,
                        MinX=-1, MaxX=1, DeadSpot=1)
    EvalElastParameters(eScatAxis=VtAxis.NO_AXIS, MinX=-20, MaxX=20, DeadSpot=1)


@pytest.mark.parametrize(
    ("percent", "minimum", "maximum", "vitess_bins"),
    [(5, 1, 180, 107), (1, 0.5, 10, 302), (12.5, 0.01, 7, 56)],
)
def test_logarithmic_bins_are_counted_as_vitess_makes_them(
    percent: float, minimum: float, maximum: float, vitess_bins: int
) -> None:
    """`vitess_bins` is the number of rows VITESS's own eval_elast wrote."""
    assert logarithmic_bin_count(minimum, maximum, percent) == vitess_bins


def test_logarithmic_bins_past_the_array_are_counted_as_too_many() -> None:
    """VITESS made 10 389 bins here, past its 10 001-entry arrays (exit 0)."""
    assert logarithmic_bin_count(1, 180, 0.05) > MAX_BINS


# ---------------------------------------------------------------------------
# The specialist's tools
# ---------------------------------------------------------------------------


def test_the_spectrum_file_must_be_a_name_not_a_path(tmp_path: Path) -> None:
    tool = named_tool(
        eval_elast_tools(project_root=tmp_path), "validate_eval_elast_parameters"
    )

    with pytest.raises(AssertionError, match="plain file name"):
        _validated(tool, {"EvalFileName": "/tmp/eval.dat"})
    assert "eval_elast" in _validated(tool, {"EvalFileName": "spectrum.dat"})


def test_a_sweep_variant_keeps_the_defaults_it_omits(tmp_path: Path) -> None:
    tool = named_tool(
        eval_elast_sweep(project_root=tmp_path), "validate_eval_elast_variants"
    )

    (variant,) = _swept(tool, [{"MaxX": 2.0}])["eval_elast"]

    assert variant["parameters"]["MaxX"] == 2.0
    assert variant["parameters"]["eKind"] == VtEvalPar.VT_EVAL_ANGLE.value
    assert variant["parameters"]["nBins"] == EvalElastParameters().nBins


# ---------------------------------------------------------------------------
# The spectrum
# ---------------------------------------------------------------------------


def test_the_spectrum_is_rendered_by_the_1d_plot_tool(tmp_path: Path) -> None:
    """Written by VITESS's own eval_elast binary (tests/data/README.md).

    Its four columns are a 1D monitor's, so the 1D plot tool renders it once it
    is given the file name -- no plot code of its own.
    """
    data = read_monitor_file(DATA / "eval_elast-angle.dat")
    assert data.kind == "monitor1d"
    assert data.x_label == "scattering angle [deg]"
    assert data.intensity.shape == (18,)
    assert data.x[0] == 5.0 and data.x[-1] == 175.0
    assert data.intensity.sum() > 0

    modules_root = tmp_path / "modules"
    modules_root.mkdir()
    for basename in cli_executables().values():
        (modules_root / basename).write_text("#!/bin/sh\ncat\n", encoding="utf-8")
    settings = ServerSettings(
        project_root=tmp_path / "projects",
        modules_root=modules_root,
        host="127.0.0.1",
        port=9005,
        timeout_seconds=30,
    )
    run_id = str(uuid4())
    run_directory = settings.project_root / THREAD_ID / "outputs" / run_id
    run_directory.mkdir(parents=True)
    shutil.copy(DATA / "eval_elast-angle.dat", run_directory / "eval_elast.dat")

    plot = render_plot(
        settings,
        kind="monitor1d",
        thread_id=THREAD_ID,
        simulation_run_id=run_id,
        filename="eval_elast.dat",
    )

    assert plot.path == "eval_elast.png"
    assert (run_directory / "eval_elast.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_1d_plot_tool_says_it_renders_the_spectrum(tmp_path: Path) -> None:
    tools = build_vitess_tools(VitessGateway(raw_tools()), project_root=tmp_path)

    assert "eval_elast spectrum" in named_tool(tools, "generate_monitor1d_plot").description


# ---------------------------------------------------------------------------
# The guided pipeline
# ---------------------------------------------------------------------------


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


def _optional_results(tmp_path: Path) -> dict[str, Any]:
    """The sample, the screen and eval_elast, each recorded by its own real tool."""
    written: dict[str, Any] = {}
    for tools, module in (
        (sample_tools(project_root=tmp_path), "sample_elasticisotr"),
        (screen_tools(project_root=tmp_path), "screen"),
        (eval_elast_tools(project_root=tmp_path), "eval_elast"),
    ):
        written.update(_validated(named_tool(tools, f"validate_{module}_parameters"), {}))
    return written


def test_the_plan_has_eval_elast_only_when_asked_for_and_then_last() -> None:
    without = plan_simulation.func(runtime=runtime())
    alone = plan_simulation.func(runtime=runtime(), include_optional=["eval_elast"])
    everything = plan_simulation.func(
        runtime=runtime(), include_optional=["eval_elast", "screen", SAMPLE_MODULE]
    )

    assert "eval_elast" not in without.update["planned_execution_order"]
    assert alone.update["planned_execution_order"] == [*BASE, "eval_elast"]
    assert everything.update["planned_execution_order"] == EVERYTHING


def test_a_run_with_every_optional_module_runs_them_in_catalog_order(
    tmp_path: Path, artifact_store: ArtifactStore
) -> None:
    results = {**configured_modules(tmp_path), **_optional_results(tmp_path)}
    calls: list[dict] = []

    command = _run(tmp_path, _planned_state(EVERYTHING, results), calls)

    assert command.update["messages"][0].status == "success"
    assert list(calls[0]["args"]["execution_order"]) == EVERYTHING
    assert calls[0]["args"]["module_results"]["eval_elast"]["cli_parameters"] == (
        parameters_to_arguments(EvalElastParameters())
    )


def test_eval_elast_configured_under_an_earlier_plan_does_not_block_a_run_without_it(
    tmp_path: Path, artifact_store: ArtifactStore
) -> None:
    results = {**configured_modules(tmp_path), **_optional_results(tmp_path)}
    calls: list[dict] = []

    command = _run(tmp_path, _planned_state(list(execution_order()), results), calls)

    assert command.update["messages"][0].status == "success"
    assert list(calls[0]["args"]["execution_order"]) == BASE


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------


def test_the_batch_runs_an_untouched_eval_elast_with_its_defaults_last(
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
        run_names=["with a spectrum"],
        include_optional=["eval_elast", "screen"],
    )
    (entry,) = planned.update["simulation_plan"]
    assert list(entry["modules"]) == [*BASE, "screen", "eval_elast"]
    assert entry["modules"]["eval_elast"]["parameters"] == (
        EvalElastParameters().model_dump(mode="json")
    )

    asyncio.run(
        named_tool(tools, "run_batch_from_matrix").coroutine(
            runtime=runtime(state={"simulation_plan": planned.update["simulation_plan"]})
        )
    )

    assert list(calls[0]["args"]["execution_order"]) == [*BASE, "screen", "eval_elast"]


@pytest.mark.parametrize("with_screen", [False, True])
@pytest.mark.parametrize("path_correction", [False, True])
@pytest.mark.parametrize("tof", [False, True])
def test_guided_tof_requires_a_planned_screen_even_without_path_correction(
    tmp_path: Path, artifact_store: ArtifactStore,
    with_screen: bool, path_correction: bool, tof: bool,
) -> None:
    results = {**configured_modules(tmp_path), **_optional_results(tmp_path)}
    parameters = dict(bTOF=tof, bPathCor=path_correction)
    if tof:
        parameters["TotLength"] = 1100
        if path_correction:
            parameters["DetDist"] = 100
    results.update(_validated(
        named_tool(eval_elast_tools(project_root=tmp_path), "validate_eval_elast_parameters"),
        parameters,
    ))
    planned = [*BASE, *(["screen"] if with_screen else []), "eval_elast"]
    calls: list[dict] = []

    command = _run(tmp_path, _planned_state(planned, results), calls)

    if tof and not with_screen:
        # A screen retained from an earlier plan does not advance this run's clock.
        assert not calls
        assert command.update["messages"][0].status == "error"
        assert "requires screen before eval_elast" in command.update["messages"][0].content
    else:
        assert len(calls) == 1
        assert command.update["messages"][0].status == "success"


@pytest.mark.parametrize("with_screen", [False, True])
@pytest.mark.parametrize("path_correction", [False, True])
def test_sweep_tof_requires_a_screen_before_executing(
    tmp_path: Path, artifact_store: ArtifactStore,
    with_screen: bool, path_correction: bool,
) -> None:
    calls: list[dict] = []

    def payload(call: dict) -> dict:
        calls.append(call)
        return simulation_payload(
            thread_id=call["args"]["thread_id"],
            simulation_run_id=call["args"]["simulation_run_id"],
            modules=list(call["args"]["execution_order"]),
        )

    variants = swept_modules(tmp_path)
    parameters = dict(bTOF=True, bPathCor=path_correction, TotLength=1100)
    if path_correction:
        parameters["DetDist"] = 100
    variants.update(_swept(
        named_tool(eval_elast_sweep(project_root=tmp_path), "validate_eval_elast_variants"),
        [parameters],
    ))
    tools = build_batch_tools(VitessGateway(raw_tools(run_simulation=payload)), project_root=tmp_path)
    planned = named_tool(tools, "write_simulation_matrix").func(
        runtime=runtime(state={"module_variants": variants}),
        combination="paired",
        include_optional=[*(["screen"] if with_screen else []), "eval_elast"],
    )

    command = asyncio.run(named_tool(tools, "run_batch_from_matrix").coroutine(
        runtime=runtime(state={"simulation_plan": planned.update["simulation_plan"]}),
    ))

    if with_screen:
        assert len(calls) == 1
        assert command.update["messages"][0].status == "success"
    else:
        assert not calls
        assert command.update["messages"][0].status == "error"
        assert "requires screen before eval_elast" in command.update["messages"][0].content
