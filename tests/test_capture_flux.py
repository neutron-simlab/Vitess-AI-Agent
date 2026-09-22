"""capture_flux: its schema, its log, and how its number reaches the chat.

The log fixtures are real VITESS 3.8 output (see `tests/data/README.md`), so the
reader is tested against what capture_flux prints rather than what it was
remembered to print.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from langgraph.types import Command
from pydantic import ValidationError

from juena_core.artifacts import ArtifactStore, set_artifact_store_for_tests
from vitess_ai.agents.advanced_mode.tools import _run_one
from vitess_ai.cli.arguments import parameters_to_arguments
from vitess_ai.mcp.capture_flux_log import read_capture_flux
from vitess_ai.mcp.server import run_pipeline
from vitess_ai.mcp.settings import ServerSettings
from vitess_ai.modules.catalog import cli_executables, execution_order
from vitess_ai.run import VitessGateway
from vitess_ai.schema import CaptureFluxParameters
from vitess_ai.schema.base import VtWindowType
from vitess_ai.schema.module_result import ModuleConfigurationResult
from vitess_ai.schema.simulation_plan import SimulationPlanEntry
from vitess_ai.state import SimulationOrderEvent
from vitess_ai.tools import build_vitess_tools

from doubles import (
    GRAPH_RUN_ID,
    SIMULATION_RUN_ID,
    THREAD_ID,
    configured_modules,
    named_tool,
    raw_tools,
    runtime,
    simulation_payload,
)

DATA = Path(__file__).parent / "data"
DEFAULT_LOG = DATA / "capture_flux-default.log"
RECTANGULAR_LOG = DATA / "capture_flux-rectangular.log"


@pytest.fixture
def artifact_store(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts", tmp_path / "audit.jsonl")
    set_artifact_store_for_tests(store)
    yield store
    set_artifact_store_for_tests(None)


# ---------------------------------------------------------------------------
# The schema
# ---------------------------------------------------------------------------


def test_the_defaults_are_capture_flux_c_defaults() -> None:
    """capture_flux.c:38-48: 1.798 A, no foil, every bound 0."""
    defaults = CaptureFluxParameters()

    assert defaults.ReferenceWavelength == 1.798
    assert defaults.WindowType == VtWindowType.NO_RESTRICTIONS
    assert parameters_to_arguments(defaults)[:2] == ["-R1.798", "-t0"]


def test_a_rectangular_foil_is_the_command_line_vitess_tests_itself_with() -> None:
    """VITESS's own module test runs `-R1.798 -t2 -w-3 -W3 -h-3 -H3`.

    The schema spells numbers as floats and also passes the fields the shape
    ignores, at 0 -- which are capture_flux.c's own defaults.
    """
    arguments = parameters_to_arguments(
        CaptureFluxParameters(
            WindowType=VtWindowType.RECTANGULAR,
            widthmin=-3,
            widthmax=3,
            heightmin=-3,
            heightmax=3,
        )
    )
    values = {argument[:2]: float(argument[2:]) for argument in arguments}
    vitess_test = {"-R": 1.798, "-t": 2, "-w": -3, "-W": 3, "-h": -3, "-H": 3}

    assert {flag: values[flag] for flag in vitess_test} == vitess_test
    assert all(value == 0.0 for flag, value in values.items() if flag not in vitess_test)


@pytest.mark.parametrize(
    "parameters",
    [
        {"WindowType": 1, "winradius": 0.5},
        {"WindowType": 1, "winradius": 0.5, "ywincenter": 1.0, "zwincenter": -1.0},
        {"WindowType": 2, "widthmin": -0.5, "widthmax": 0.5, "heightmin": -0.5, "heightmax": 0.5},
        {"lambdamin": 1.0, "lambdamax": 5.0},
        {"ReferenceWavelength": 0.0},
    ],
)
def test_a_complete_foil_or_window_is_accepted(parameters: dict) -> None:
    CaptureFluxParameters(**parameters)


@pytest.mark.parametrize(
    ("parameters", "message"),
    [
        ({"WindowType": 1}, "winradius greater than 0"),
        (
            {"WindowType": 2, "widthmin": 1, "widthmax": -1, "heightmin": -1, "heightmax": 1},
            "widthmin smaller than widthmax",
        ),
        (
            {"WindowType": 2, "widthmin": -1, "widthmax": 1, "heightmin": 1, "heightmax": 1},
            "heightmin smaller than heightmax",
        ),
        ({"winradius": 2.0}, "winradius would be ignored with WindowType NO_RESTRICTIONS"),
        (
            {"WindowType": 1, "winradius": 1.0, "widthmax": 2.0},
            "widthmax would be ignored with WindowType CIRCULAR",
        ),
        (
            {"WindowType": 2, "widthmin": -1, "widthmax": 1, "heightmin": -1, "heightmax": 1,
             "winradius": 1.0},
            "winradius would be ignored with WindowType RECTANGULAR",
        ),
        ({"lambdamin": 2.0}, "both be set or both be 0"),
        ({"lambdamax": 2.0}, "both be set or both be 0"),
        ({"lambdamin": 5.0, "lambdamax": 2.0}, "lambdamin must be smaller than lambdamax"),
        ({"ReferenceWavelength": -1.0}, "greater than or equal to 0"),
    ],
)
def test_a_foil_or_window_capture_flux_would_misread_is_refused(
    parameters: dict, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        CaptureFluxParameters(**parameters)


# ---------------------------------------------------------------------------
# The log
# ---------------------------------------------------------------------------


def test_the_reader_takes_the_numbers_capture_flux_printed() -> None:
    reading = read_capture_flux(RECTANGULAR_LOG.read_text(encoding="utf-8"))

    assert reading is not None
    assert reading.reference_wavelength == 1.798
    assert reading.captured_intensity == 5.991e10
    assert reading.captured_intensity_error == 9.676e8
    assert reading.trajectories == 4401
    assert reading.capture_flux == 1.664e9
    assert reading.capture_flux_error == 2.688e7


def test_with_no_foil_the_capture_flux_is_the_captured_intensity() -> None:
    """The area is taken as 1 cm^2 (capture_flux.c:51), and the log shows it."""
    reading = read_capture_flux(DEFAULT_LOG.read_text(encoding="utf-8"))

    assert reading is not None
    assert reading.trajectories == 10000
    assert reading.capture_flux == reading.captured_intensity == 2.485e11


def test_a_log_without_a_capture_flux_result_has_no_reading() -> None:
    """The source module's log alone: what a run looks like if capture_flux died."""
    source_only = DEFAULT_LOG.read_text(encoding="utf-8").split("module CaptureFlux")[0]

    assert read_capture_flux(source_only) is None


