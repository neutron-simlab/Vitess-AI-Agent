"""Beam flatness: the verdict, how it reaches the chat, and the sweep's choice.

Every monitor file here is real VITESS 3.8 output (see `tests/data/README.md`).
A fixture written to suit the reader would agree with whatever the reader
assumes, and the assumptions -- the axis label, the bin centres, the error
column -- are exactly what these tests have to check.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from langgraph.types import Command

from juena_core.artifacts import ArtifactStore, set_artifact_store_for_tests
from vitess_ai.agents.advanced_mode.tools import build_batch_tools
from vitess_ai.agents.specialists.guide.tools import build_sweep_tools as guide_sweep
from vitess_ai.cli.arguments import parameters_to_arguments
from vitess_ai.mcp.capture_flux_log import read_capture_flux
from vitess_ai.mcp.payloads import FlatnessReading, SimulationResult
from vitess_ai.mcp.profile_flatness import read_flatness
from vitess_ai.mcp.server import run_pipeline
from vitess_ai.mcp.settings import ServerSettings
from vitess_ai.modules.catalog import cli_executables, execution_order
from vitess_ai.plots import read_monitor_file
from vitess_ai.run import VitessGateway
from vitess_ai.schema import GuideParameters, Monitor1DParameters
from vitess_ai.schema.base import VtGdeShape, VtMonPar
from vitess_ai.state import SimulationOrderEvent
from vitess_ai.tools import (
    build_vitess_tools,
    capture_flux_summary,
    flatness_summary,
    guide_position,
)

from doubles import (
    SIMULATION_RUN_ID,
    THREAD_ID,
    _swept,
    configured_modules,
    named_tool,
    raw_tools,
    runtime,
    simulation_payload,
    swept_modules,
)

DATA = Path(__file__).parent / "data"
CAPTURE_FLUX_LOG = DATA / "capture_flux-rectangular.log"


def _fixture(name: str) -> Path:
    return DATA / f"monitor1D-flatness-{name}.dat"


def _reading(name: str) -> FlatnessReading:
    reading = read_flatness(read_monitor_file(_fixture(name)))
    assert reading is not None
    return reading


@pytest.fixture
def artifact_store(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts", tmp_path / "audit.jsonl")
    set_artifact_store_for_tests(store)
    yield store
    set_artifact_store_for_tests(None)


# ---------------------------------------------------------------------------
# The verdict
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fixture", "verdict"),
    [
        ("pass", "pass"),
        ("half-edges", "fail"),
        ("empty-edges", "fail"),
        # The same flat beam as "pass", with 10^4 trajectories instead of 10^6:
        # noise, not the beam, is what keeps it from passing, so it must not fail.
        ("inconclusive", "inconclusive"),
        ("100-bins", "wrong_binning"),
    ],
)
def test_each_real_profile_gets_its_verdict(fixture: str, verdict: str) -> None:
    assert _reading(fixture).verdict == verdict


def test_half_filled_edge_bins_fail_on_their_deviation() -> None:
    reading = _reading("half-edges")

    assert reading.empty_bins == 0
    assert abs(reading.worst_position_cm) == pytest.approx(0.45)
    assert reading.worst_deviation < -0.4


def test_a_hole_in_the_beam_fails_and_is_counted() -> None:
    reading = _reading("empty-edges")

    assert reading.verdict == "fail"
    assert reading.empty_bins == 4


def test_bins_other_than_the_criterion_s_are_not_judged() -> None:
    reading = _reading("100-bins")

    assert reading.bin_width_cm == pytest.approx(0.04)
    assert reading.worst_deviation is None
    assert reading.median_relative_error is None


@pytest.mark.parametrize("fixture", ["monitor1D.dat", "monitor2D-F1.dat"])
def test_a_monitor_not_recording_horizontal_position_has_no_reading(fixture: str) -> None:
    assert read_flatness(read_monitor_file(DATA / fixture)) is None


# ---------------------------------------------------------------------------
# On the server
# ---------------------------------------------------------------------------


def _settings(tmp_path: Path, *, monitor_file: Path | None, fail_last: bool = False) -> ServerSettings:
    """Stand-ins that pass the beam on; monitor1D's writes a real file to its ``-O``.

    The server runs each module in the run directory, as VITESS is run, so a
    relative ``-O`` lands where the real monitor1D would write it.
    """
    modules_root = tmp_path / "modules"
    modules_root.mkdir()
    for basename in cli_executables().values():
        binary = modules_root / basename
        binary.write_text("#!/bin/sh\ncat\n", encoding="utf-8")
        binary.chmod(0o755)
    if monitor_file is not None:
        (modules_root / cli_executables()["monitor1d"]).write_text(
            "#!/bin/sh\n"
            'for argument in "$@"; do\n'
            f'  case "$argument" in -O*) cp "{monitor_file}" "${{argument#-O}}" ;; esac\n'
            "done\n"
            "cat\n",
            encoding="utf-8",
        )
    if fail_last:
        (modules_root / cli_executables()["capture_flux"]).write_text(
            "#!/bin/sh\ncat >/dev/null\nexit 1\n", encoding="utf-8"
        )
    project_root = tmp_path / "projects"
    project_root.mkdir()
    return ServerSettings(
        project_root=project_root,
        modules_root=modules_root,
        host="127.0.0.1",
        port=9005,
        timeout_seconds=30,
    )


def _module_results() -> dict[str, dict[str, Any]]:
    """monitor1D's arguments from its own schema, so ``-O`` is spelled as in a real run."""
    results: dict[str, dict[str, Any]] = {
        name: {"cli_parameters": ["-a1"]} for name in execution_order()
    }
    results["monitor1d"] = {
        "cli_parameters": parameters_to_arguments(
            Monitor1DParameters(eParX=VtMonPar.POS_Y, xMin=-2.0, xMax=2.0, nBinsX=40)
        )
    }
    return results


