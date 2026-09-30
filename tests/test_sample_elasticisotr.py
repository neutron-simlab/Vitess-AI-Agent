"""sample_elasticisotr: its schema, its tools, and the pipeline it is optional in.

The rules the schema enforces were measured on the VITESS 3.8 binary this
repository builds (6bd0e006), with VITESS's own module test for this sample --
1000 trajectories, GSL seed 1 -- run once from its parameter file and once from
the flags the schema produces. The two outputs, and VITESS's reference output,
are identical. The measured numbers are in the model's validator docstrings.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from langgraph.types import Command
from pydantic import ValidationError

from juena_core.artifacts import ArtifactStore, set_artifact_store_for_tests
from vitess_ai.agents.advanced_mode.tools import _run_one, build_batch_tools, guide_selection
from vitess_ai.agents.specialists.sample_elasticisotr.tools import (
    build_sweep_tools as sample_sweep,
)
from vitess_ai.agents.specialists.sample_elasticisotr.tools import (
    build_tools as sample_tools,
)
from vitess_ai.cli.arguments import parameters_to_arguments
from vitess_ai.mcp.capture_flux_log import read_capture_flux
from vitess_ai.mcp.profile_flatness import read_flatness
from vitess_ai.modules.catalog import SAMPLE_MODULE, execution_order
from vitess_ai.plots import read_monitor_file
from vitess_ai.run import VitessGateway
from vitess_ai.schema import SampleElasticIsotrParameters
from vitess_ai.schema.base import VtSmplGeom
from vitess_ai.schema.module_result import ModuleConfigurationResult
from vitess_ai.schema.simulation_plan import SimulationPlanEntry
from vitess_ai.state import SimulationOrderEvent
from vitess_ai.tools import build_vitess_tools, plan_simulation

from doubles import (
    GRAPH_RUN_ID,
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
WITH_SAMPLE = [
    "readin",
    "guide",
    "sample_elasticisotr",
    "writeout",
    "monitor1d",
    "monitor2d",
    "capture_flux",
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
    """sample_elasticisotr.c:409-487, OwnInit's `case` letters, all 23 of them."""
    flags = {
        field.json_schema_extra["flag"]
        for field in SampleElasticIsotrParameters.model_fields.values()
    }

    assert flags == {f"-{letter}" for letter in "PAcEFefTmGxyzthwoOXYZuU"}
    assert len(SampleElasticIsotrParameters.model_fields) == 23


def test_the_schema_defaults_are_vitess_s_default_sample_given_as_flags() -> None:
    """FILES/sample_files/sampleelastizotr_default.iso, whose full ranges 2 and 2
    the module halves (c:562-563) -- so the flags carry 1 and 1.

    Not the C initialisers (c:53-70): with no shape and no scattering those
    stop VITESS or scatter nothing.
    """
    arguments = parameters_to_arguments(SampleElasticIsotrParameters())

    assert arguments == [
        "-Psampleelastizotr_default.iso", "-A1", "-c-1", "-G1",
        "-E0.0", "-F0.0", "-e1.0", "-f1.0", "-m0.197", "-T0.368",
        "-x50.0", "-y0.0", "-z0.0", "-t3.0", "-h3.0", "-w3.0",
        "-o0.0", "-O0.0", "-X50.0", "-Y0.0", "-Z0.0", "-u0.0", "-U0.0",
    ]