# ---------------------------------------------------------------------------
# From the server to the chat
# ---------------------------------------------------------------------------


def _settings(tmp_path: Path) -> ServerSettings:
    """Stand-ins that pass the beam on; capture_flux's also writes its real log.

    VITESS gives every module `--L<log file>`; the stand-in copies the fixture
    there, so the server reads genuine capture_flux output through the real
    pipeline and the real log concatenation.
    """
    modules_root = tmp_path / "modules"
    modules_root.mkdir()
    for basename in cli_executables().values():
        binary = modules_root / basename
        binary.write_text("#!/bin/sh\ncat\n", encoding="utf-8")
        binary.chmod(0o755)
    (modules_root / "capture_flux").write_text(
        "#!/bin/sh\n"
        'for argument in "$@"; do\n'
        f'  case "$argument" in --L*) cp "{RECTANGULAR_LOG}" "${{argument#--L}}" ;; esac\n'
        "done\n"
        "cat\n",
        encoding="utf-8",
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


def test_the_server_puts_the_reading_on_the_run_result(tmp_path: Path) -> None:
    result = run_pipeline(
        _settings(tmp_path),
        thread_id=THREAD_ID,
        simulation_run_id=SIMULATION_RUN_ID,
        module_results={name: {"cli_parameters": ["-a1"]} for name in execution_order()},
        execution_order=list(execution_order()),
    )

    assert result.success is True
    assert result.capture_flux == read_capture_flux(
        RECTANGULAR_LOG.read_text(encoding="utf-8")
    )


def _reading_payload(call: dict) -> dict:
    payload = simulation_payload(
        thread_id=call["args"]["thread_id"],
        simulation_run_id=call["args"]["simulation_run_id"],
        modules=list(call["args"]["execution_order"]),
    )
    reading = read_capture_flux(RECTANGULAR_LOG.read_text(encoding="utf-8"))
    payload["capture_flux"] = reading.model_dump(mode="json")
    return payload


EXPECTED_SENTENCE = (
    "Capture flux from the capture_flux log: 1.664e+09 ± 2.688e+07 n/(s·cm²); "
    "captured intensity 5.991e+10 ± 9.676e+08 n/s from 4401 trajectories; "
    "reference wavelength 1.798 Å."
)


def test_run_simulation_tells_the_supervisor_the_capture_flux(
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
        VitessGateway(raw_tools(run_simulation=_reading_payload)), project_root=tmp_path
    )

    command = asyncio.run(
        named_tool(facade, "run_simulation").coroutine(runtime=runtime(state=state))
    )

    assert isinstance(command, Command)
    message = command.update["messages"][0]
    assert message.status == "success"
    assert message.text.endswith(EXPECTED_SENTENCE)


def test_a_sweep_run_line_carries_the_capture_flux(
    tmp_path: Path, artifact_store: ArtifactStore
) -> None:
    entry = SimulationPlanEntry(
        run_name="baseline",
        simulation_run_id=uuid4(),
        modules={
            module: ModuleConfigurationResult.model_validate(result)
            for module, result in configured_modules(tmp_path).items()
        },
    )

    line, _events, reference = asyncio.run(
        _run_one(
            VitessGateway(raw_tools(run_simulation=_reading_payload)),
            entry,
            planned=execution_order(),
            project_root=tmp_path,
            user_id="user-a",
            thread_id=THREAD_ID,
            graph_run_id=GRAPH_RUN_ID,
        )
    )

    assert reference is not None
    assert line.startswith("- baseline: completed (")
    assert line.endswith(f"). {EXPECTED_SENTENCE}")