def _run(settings: ServerSettings) -> SimulationResult:
    return run_pipeline(
        settings,
        thread_id=THREAD_ID,
        simulation_run_id=SIMULATION_RUN_ID,
        module_results=_module_results(),
        execution_order=list(execution_order()),
    )


def test_the_server_puts_the_flatness_on_the_run_result(tmp_path: Path) -> None:
    result = _run(_settings(tmp_path, monitor_file=_fixture("pass")))

    assert result.success is True
    assert result.flatness == _reading("pass")


def test_a_monitor_that_wrote_nothing_leaves_a_successful_run_without_a_reading(
    tmp_path: Path,
) -> None:
    result = _run(_settings(tmp_path, monitor_file=None))

    assert result.success is True
    assert result.flatness is None


def test_a_failed_run_is_not_judged_even_if_its_monitor_wrote(tmp_path: Path) -> None:
    result = _run(_settings(tmp_path, monitor_file=_fixture("pass"), fail_last=True))

    assert result.success is False
    assert result.flatness is None


# ---------------------------------------------------------------------------
# In the chat
# ---------------------------------------------------------------------------


def _summary(fixture: str) -> str | None:
    return flatness_summary(
        SimulationResult(
            success=True,
            timed_out=False,
            thread_id=THREAD_ID,
            simulation_run_id=SIMULATION_RUN_ID,
            message="Pipeline completed",
            flatness=_reading(fixture),
        )
    )


@pytest.mark.parametrize(
    ("fixture", "sentence"),
    [
        (
            "pass",
            "Horizontal flatness over the central 1 cm in 0.1 cm bins (every bin "
            "within 10% of the mean, allowing 2σ): PASS; largest deviation -0.9% "
            "at y = +0.35 cm; median bin error 0.4%.",
        ),
        (
            "empty-edges",
            "Horizontal flatness over the central 1 cm in 0.1 cm bins (every bin "
            "within 10% of the mean, allowing 2σ): FAIL; 4 empty bin(s) in the "
            "window; largest deviation -100.0% at y = -0.45 cm; median bin error 0.2%.",
        ),
        (
            "inconclusive",
            "Horizontal flatness over the central 1 cm in 0.1 cm bins (every bin "
            "within 10% of the mean, allowing 2σ): INCONCLUSIVE (the statistical "
            "errors are too large to decide; run more trajectories); largest "
            "deviation -6.3% at y = -0.25 cm; median bin error 4.5%.",
        ),
        (
            "100-bins",
            "Horizontal flatness not judged: the 1D monitor's bins are 0.04 cm wide "
            "and do not tile the central 1 cm in 0.1 cm bins; record pos_y from -2 "
            "to 2 cm in 40 bins.",
        ),
    ],
)
def test_the_verdict_reads_as_one_sentence(fixture: str, sentence: str) -> None:
    assert _summary(fixture) == sentence


def test_the_position_is_the_guide_length_from_its_entrance() -> None:
    guide = GuideParameters(nPieces=20, piecelength=50.0).model_dump(mode="json")

    assert guide_position(guide) == "at the guide exit, 10.00 m from the guide entrance"


def test_a_guide_from_a_shape_file_does_not_guess_its_length() -> None:
    guide = GuideParameters(
        eGuideShapeY=VtGdeShape.VT_FROM_FILE, ShapeFileName="shape.dat"
    ).model_dump(mode="json")

    assert guide_position(guide) == (
        "at the guide exit (guide length set by the shape file 'shape.dat')"
    )


def _payload_with(fixture: str, capture_flux: float | None = None):
    captured = read_capture_flux(CAPTURE_FLUX_LOG.read_text(encoding="utf-8"))
    assert captured is not None
    if capture_flux is not None:
        captured = captured.model_copy(update={"capture_flux": capture_flux})

    def payload(call: dict) -> dict:
        body = simulation_payload(
            thread_id=call["args"]["thread_id"],
            simulation_run_id=call["args"]["simulation_run_id"],
            modules=list(call["args"]["execution_order"]),
        )
        body["capture_flux"] = captured.model_dump(mode="json")
        body["flatness"] = _reading(fixture).model_dump(mode="json")
        return body

    return payload