def test_vitess_s_own_module_test_is_the_command_line_that_was_measured() -> None:
    """The hollow vanadium cylinder of tests/module_tests/SampleElasticIsotr-1_rep.

    Its file gives full ranges 90 and 25; the half-ranges 45 and 12.5 are what
    the measured flags run used, and its output was identical to the file run's
    and to VITESS's reference, trajectory for trajectory.
    """
    arguments = parameters_to_arguments(
        SampleElasticIsotrParameters(
            Repetition=2,
            eGeom=VtSmplGeom.VT_HOL_CYL,
            ScatRangeHor=45,
            ScatRangeVert=12.5,
            ScatteringC=0.309,
            AbsorptionC=0.103,
            PosSampleX=5,
            Diameter=2,
            Height=2,
            Width=1.8,
            TranslOutX=0,
        )
    )
    measured = "-A2 -c-1 -E0 -F0 -e45 -f12.5 -T0.309 -m0.103 -x5 -y0 -z0 -o0 -O0 " \
        "-G4 -t2 -h2 -w1.8 -X0 -Y0 -Z0 -u0 -U0"

    ours = _flags(arguments)
    assert ours.pop("-P") == "sampleelastizotr_default.iso"
    assert {flag: float(value) for flag, value in ours.items()} == {
        flag: float(value) for flag, value in _flags(measured.split()).items()
    }


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"eGeom": VtSmplGeom.VT_NO_GEOM}, "eGeom must name a shape"),
        ({"ScatteringC": 0.0}, "ScatteringC must be greater than 0"),
        ({"ScatRangeHor": 0.0}, "ScatRangeHor is a half-range"),
        ({"ScatRangeHor": 180.5}, "ScatRangeHor is a half-range"),
        ({"ScatRangeVert": 0.0}, "ScatRangeVert is a half-range"),
        ({"ScatRangeVert": 90.0}, "ScatRangeVert is a half-range"),
        ({"Width": 0.0}, "needs Width greater than 0"),
        (
            {"eGeom": VtSmplGeom.VT_CYL, "Height": 0.0, "Width": 0.0},
            "needs Height greater than 0",
        ),
        (
            {"eGeom": VtSmplGeom.VT_SPHERE, "Diameter": 0.0, "Height": 0.0, "Width": 0.0},
            "needs Diameter greater than 0",
        ),
        ({"eGeom": VtSmplGeom.VT_HOL_CYL, "Width": 3.0}, "inner diameter"),
        ({"eGeom": VtSmplGeom.VT_HOL_CYL, "Width": 3.5}, "inner diameter"),
        ({"eGeom": VtSmplGeom.VT_CYL, "Width": 0.7}, "Width would be ignored"),
        ({"eGeom": VtSmplGeom.VT_SPHERE, "Height": 1.0}, "Height would be ignored"),
        (
            {"eGeom": VtSmplGeom.VT_SPHERE, "Height": 0.0, "Width": 0.0, "AnglSmplHor": 30},
            "AnglSmplHor would be ignored",
        ),
        ({"Repetition": 0}, "greater than or equal to 1"),
        ({"iColor": -2}, "greater than or equal to -1"),
        ({"AbsorptionC": -0.1}, "greater than or equal to 0"),
        ({"pSmplFileName": ""}, "at least 1 character"),
    ],
)
def test_a_sample_vitess_would_misread_is_refused(
    changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        SampleElasticIsotrParameters(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"ScatRangeHor": 180.0},
        {"ScatRangeVert": 89.9},
        {"AbsorptionC": 0.0},
        # Measured: an inner diameter of 0 is a solid cylinder, not an error.
        {"eGeom": VtSmplGeom.VT_HOL_CYL, "Width": 0.0},
        {"eGeom": VtSmplGeom.VT_HOL_CYL, "Width": 2.9},
        {"eGeom": VtSmplGeom.VT_CYL, "Width": 0.0},
        {"eGeom": VtSmplGeom.VT_SPHERE, "Height": 0.0, "Width": 0.0},
        # The cuboid's sizes left at their defaults are not sizes anyone asked for.
        {"eGeom": VtSmplGeom.VT_CYL},
        {"eGeom": VtSmplGeom.VT_SPHERE},
        {"iColor": 0},
    ],
)
def test_the_neighbouring_valid_sample_is_accepted(changes: dict[str, Any]) -> None:
    SampleElasticIsotrParameters(**changes)


# ---------------------------------------------------------------------------
# The specialist's tools
# ---------------------------------------------------------------------------


def test_the_parameter_file_name_must_be_a_name_not_a_path(tmp_path: Path) -> None:
    tool = named_tool(
        sample_tools(project_root=tmp_path), "validate_sample_elasticisotr_parameters"
    )

    with pytest.raises(AssertionError, match="plain file name"):
        _validated(tool, {"pSmplFileName": "../elsewhere/sample.iso"})
    assert SAMPLE_MODULE in _validated(tool, {"pSmplFileName": "my_sample.iso"})


def test_a_sweep_variant_keeps_vitess_s_default_sample_for_what_it_omits(
    tmp_path: Path,
) -> None:
    tool = named_tool(
        sample_sweep(project_root=tmp_path), "validate_sample_elasticisotr_variants"
    )

    written = _swept(tool, [{"Diameter": 1.0, "Height": 1.0, "Width": 1.0}])
    (variant,) = written[SAMPLE_MODULE]

    defaults = SampleElasticIsotrParameters()
    assert variant["parameters"]["Diameter"] == 1.0
    assert variant["parameters"]["ScatteringC"] == defaults.ScatteringC
    assert variant["parameters"]["PosSampleX"] == defaults.PosSampleX


# ---------------------------------------------------------------------------
# The guided pipeline
# ---------------------------------------------------------------------------


def _sample_result(tmp_path: Path, **changes: Any) -> dict[str, Any]:
    return _validated(
        named_tool(
            sample_tools(project_root=tmp_path), "validate_sample_elasticisotr_parameters"
        ),
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


def _payload_with_readings(calls: list[dict]):
    """A run result carrying both readings, from real capture_flux and monitor1D output."""
    captured = read_capture_flux((DATA / "capture_flux-rectangular.log").read_text("utf-8"))
    flatness = read_flatness(read_monitor_file(DATA / "monitor1D-flatness-pass.dat"))
    assert captured is not None and flatness is not None

    def payload(call: dict) -> dict:
        calls.append(call)
        body = simulation_payload(
            thread_id=call["args"]["thread_id"],
            simulation_run_id=call["args"]["simulation_run_id"],
            modules=list(call["args"]["execution_order"]),
        )
        body["capture_flux"] = captured.model_dump(mode="json")
        body["flatness"] = flatness.model_dump(mode="json")
        return body

    return payload


def _run(tmp_path: Path, state: dict[str, Any], calls: list[dict]) -> Command:
    facade = build_vitess_tools(
        VitessGateway(raw_tools(run_simulation=_payload_with_readings(calls))),
        project_root=tmp_path,
    )
    return asyncio.run(
        named_tool(facade, "run_simulation").coroutine(runtime=runtime(state=state))
    )


def test_the_plan_has_a_sample_only_when_asked_for() -> None:
    without = plan_simulation.func(runtime=runtime())
    with_sample = plan_simulation.func(runtime=runtime(), include_optional=[SAMPLE_MODULE])

    assert without.update["planned_execution_order"] == list(execution_order())
    assert SAMPLE_MODULE not in without.update["planned_execution_order"]
    assert with_sample.update["planned_execution_order"] == WITH_SAMPLE


def test_a_run_with_the_sample_says_its_readings_are_of_scattered_neutrons(
    tmp_path: Path, artifact_store: ArtifactStore
) -> None:
    results = {**configured_modules(tmp_path), **_sample_result(tmp_path)}
    calls: list[dict] = []

    command = _run(tmp_path, _planned_state(WITH_SAMPLE, results), calls)

    (call,) = calls
    assert list(call["args"]["execution_order"]) == WITH_SAMPLE
    assert "-G1" in call["args"]["module_results"][SAMPLE_MODULE]["cli_parameters"]
    text = command.update["messages"][0].text
    assert (
        "Measured after the sample, which scattered every neutron that hit it and "
        "let none through unscattered" in text
    )
    assert "Capture flux from the capture_flux log" in text
    # The flatness verdict judges a beam, and the sample replaced it.
    assert "Horizontal flatness" not in text
    assert "guide exit" not in text


def test_a_colour_filtered_sample_does_not_claim_its_readings_are_all_scattered(
    tmp_path: Path, artifact_store: ArtifactStore
) -> None:
    """With `iColor` set, every other colour passes through unscattered.

    Measured: iColor 1 against VITESS's colour-0 test beam wrote all 1000
    trajectories, none scattered. "Scattered neutrons, not the beam" would
    then describe a beam that went straight through.
    """
    results = {**configured_modules(tmp_path), **_sample_result(tmp_path, iColor=1)}
    calls: list[dict] = []

    command = _run(tmp_path, _planned_state(WITH_SAMPLE, results), calls)

    text = command.update["messages"][0].text
    assert "scattered only colour 1 neutrons; every other colour passed through" in text
    assert "can include unscattered beam as well as scattered neutrons" in text
    assert "let none through unscattered" not in text
    assert "Horizontal flatness" not in text


def test_a_sample_configured_under_an_earlier_plan_does_not_block_a_run_without_it(
    tmp_path: Path, artifact_store: ArtifactStore
) -> None:
    """Stored configurations are never removed, so the old sample is still there."""
    results = {**configured_modules(tmp_path), **_sample_result(tmp_path)}
    calls: list[dict] = []

    command = _run(tmp_path, _planned_state(list(execution_order()), results), calls)

    (call,) = calls
    assert list(call["args"]["execution_order"]) == list(execution_order())
    assert SAMPLE_MODULE not in call["args"]["module_results"]
    assert "Measured at the guide exit" in command.update["messages"][0].text


def test_a_planned_sample_that_was_never_configured_is_refused(
    tmp_path: Path, artifact_store: ArtifactStore
) -> None:
    calls: list[dict] = []

    command = _run(
        tmp_path, _planned_state(WITH_SAMPLE, configured_modules(tmp_path)), calls
    )

    assert calls == []
    assert (
        "These planned modules have no validated configuration: sample_elasticisotr"
        in command.update["messages"][0].text
    )


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------


def _matrix(tmp_path: Path, variants: dict[str, Any], **arguments: Any) -> Command:
    tools = build_batch_tools(VitessGateway(raw_tools()), project_root=tmp_path)
    return named_tool(tools, "write_simulation_matrix").func(
        runtime=runtime(state={"module_variants": variants}),
        combination="paired",
        run_names=None,
        **arguments,
    )


def test_a_sweep_with_an_untouched_sample_runs_vitess_s_default_sample(
    tmp_path: Path, artifact_store: ArtifactStore
) -> None:
    command = _matrix(tmp_path, swept_modules(tmp_path), include_optional=[SAMPLE_MODULE])

    for entry in command.update["simulation_plan"]:
        assert list(entry["modules"]) == WITH_SAMPLE
        assert entry["modules"][SAMPLE_MODULE]["parameters"] == SampleElasticIsotrParameters().model_dump(mode="json")


def test_sample_variants_are_left_out_of_a_sweep_without_the_sample(
    tmp_path: Path, artifact_store: ArtifactStore
) -> None:
    variants = swept_modules(tmp_path)
    variants.update(
        _swept(
            named_tool(
                sample_sweep(project_root=tmp_path), "validate_sample_elasticisotr_variants"
            ),
            [{"Diameter": 1.0, "Height": 1.0, "Width": 1.0}],
        )
    )

    without = _matrix(tmp_path, variants)
    with_sample = _matrix(tmp_path, variants, include_optional=[SAMPLE_MODULE])

    assert all(
        SAMPLE_MODULE not in entry["modules"] for entry in without.update["simulation_plan"]
    )
    (entry,) = with_sample.update["simulation_plan"]
    assert entry["modules"][SAMPLE_MODULE]["parameters"]["Diameter"] == 1.0


def test_a_sweep_run_with_the_sample_runs_it_after_the_guide(
    tmp_path: Path, artifact_store: ArtifactStore
) -> None:
    results = {**configured_modules(tmp_path), **_sample_result(tmp_path)}
    entry = SimulationPlanEntry(
        run_name="with sample",
        simulation_run_id=uuid4(),
        modules={
            module: ModuleConfigurationResult.model_validate(result)
            for module, result in results.items()
        },
    )
    calls: list[dict] = []

    line, _events, reference, result = asyncio.run(
        _run_one(
            VitessGateway(raw_tools(run_simulation=_payload_with_readings(calls))),
            entry,
            planned=execution_order(include_optional=[SAMPLE_MODULE]),
            project_root=tmp_path,
            user_id="user-a",
            thread_id=THREAD_ID,
            graph_run_id=GRAPH_RUN_ID,
        )
    )

    assert reference is not None
    assert list(calls[0]["args"]["execution_order"]) == WITH_SAMPLE
    assert "Measured after the sample" in line
    assert "Horizontal flatness" not in line
    # Its monitor still wrote a flatness reading; no guide is ranked by it.
    assert result is not None and result.flatness is not None
    assert guide_selection([(entry, result)]) is None


def test_the_batch_runs_the_sample_the_matrix_recorded_right_after_the_guide(
    tmp_path: Path, artifact_store: ArtifactStore
) -> None:
    """Through both real sweep tools: each entry's pipeline comes from the entry."""
    calls: list[dict] = []
    tools = build_batch_tools(
        VitessGateway(raw_tools(run_simulation=_payload_with_readings(calls))),
        project_root=tmp_path,
    )
    planned = named_tool(tools, "write_simulation_matrix").func(
        runtime=runtime(state={"module_variants": swept_modules(tmp_path)}),
        combination="paired",
        run_names=["with sample"],
        include_optional=[SAMPLE_MODULE],
    )

    swept = asyncio.run(
        named_tool(tools, "run_batch_from_matrix").coroutine(
            runtime=runtime(state={"simulation_plan": planned.update["simulation_plan"]})
        )
    )

    (call,) = calls
    assert list(call["args"]["execution_order"]) == WITH_SAMPLE
    text = swept.update["messages"][0].text
    assert "Sweep complete: 1 of 1 run(s) succeeded." in text
    assert "Measured after the sample" in text
    assert "Guide selection" not in text