def test_run_simulation_says_where_it_measured_and_how_flat(
    tmp_path: Path, artifact_store: ArtifactStore
) -> None:
    state = {
        "planned_execution_order": list(execution_order()),
        "simulation_order_events": [
            SimulationOrderEvent(kind="plan", execution_order=execution_order()).model_dump(
                mode="json"
            ),
            *[
                SimulationOrderEvent(kind="configured", module=module).model_dump(mode="json")
                for module in execution_order()
            ],
        ],
        "module_results": configured_modules(tmp_path),
    }
    facade = build_vitess_tools(
        VitessGateway(raw_tools(run_simulation=_payload_with("pass"))),
        project_root=tmp_path,
    )

    command = asyncio.run(
        named_tool(facade, "run_simulation").coroutine(runtime=runtime(state=state))
    )

    assert isinstance(command, Command)
    message = command.update["messages"][0]
    result = SimulationResult(
        success=True,
        timed_out=False,
        thread_id=THREAD_ID,
        simulation_run_id=SIMULATION_RUN_ID,
        message="Pipeline completed",
        capture_flux=read_capture_flux(CAPTURE_FLUX_LOG.read_text(encoding="utf-8")),
        flatness=_reading("pass"),
    )
    # The specialist's default guide: twenty 50 cm pieces.
    assert message.text.endswith(
        "Measured at the guide exit, 10.00 m from the guide entrance. "
        f"{capture_flux_summary(result)} {flatness_summary(result)}"
    )


# ---------------------------------------------------------------------------
# The sweep's choice
# ---------------------------------------------------------------------------


def _run_sweep(tmp_path: Path, runs: list[tuple[str, int, str, float]]) -> str:
    """Plan and run a sweep over guide lengths, one (name, pieces, fixture, flux) per run.

    The guide variants are recorded by the real guide sweep tool: 50 cm pieces,
    so 16 pieces is an 8 m guide.
    """
    variants = swept_modules(tmp_path)
    variants.update(
        _swept(
            named_tool(
                guide_sweep(project_root=tmp_path, gateway=None),
                "validate_guide_variants",
            ),
            [{"nPieces": pieces} for _, pieces, _, _ in runs],
            thread_id=THREAD_ID,
        )
    )
    answers = iter(_payload_with(fixture, flux) for _, _, fixture, flux in runs)
    tools = build_batch_tools(
        VitessGateway(raw_tools(run_simulation=lambda call: next(answers)(call))),
        project_root=tmp_path,
    )
    planned = named_tool(tools, "write_simulation_matrix").func(
        runtime=runtime(state={"module_variants": variants}),
        combination="paired",
        run_names=[name for name, _, _, _ in runs],
    )
    swept = asyncio.run(
        named_tool(tools, "run_batch_from_matrix").coroutine(
            runtime=runtime(state={"simulation_plan": planned.update["simulation_plan"]})
        )
    )
    return swept.update["messages"][0].text


def test_a_guide_sweep_ends_with_the_flat_runs_ranked_by_capture_flux(
    tmp_path: Path, artifact_store: ArtifactStore
) -> None:
    text = _run_sweep(
        tmp_path,
        [
            ("guide-8m", 16, "pass", 1.5e9),
            ("guide-10m", 20, "pass", 2.5e9),
            # The highest flux of all, and still not the choice: it is not flat.
            ("guide-12m", 24, "half-edges", 3.0e9),
            ("guide-14m", 28, "inconclusive", 4.0e9),
        ],
    )

    assert text.endswith(
        "Guide selection: flat runs ranked by capture flux, highest first.\n"
        "1. guide-10m: 2.500e+09 n/(s·cm²), at the guide exit, 10.00 m from the "
        "guide entrance\n"
        "2. guide-8m: 1.500e+09 n/(s·cm²), at the guide exit, 8.00 m from the "
        "guide entrance\n"
        "Not judged: guide-14m (inconclusive).\n"
        "Not flat: guide-12m."
    )
    # Every run's own line states its own guide length.
    for metres in (8, 10, 12, 14):
        assert (
            f"Measured at the guide exit, {metres}.00 m from the guide entrance." in text
        )


def test_a_sweep_without_a_flatness_reading_has_no_ranking(
    tmp_path: Path, artifact_store: ArtifactStore
) -> None:
    tools = build_batch_tools(VitessGateway(raw_tools()), project_root=tmp_path)
    planned = named_tool(tools, "write_simulation_matrix").func(
        runtime=runtime(state={"module_variants": swept_modules(tmp_path)}),
        combination="paired",
        run_names=None,
    )
    swept = asyncio.run(
        named_tool(tools, "run_batch_from_matrix").coroutine(
            runtime=runtime(state={"simulation_plan": planned.update["simulation_plan"]})
        )
    )

    assert "Guide selection" not in swept.update["messages"][0].text
