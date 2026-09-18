"""CP4: a validated configuration reaches the command builder without a model."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Any

import pytest
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command
from pydantic import BaseModel, Field, ValidationError

from juena_core.agents.ask_user import build_ask_user_tool
from juena_core.server.streaming.processor import StreamEventProcessor
from juena_core.agents.specialist_outcome import (
    SpecialistOutcomeMiddleware,
    outcome_verified,
)
from juena_core.artifacts import ArtifactStore, set_artifact_store_for_tests
from juena_core.schema.agents import SpecialistReport
from vitess_ai.agents.delegation import (
    ModuleSpecialistDelegate,
    with_module_delegation_boundary,
)
from vitess_ai.agents.specialists import compile_module_specialists
from vitess_ai.agents.specialists.guide.tools import build_tools as guide_tools
from vitess_ai.agents.specialists.module_specialist import (
    FILESYSTEM_TOOLS,
    GuidedAskUserMiddleware,
    ModuleReportMiddleware,
    build_module_prompt,
    omitted_file_value,
)
from vitess_ai.agents.specialists.monitor1d.tools import build_tools as monitor1d_tools
from vitess_ai.agents.specialists.monitor2d.tools import build_tools as monitor2d_tools
from vitess_ai.agents.specialists.readin.tools import build_tools as readin_tools
from vitess_ai.agents.specialists.writeout.tools import build_tools as writeout_tools
from vitess_ai.cli.arguments import (
    ParameterConversionError,
    parameters_to_arguments,
)
from vitess_ai.modules.catalog import cli_executables, execution_order, upload_modules
from vitess_ai.modules.parameters import PARAMETER_MODELS, parameter_model
from vitess_ai.retrieval import SPECIALIST_RAG_TOOLS, specialist_rag_tools
from vitess_ai.schema import (
    GuideParameters,
    Monitor1DParameters,
    Monitor2DParameters,
    ReadInParameters,
    WriteoutParameters,
)
from vitess_ai.schema.module_result import (
    ModuleConfigurationResult,
    module_schema_version,
)
from vitess_ai.state import VitessBridgeState, merge_module_results

from doubles import (
    THREAD_ID,
    configured_modules,
    named_tool,
    runtime,
    stage_uploads,
    swept_modules,
)

OTHER_THREAD_ID = "44444444-4444-4444-8444-444444444444"


# ---------------------------------------------------------------------------
# The two module-name-keyed tables, compared
# ---------------------------------------------------------------------------


def test_every_executable_module_has_exactly_one_parameter_model() -> None:
    """Two tables keyed by module name drift when nobody compares them.

    The catalog says which modules run a binary; this says which model
    validates their parameters. `run_simulation` needs both to agree for every
    module it is about to execute.
    """
    assert tuple(PARAMETER_MODELS) == execution_order()


def test_asking_for_a_model_that_is_not_there_raises() -> None:
    with pytest.raises(KeyError, match="No VITESS parameter model for 'monitor3d'"):
        parameter_model("monitor3d")


# ---------------------------------------------------------------------------
# Parameters to arguments
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module", execution_order())
def test_every_model_converts_to_flag_value_arguments(module: str) -> None:
    """One token per argument, each a flag with its value attached.

    `generate_cli_command` (CP1) rejects anything else, and it rejects it at
    execution time -- by which point the specialist has gone.
    """
    model = parameter_model(module)
    defaults = model() if module != "readin" else model(
        sInputFileName=["/data/projects/x/uploads/readin/beam.dat"],
        Weight=[1.0],
        sInstrInfIn=None,
    )

    arguments = parameters_to_arguments(defaults)

    assert arguments
    for argument in arguments:
        assert argument.startswith("-"), argument
        assert " " not in argument, argument
        assert len(argument.lstrip("-")) > 1, f"{argument} carries a flag but no value"


def test_a_field_with_no_flag_refuses_to_convert_rather_than_dropping_it() -> None:
    """The monitors' converters skipped such a field, with a comment saying why.

    What that produced is a parameter the user asked for, absent from the
    command, in a simulation that completes -- CP1's defect in another place.
    """

    class _Unflagged(BaseModel):
        nBins: Annotated[int, Field(default=10, json_schema_extra={"flag": "-x"})]
        forgotten: Annotated[float, Field(default=1.5)]

    with pytest.raises(ParameterConversionError, match="declares no CLI flag"):
        parameters_to_arguments(_Unflagged())


def test_nested_shared_flags_become_one_bit_string_and_distinct_ones_do_not() -> None:
    """Writeout holds both nested shapes, so both rules are exercised at once."""
    arguments = parameters_to_arguments(WriteoutParameters(sOutFileName="output.dat"))

    assert "-c111111111" in arguments
    assert "-l-1.0" in arguments
    assert "-L10000000000.0" in arguments


def test_more_list_values_than_flags_is_refused() -> None:
    """Truncating would read fewer input files than the user asked for."""

    class _TwoSlots(BaseModel):
        files: Annotated[
            list[str], Field(default_factory=list, json_schema_extra={"flag": "-A -B"})
        ]

    with pytest.raises(ParameterConversionError, match="only 2 flags"):
        parameters_to_arguments(_TwoSlots(files=["a", "b", "c"]))


def test_an_argument_with_a_nul_byte_is_refused_before_process_execution() -> None:
    class _StringArgument(BaseModel):
        value: Annotated[str, Field(json_schema_extra={"flag": "-x"})]

    with pytest.raises(ParameterConversionError, match="NUL byte"):
        parameters_to_arguments(_StringArgument(value="bad\x00value"))


def test_an_empty_shape_filename_omits_its_flag_entirely() -> None:
    """Empty means "no guide file", and a bare `-S` would eat the next argument."""
    arguments = parameters_to_arguments(GuideParameters())

    assert not any(argument.startswith("-S") for argument in arguments)


def test_a_staged_shape_filename_is_emitted() -> None:
    arguments = parameters_to_arguments(GuideParameters(ShapeFileName="/data/g.dat"))

    assert "-S/data/g.dat" in arguments


# ---------------------------------------------------------------------------
# The validation tools, which are the only writers of module_results
# ---------------------------------------------------------------------------


def _validate(tool: Any, parameters: Any, **kwargs: Any) -> Command:
    return tool.func(runtime=runtime(**kwargs), parameters=parameters)


def test_a_valid_object_is_recorded_as_a_typed_configuration(tmp_path: Path) -> None:
    tool = named_tool(
        monitor1d_tools(project_root=tmp_path), "validate_monitor1d_parameters"
    )

    command = _validate(tool, {})

    stored = command.update["module_results"]["monitor1d"]
    result = ModuleConfigurationResult.model_validate(stored)
    assert result.module == "monitor1d"
    assert result.schema_version == module_schema_version(parameter_model("monitor1d"))
    assert result.parameters["fMonitorFilename"] == "monitor1D.dat"
    assert command.update["messages"][0].status == "success"


def test_an_invalid_object_records_nothing_at_all(tmp_path: Path) -> None:
    """The first-generation tool returned `{"validation_status": False, ...}`.

    That payload was an ordinary result, so it could travel to execution --
    which is why the MCP server still refuses one (CP3). Here it never enters
    the channel, so there is nothing to refuse later.
    """
    tool = named_tool(
        monitor1d_tools(project_root=tmp_path), "validate_monitor1d_parameters"
    )

    command = _validate(tool, {"nBinsX": "not a number"})

    assert "module_results" not in command.update
    assert command.update["messages"][0].status == "error"


def test_a_json_string_is_accepted_because_models_send_one(tmp_path: Path) -> None:
    tool = named_tool(
        monitor1d_tools(project_root=tmp_path), "validate_monitor1d_parameters"
    )

    command = _validate(tool, json.dumps({"nBinsX": 50}))

    assert command.update["module_results"]["monitor1d"]["parameters"]["nBinsX"] == 50


@pytest.mark.parametrize("model", PARAMETER_MODELS.values(), ids=lambda model: model.__name__)
def test_parameter_models_reject_unknown_fields(model: type[BaseModel]) -> None:
    """A typo must not be recorded as the default value it failed to replace."""
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        model(this_field_does_not_exist=1)


def test_nested_parameter_models_reject_unknown_fields() -> None:
    """Strictness must continue below the top-level writeout object."""
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        WriteoutParameters(output_flags={"bF_cID": False, "bF_typo": False})


def test_readin_requires_one_weight_per_input_file(tmp_path: Path) -> None:
    staged = stage_uploads(tmp_path)
    second = tmp_path / THREAD_ID / "uploads/readin/second.dat"
    second.write_text("second beam\n", encoding="utf-8")
    tool = named_tool(
        readin_tools(project_root=tmp_path, gateway=None), "validate_readin_parameters"
    )

    command = _validate(
        tool,
        {
            "sInputFileName": [staged["readin"], str(second)],
            "Weight": [1.0],
            "sInstrInfIn": None,
        },
    )

    assert "module_results" not in command.update
    assert "one weight per input file" in command.update["messages"][0].text


@pytest.mark.parametrize(
    "weights",
    [
        [-0.1, 1.0],
        [1.1, 0.0],
        [float("nan"), 1.0],
        [float("inf"), 0.0],
    ],
)
def test_readin_refuses_a_weight_that_is_not_a_number_between_zero_and_one(
    weights: list[float], tmp_path: Path
) -> None:
    """The documented range is 0.0 - 1.0, and a non-number is not a weight.

    One case per bound, deliberately. A single ``[-0.1, 1.1]`` case looks like it
    covers both and covers neither: deleting either bound from the model leaves
    the other value still out of range, and the test goes on passing.
    """
    staged = stage_uploads(tmp_path)
    second = tmp_path / THREAD_ID / "uploads/readin/second.dat"
    second.write_text("second beam\n", encoding="utf-8")
    tool = named_tool(
        readin_tools(project_root=tmp_path, gateway=None),
        "validate_readin_parameters",
    )

    command = _validate(
        tool,
        {
            "sInputFileName": [staged["readin"], str(second)],
            "Weight": weights,
            "sInstrInfIn": None,
        },
    )

    assert "module_results" not in command.update


@pytest.mark.parametrize("weights", [[0.25, 0.75], [0.5, 0.5], [1.0, 1.0]])
def test_equal_weights_need_not_be_written_as_halves(
    weights: list[float], tmp_path: Path
) -> None:
    """``[1.0, 1.0]`` is the right answer to "weight them equally", not a bug.

    A round of this review made the weights sum to 1.0 on the strength of the
    VITESS sentence "their sum should give 1". Measured against VITESS 3.8
    ``read_in``, that sum is a readability convention and nothing else: two
    files weighted ``[1.0, 1.0]``, ``[0.5, 0.5]`` and ``[0.1, 0.1]`` all gave a
    monitored total of 4.19578e10, and ``[2.0, 6.0]``, ``[0.5, 1.5]`` and
    ``[0.25, 0.75]`` all gave 3.2863e10. read_in divides by the total, so only
    the ratio survives -- and a validator that refuses ``[1.0, 1.0]`` refuses a
    correct simulation over its spelling.
    """
    staged = stage_uploads(tmp_path)
    second = tmp_path / THREAD_ID / "uploads/readin/second.dat"
    second.write_text("second beam\n", encoding="utf-8")
    tool = named_tool(
        readin_tools(project_root=tmp_path, gateway=None),
        "validate_readin_parameters",
    )

    command = _validate(
        tool,
        {
            "sInputFileName": [staged["readin"], str(second)],
            "Weight": weights,
            "sInstrInfIn": None,
        },
    )

    assert "module_results" in command.update


@pytest.mark.parametrize(
    "build",
    [
        lambda: GuideParameters(Radius=float("nan")),
        lambda: WriteoutParameters(
            filter_limits={"filtLambdaMin": float("nan")}
        ),
        lambda: Monitor1DParameters(xMin=float("nan")),
        lambda: Monitor2DParameters(yMax=float("inf")),
    ],
)
def test_no_cli_parameter_model_accepts_a_non_finite_number(build: Any) -> None:
    with pytest.raises(ValidationError, match="finite number"):
        build()


#: Half-written monitor filters, with what VITESS 3.8 ``monitor1D`` does with
#: each one instead of refusing it. The unfiltered total of the probe beam is
#: 6.01e10; a complete POS_Y filter on [-0.5, 0.5] gives 1.62e10.
HALF_WRITTEN_FILTERS = [
    ({"filterVarMin1": -1.0, "filterVarMax1": 1.0}, "limits require a filter parameter"),
    ({"filterParam1": 1}, "no limits to filter by"),
    ({"filterParam1": 1, "filterVarMin1": -1.0}, "needs both a minimum and a maximum"),
    ({"filterParam2": 2, "filterVarMax2": 1.0}, "needs both a minimum and a maximum"),
    ({"lambdaMin": 4.0}, "lambda needs both a minimum and a maximum"),
    ({"lambdaMax": 12.0}, "lambda needs both a minimum and a maximum"),
]


@pytest.mark.parametrize("model", [Monitor1DParameters, Monitor2DParameters])
@pytest.mark.parametrize(("parameters", "message"), HALF_WRITTEN_FILTERS)
def test_a_half_written_monitor_filter_is_refused(
    model: type[BaseModel], parameters: dict[str, Any], message: str
) -> None:
    """VITESS fills a missing bound with 0 and runs, which is the whole problem.

    Measured on a 1000-trajectory beam: ``-l4`` with no ``-L`` monitored a total
    of 0 -- a wavelength window of [4, 0] keeps nothing and the file is zeros --
    while ``-L12`` with no ``-l`` filtered nothing at all. ``-u-0.5`` with no
    ``-U`` gave 3.87e10, a filter on [-0.5, 0] that nobody asked for, and a
    filter parameter with no bounds, or bounds with no parameter, filtered
    nothing. Every one of them exits 0.
    """
    with pytest.raises(ValidationError, match=message):
        model(**parameters)


@pytest.mark.parametrize("model", [Monitor1DParameters, Monitor2DParameters])
def test_two_monitor_filters_must_say_how_they_combine(
    model: type[BaseModel],
) -> None:
    """``NO_FCOMB`` is not "no combination"; it is OR, and it is the default.

    Measured with both filters complete: ``-C-1`` (the default ``NO_FCOMB``),
    ``-C0`` and ``-C2`` all monitored 4.63264e10, the union of the two filters,
    and only ``-C1`` gave 1.14587e10, the intersection. A user who sets two
    filters and leaves the combination alone has silently chosen OR. This is the
    one combination rule worth enforcing -- see the test below for the two that
    are not.
    """
    with pytest.raises(ValidationError, match="must say how they combine"):
        model(
            filterParam1=1,
            filterVarMin1=-1.0,
            filterVarMax1=1.0,
            filterParam2=5,
            filterVarMin2=4.0,
            filterVarMax2=12.0,
        )


@pytest.mark.parametrize("model", [Monitor1DParameters, Monitor2DParameters])
@pytest.mark.parametrize(
    "parameters",
    [
        {},
        {"filterParam1": 1, "filterVarMin1": -1.0, "filterVarMax1": 1.0},
        {"filterParam2": 5, "filterVarMin2": 4.0, "filterVarMax2": 12.0},
        {
            "filterParam1": 1,
            "filterVarMin1": -1.0,
            "filterVarMax1": 1.0,
            "filterParam2": 5,
            "filterVarMin2": 4.0,
            "filterVarMax2": 12.0,
            "filterComb": 1,
        },
        {"filterComb": 1},
        {"lambdaMin": 4.0, "lambdaMax": 12.0},
    ],
)
def test_a_working_monitor_filter_is_not_refused_for_its_spelling(
    model: type[BaseModel], parameters: dict[str, Any]
) -> None:
    """Two rules a round of this review added are not in the binary.

    **Filter 2 on its own works.** ``-J5 -v4 -V12`` with no filter 1 monitored
    4.15848e10, the same as putting that filter in slot 1. **A combination with
    fewer than two filters changes nothing.** One complete filter gave 1.62002e10
    whether the combination said ``NO_FCOMB``, ``AND`` or ``OR``, and so did no
    filter at all. Refusing either would make a correct configuration
    inexpressible, which is the same defect as a prompt claiming a rule the
    validator does not enforce, pointed the other way.
    """
    model(**parameters)


@pytest.mark.parametrize(
    ("build", "message"),
    [
        (lambda: ReadInParameters(sInputFileName=[], Weight=[]), "input file"),
        (lambda: GuideParameters(GuideEntrWidth=0), "greater than 0"),
        (lambda: GuideParameters(MValGenL=6.1), "less than or equal to 6"),
        (lambda: Monitor1DParameters(nBinsX=0), "greater than 0"),
        (lambda: Monitor1DParameters(xMin=2, xMax=1), "xMin"),
        (lambda: Monitor2DParameters(nBinsY=-1), "greater than 0"),
        (lambda: Monitor2DParameters(yMin=2, yMax=1), "yMin"),
        (
            lambda: WriteoutParameters(
                filter_limits={"filtLambdaMin": 5, "filtLambdaMax": 1}
            ),
            "wavelength minimum",
        ),
    ],
)
def test_physical_constraints_promised_by_the_schema_are_enforced(
    build: Any, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        build()


def test_the_bare_instrument_file_default_is_refused(tmp_path: Path) -> None:
    """`ReadInParameters.sInstrInfIn` defaults to the bare name `instrument.inf`.

    VITESS would resolve it against the run directory, where no such file
    exists, and read-in would fail with an error nobody can read back to a
    cause. The old prompt worked around it by telling the model to send `null`;
    a prompt is not a check.
    """
    stage_uploads(tmp_path)
    tool = named_tool(
        readin_tools(project_root=tmp_path, gateway=None), "validate_readin_parameters"
    )

    command = _validate(
        tool,
        {
            "sInputFileName": [str(tmp_path / THREAD_ID / "uploads/readin/beam.dat")],
            "Weight": [1.0],
        },
    )

    assert "module_results" not in command.update
    assert "sInstrInfIn" in command.update["messages"][0].text


def test_another_conversations_upload_is_refused(tmp_path: Path) -> None:
    """A path is only trustworthy relative to the thread that owns it."""
    stage_uploads(tmp_path, OTHER_THREAD_ID)
    tool = named_tool(
        readin_tools(project_root=tmp_path, gateway=None), "validate_readin_parameters"
    )

    command = _validate(
        tool,
        {
            "sInputFileName": [
                str(tmp_path / OTHER_THREAD_ID / "uploads/readin/beam.dat")
            ],
            "Weight": [1.0],
            "sInstrInfIn": None,
        },
    )

    assert "module_results" not in command.update
    assert "outside this conversation's uploads" in command.update["messages"][0].text


def test_a_file_from_the_wrong_upload_slot_is_refused(tmp_path: Path) -> None:
    """A same-thread instrument file is not a neutron trajectory file."""
    staged = stage_uploads(tmp_path)
    tool = named_tool(
        readin_tools(project_root=tmp_path, gateway=None), "validate_readin_parameters"
    )

    command = _validate(
        tool,
        {
            "sInputFileName": [staged["instrument"]],
            "Weight": [1.0],
            "sInstrInfIn": None,
        },
    )

    assert "module_results" not in command.update
    assert "uploads/readin" in command.update["messages"][0].text


def test_a_nonexistent_file_under_the_right_slot_is_refused(tmp_path: Path) -> None:
    tool = named_tool(
        readin_tools(project_root=tmp_path, gateway=None), "validate_readin_parameters"
    )
    missing = tmp_path / THREAD_ID / "uploads/readin/missing.dat"

    command = _validate(
        tool,
        {
            "sInputFileName": [str(missing)],
            "Weight": [1.0],
            "sInstrInfIn": None,
        },
    )

    assert "module_results" not in command.update
    assert "does not exist" in command.update["messages"][0].text


@pytest.mark.parametrize(
    "filename",
    [
        "outputs/monitor1D.dat",
        "/data/projects/x/monitor1D.dat",
        "../escape.dat",
        "outputs\\monitor1D.dat",
        "bad\x00name.dat",
    ],
)
def test_a_monitor_filename_that_is_a_path_is_refused(
    tmp_path: Path, filename: str
) -> None:
    """The old prompt demanded a FULL ABSOLUTE PATH in capital letters.

    The tool then quietly took the basename, so prompt and tool disagreed --
    and the plot tools of CP3 accept a plain name only, so what the prompt
    asked for would have been rejected there.
    """
    tool = named_tool(
        monitor1d_tools(project_root=tmp_path), "validate_monitor1d_parameters"
    )

    command = _validate(tool, {"fMonitorFilename": filename})

    assert "module_results" not in command.update
    assert "plain file name" in command.update["messages"][0].text


def test_the_writeout_filename_is_checked_the_same_way(tmp_path: Path) -> None:
    tool = named_tool(
        writeout_tools(project_root=tmp_path), "validate_writeout_parameters"
    )

    command = _validate(tool, {"sOutFileName": "runs/output.dat"})

    assert "module_results" not in command.update


def test_a_guide_with_no_shape_file_validates(tmp_path: Path) -> None:
    tool = named_tool(
        guide_tools(project_root=tmp_path, gateway=None), "validate_guide_parameters"
    )

    command = _validate(tool, {"GuideEntrWidth": 5.0})

    assert command.update["module_results"]["guide"]["parameters"]["ShapeFileName"] == ""


# ---------------------------------------------------------------------------
# What may cross back out of a specialist
# ---------------------------------------------------------------------------


class _Returns:
    """A specialist runnable that returns whatever it was told to."""

    def __init__(self, written: dict[str, Any]) -> None:
        self._written = written

    def invoke(self, state: Any, config: Any = None, **kwargs: Any) -> dict[str, Any]:
        return {"messages": [AIMessage("configured")], "module_results": self._written}

    async def ainvoke(
        self, state: Any, config: Any = None, **kwargs: Any
    ) -> dict[str, Any]:
        return self.invoke(state, config, **kwargs)


def test_a_specialist_returns_the_configuration_it_validated() -> None:
    delegate = ModuleSpecialistDelegate(
        _Returns({"guide": {"module": "guide"}}), name="guide-specialist", module="guide"
    )

    crossing = delegate.invoke({"messages": [], "files": {}})

    assert crossing["module_results"] == {"guide": {"module": "guide"}}


def test_a_specialist_cannot_return_another_modules_configuration() -> None:
    """Nothing sends `module_results` inbound, so this can only be invented."""
    delegate = ModuleSpecialistDelegate(
        _Returns({"guide": {"module": "guide"}, "readin": {"module": "readin"}}),
        name="guide-specialist",
        module="guide",
    )

    crossing = delegate.invoke({"messages": [], "files": {}})

    assert crossing["module_results"] == {"guide": {"module": "guide"}}


def test_a_specialist_cannot_invent_the_recorded_configuration_order() -> None:
    class _InventsOrder(_Returns):
        def invoke(self, state: Any, config: Any = None, **kwargs: Any) -> dict[str, Any]:
            result = super().invoke(state, config, **kwargs)
            result["simulation_order_events"] = [
                {"kind": "configured", "module": "monitor2d"}
            ]
            return result

    delegate = ModuleSpecialistDelegate(
        _InventsOrder({"guide": {"module": "guide"}}),
        name="guide-specialist",
        module="guide",
    )

    crossing = delegate.invoke({"messages": [], "files": {}})

    assert crossing["simulation_order_events"] == [
        {"kind": "configured", "execution_order": None, "module": "guide"}
    ]


def test_a_specialist_that_validated_nothing_writes_nothing() -> None:
    delegate = ModuleSpecialistDelegate(
        _Returns({}), name="guide-specialist", module="guide"
    )

    assert "module_results" not in delegate.invoke({"messages": [], "files": {}})


def test_the_boundary_takes_the_module_key_off_the_registration() -> None:
    """`SubAgentMiddleware` reads three keys; a fourth would be passed through."""
    wrapped = with_module_delegation_boundary(
        [
            {
                "name": "guide-specialist",
                "description": "d",
                "runnable": _Returns({}),
                "module": "guide",
            }
        ]
    )

    assert set(wrapped[0]) == {"name", "description", "runnable"}
    assert isinstance(wrapped[0]["runnable"], ModuleSpecialistDelegate)


def test_reconfiguring_one_module_disturbs_no_other() -> None:
    """"Make the guide wider" must not unconfigure the monitors."""
    merged = merge_module_results(
        {"readin": {"v": 1}, "guide": {"v": 1}}, {"guide": {"v": 2}}
    )

    assert merged == {"readin": {"v": 1}, "guide": {"v": 2}}


# ---------------------------------------------------------------------------
# The five specialists
# ---------------------------------------------------------------------------


def test_guided_specialist_plain_question_is_routed_through_ask_user() -> None:
    """Plain prose is an invalid exit until this module has been validated."""
    middleware = GuidedAskUserMiddleware(module="readin")
    question = AIMessage(
        content="Here is the complete configuration. Is this correct?",
        id="confirmation",
    )

    update = middleware.after_model({"messages": [question]}, runtime=None)

    assert update is not None
    assert update["jump_to"] == "tools"
    redirected = update["messages"][0]
    assert redirected.id == question.id
    assert redirected.tool_calls == [
        {
            "name": "ask_user",
            "args": {"question": question.text, "options": []},
            "id": redirected.tool_calls[0]["id"],
            "type": "tool_call",
        }
    ]


def test_guided_specialist_plain_question_reaches_a_graph_interrupt() -> None:
    """The guard must produce a user-visible pause, not merely reshape state."""

    class _IgnoresRequiredToolChoice(FakeMessagesListChatModel):
        def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
            return self

    question = "Here is the complete configuration. Is this correct?"
    agent = create_agent(
        model=_IgnoresRequiredToolChoice(responses=[AIMessage(content=question)]),
        tools=[build_ask_user_tool("readin-specialist")],
        middleware=[GuidedAskUserMiddleware(module="readin")],
    )

    result = asyncio.run(
        agent.ainvoke({"messages": [HumanMessage(content="Configure read-in.")]})
    )

    interrupts = result["__interrupt__"]
    assert len(interrupts) == 1
    assert interrupts[0].value == {
        "kind": "clarification",
        "asked_by": "readin-specialist",
        "question": question,
        "options": [],
    }


def test_guided_specialist_guard_leaves_real_tool_calls_unchanged() -> None:
    middleware = GuidedAskUserMiddleware(module="readin")
    tool_call = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "list_staged_files",
                "args": {},
                "id": "list-files",
                "type": "tool_call",
            }
        ],
    )

    assert middleware.after_model({"messages": [tool_call]}, runtime=None) is None


def test_guided_specialist_guard_stops_after_this_module_is_validated() -> None:
    middleware = GuidedAskUserMiddleware(module="readin")
    final_report = AIMessage(content="Configuration recorded.")

    update = middleware.after_model(
        {
            "messages": [final_report],
            "module_results": {"readin": {"module": "readin"}},
        },
        runtime=None,
    )

    assert update is None


# ---------------------------------------------------------------------------
# The report the server writes when the model does not
# ---------------------------------------------------------------------------


@pytest.fixture
def artifact_store(tmp_path: Path):
    """`SpecialistOutcomeMiddleware` reads the store to list what was delivered."""
    store = ArtifactStore(tmp_path / "artifacts", tmp_path / "audit.jsonl")
    set_artifact_store_for_tests(store)
    yield store
    set_artifact_store_for_tests(None)


def _package(state: dict[str, Any]) -> Any:
    """The hand-off `SpecialistOutcomeMiddleware` builds from this state."""
    update = SpecialistOutcomeMiddleware(
        specialist_name="readin-specialist"
    ).after_agent(state, runtime())
    return update["messages"][0]


def _readin_report_middleware() -> ModuleReportMiddleware:
    return ModuleReportMiddleware(
        module="readin", model=parameter_model("readin"), unattended=False
    )


def test_a_prose_exit_after_a_successful_validation_is_still_verified(
    artifact_store: Any, tmp_path: Path
) -> None:
    """The reported incident: validation succeeded, the model signed off in prose.

    `create_agent` ends the loop at the first message without tool calls,
    before structured output is considered, so `structured_response` was never
    set and the supervisor was told to tell the user the attempt had failed --
    while `module_results[readin]` held the configuration all along.
    """
    state = {
        "messages": [AIMessage("✅ Configuration validated and recorded.")],
        "structured_response": None,
        "module_results": configured_modules(tmp_path, only=("readin",)),
    }

    filled = _readin_report_middleware().after_agent(state, runtime())
    message = _package({**state, **filled})

    assert "STATUS: VERIFIED" in message.text
    assert outcome_verified(message)
    # The staged file the real validation tool recorded, and the one canonical
    # rendering of what it runs as.
    assert "beam.dat" in message.text
    assert "VITESS will run it as: " in message.text
    assert "The server wrote this report" in message.text


def test_the_specialists_own_report_is_left_alone(tmp_path: Path) -> None:
    """A report the model did return is its own work; this only fills a gap."""
    state = {
        "messages": [AIMessage("")],
        "structured_response": SpecialistReport(
            status="completed", finding="read_in will read beam.dat in VITESS format."
        ),
        "module_results": configured_modules(tmp_path, only=("readin",)),
    }

    assert _readin_report_middleware().after_agent(state, runtime()) is None


def test_a_specialist_that_recorded_nothing_stays_unverified(
    artifact_store: Any, tmp_path: Path
) -> None:
    """The fail-closed guarantee. A failed validation must stay a failed attempt."""
    staged = stage_uploads(tmp_path)
    tool = named_tool(
        readin_tools(project_root=tmp_path, gateway=None),
        "validate_readin_parameters",
    )

    # The real tool, refusing: two input files and one weight.
    command = _validate(
        tool, {"sInputFileName": [staged["readin"], staged["readin"]], "Weight": [1.0]}
    )
    assert "module_results" not in command.update

    state = {"messages": [AIMessage("I could not settle the weights.")]}
    assert _readin_report_middleware().after_agent(state, runtime()) is None
    message = _package(state)

    assert "STATUS: UNVERIFIED" in message.text
    assert not outcome_verified(message)


def test_a_sweep_that_recorded_variants_reports_how_many(tmp_path: Path) -> None:
    """The sweep path writes a list, and has no `ask_user` to fall back on."""
    middleware = ModuleReportMiddleware(
        module="guide", model=parameter_model("guide"), unattended=True
    )
    state = {
        "messages": [AIMessage("Recorded both widths.")],
        "module_variants": swept_modules(tmp_path, guide_widths=(3.0, 5.0)),
    }

    filled = middleware.after_agent(state, runtime())
    report = filled["structured_response"]

    assert report.status == "completed"
    assert "2 variants" in report.finding
    assert sum("VITESS will run it as: " in item for item in report.evidence) == 2


def test_a_real_prose_exit_reaches_the_filled_report(
    artifact_store: Any, tmp_path: Path
) -> None:
    """End to end, in the real mounting order, over the real validation tool.

    Middleware `after_agent` hooks run in reverse list order, so the outcome
    middleware mounted first by `build_specialist_middleware` runs last and
    sees what this one wrote. Asserting on the final message is what proves
    that, rather than the two hooks being called in a convenient order here.
    """

    class _EndsInProse(FakeMessagesListChatModel):
        def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
            return self

    staged = stage_uploads(tmp_path)
    agent = create_agent(
        model=_EndsInProse(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "validate_readin_parameters",
                            "args": {
                                "parameters": {
                                    "sInputFileName": [staged["readin"]],
                                    "Weight": [1.0],
                                    # The schema default is the bare name
                                    # `instrument.inf`, which validation refuses.
                                    "sInstrInfIn": None,
                                }
                            },
                            "id": "validate-call",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(
                    "✅ Configuration validated and recorded."
                    "\n**Finding**\nDone."
                ),
            ]
        ),
        tools=[
            named_tool(
                readin_tools(project_root=tmp_path, gateway=None),
                "validate_readin_parameters",
            )
        ],
        response_format=ToolStrategy(SpecialistReport),
        middleware=[
            SpecialistOutcomeMiddleware(specialist_name="readin-specialist"),
            _readin_report_middleware(),
        ],
        state_schema=VitessBridgeState,
        context_schema=dict,
    )

    result = asyncio.run(
        agent.ainvoke(
            {"messages": [HumanMessage("Configure read-in from the staged file.")]},
            {"configurable": {"thread_id": THREAD_ID}},
            context={"user_id": "user-a", "thread_id": THREAD_ID},
        )
    )

    final = result["messages"][-1]
    assert "STATUS: VERIFIED" in final.text
    assert outcome_verified(final)
    assert "beam.dat" in final.text


def test_the_five_specialists_are_the_five_executable_modules(
    offline_model: Any, tmp_path: Path
) -> None:
    specialists = compile_module_specialists(
        project_root=tmp_path,
        gateway=None,
        summarizer_model=offline_model,
        fallback_models=[],
    )

    assert [spec["module"] for spec in specialists] == list(execution_order())
    assert [spec["name"] for spec in specialists] == [
        f"{module}-specialist" for module in execution_order()
    ]


#: The one value a prompt is allowed to contradict its schema on, and what it must
#: say instead.
#:
#: `ReadInParameters.sInstrInfIn` defaults to the bare name `instrument.inf`, which
#: names no file that exists. The prompt tells the model to send `null` instead, and
#: the validation tool refuses anything that is not `null` or a staged path -- so the
#: prompt, the tool and reality agree, and the schema default is the outlier.
#:
#: The required value is written here rather than the field merely being skipped. An
#: exception that skips a field asserts nothing about it: the prompt could go back to
#: claiming `"instrument.inf"`, or to anything else, and this test would still pass
#: while the deliberate override it exists to protect had quietly been lost.
PROMPT_OVERRIDES_SCHEMA = {("readin", "sInstrInfIn"): None}


@pytest.mark.parametrize("module", execution_order())
def test_the_default_configuration_in_each_prompt_is_the_schema_default(
    module: str,
) -> None:
    """A default written twice is a default that drifts.

    These blocks were ported from the first-generation prompts, and two of the
    values in them were already wrong against the schema: the guide's
    `eGuideShapeY`/`eGuideShapeZ` said VT_CONSTANT where the schema says
    VT_LINEAR. A model reading the prompt would configure a different guide than
    the one the user was shown.
    """
    text = (
        Path(__file__).parents[1]
        / "src/vitess_ai/agents/specialists"
        / module
        / "AGENT.md"
    ).read_text(encoding="utf-8")
    block = re.search(r"```jsonc?\n(\{.*?\n\})\n```", text, re.S)
    assert block is not None, f"{module}/AGENT.md has no default configuration block"
    claimed = json.loads(re.sub(r"//.*", "", block.group(1)))

    model = parameter_model(module)
    for field_name, value in claimed.items():
        assert field_name in model.model_fields, (
            f"{module}/AGENT.md names {field_name}, which {model.__name__} has no field for"
        )
        if (module, field_name) in PROMPT_OVERRIDES_SCHEMA:
            required = PROMPT_OVERRIDES_SCHEMA[(module, field_name)]
            assert value == required, (
                f"{module}/AGENT.md overrides the schema default for {field_name}, "
                f"which is allowed, but it must say {required!r} and it says {value!r}"
            )
            continue
        default = model.model_fields[field_name].get_default(call_default_factory=True)
        if hasattr(default, "value"):
            default = default.value
        if hasattr(default, "model_dump"):
            default = default.model_dump(mode="json")
        assert value == default, (
            f"{module}/AGENT.md tells the model {field_name} defaults to {value!r}, "
            f"but {model.__name__} says {default!r}"
        )

    missing = [name for name in model.model_fields if name not in claimed]
    assert not missing, f"{module}/AGENT.md's default block omits {missing}"


# ---------------------------------------------------------------------------
# What the user can actually see of a specialist
# ---------------------------------------------------------------------------


def _agent_md(module: str) -> str:
    return (
        Path(__file__).parents[1]
        / "src/vitess_ai/agents/specialists"
        / module
        / "AGENT.md"
    ).read_text(encoding="utf-8")


def test_a_specialists_own_messages_never_reach_the_user() -> None:
    """The fact every module prompt is written around.

    A specialist that "presents the configuration, then asks" presents it into
    a message the server drops, so the confirmation question arrives with
    nothing to confirm. This is the behaviour that makes that true, asserted
    here so the prompts and the stream cannot part company: if this ever
    starts letting specialist messages through, the instruction to put the
    configuration inside the question becomes unnecessary rather than wrong,
    and someone should know.
    """
    processor = StreamEventProcessor(
        agent=None, config=None, run_id="run-1", user_input_message="configure monitor1d"
    )
    presented = AIMessage(
        'Here is the configuration:\n```json\n{"nBinsX": 100}\n```', id="presented"
    )

    async def collect(node_path: tuple, message: AIMessage) -> list:
        return [
            event
            async for event in processor.process_event(
                (node_path, "updates", {"model": {"messages": [message]}})
            )
        ]

    from_specialist = asyncio.run(collect(("tools:a-task-id",), presented))
    from_supervisor = asyncio.run(
        collect((), AIMessage("The monitor is configured.", id="answer"))
    )

    assert from_specialist == []
    assert from_supervisor != []


@pytest.mark.parametrize("module", execution_order())
def test_every_prompt_puts_the_setup_choice_through_ask_user(module: str) -> None:
    """Default-or-custom is the first question, and it has to be askable.

    Ported from the first generation, where it was the opening message of each
    module agent. Here an opening message is invisible, so a prompt that only
    says "open with this choice" produces a specialist that appears to skip
    straight to interrogating the user about every field in the schema.
    """
    text = _agent_md(module)

    assert "## STEP 0 — ASK WHICH SETUP THE USER WANTS" in text
    choice = text.split("## STEP 0")[1].split("## PATH A")[0]
    assert "`ask_user`" in choice
    assert '`options`: `["Default setup", "Customize"]`' in choice
    assert "your very first action" in choice
    # The instruction it replaced, which a later edit must not restore.
    assert "Open with a short greeting" not in text


@pytest.mark.parametrize("module", execution_order())
def test_every_prompt_keeps_the_configuration_inside_the_question(module: str) -> None:
    """Nothing may tell the model to show the configuration on its own."""
    text = _agent_md(module)

    assert "The user only ever sees your `ask_user` questions." in text
    assert text.count("inside the question text") >= 2
    for banned in (
        "Present it to the user, formatted",
        "Present the complete configuration",
        "Present the complete default configuration",
        "Do not validate in the same turn",
    ):
        assert banned not in text, f"{module}/AGENT.md still says: {banned}"


@pytest.mark.parametrize("module", execution_order())
def test_each_specialist_prompt_carries_its_own_schema_and_no_other(
    module: str,
) -> None:
    """A prompt holding two modules' fields is how a specialist configures the
    wrong one: the field names are there, and nothing stops it using them."""
    prompt = build_module_prompt(
        f"vitess_ai.agents.specialists.{module}", parameter_model(module)
    )

    assert parameter_model(module).__name__ in prompt
    for other in execution_order():
        if other != module:
            assert parameter_model(other).__name__ not in prompt


def _specialist_tools(module: str, tmp_path: Path) -> list[Any]:
    """One specialist's tools, documentation included.

    The documentation tools are injected rather than looked up inside the
    builder, so that this stays a pure function of its arguments -- but the
    agent builders do pass them, and `test_a_module_specialist_is_bound_only_the
    _tools_its_job_needs` compiles the real specialist to prove it.
    """
    documentation = specialist_rag_tools()
    builders = {
        "readin": lambda: readin_tools(
            project_root=tmp_path, gateway=None, documentation_tools=documentation
        ),
        "guide": lambda: guide_tools(
            project_root=tmp_path, gateway=None, documentation_tools=documentation
        ),
        "writeout": lambda: writeout_tools(
            project_root=tmp_path, documentation_tools=documentation
        ),
        "monitor1d": lambda: monitor1d_tools(
            project_root=tmp_path, documentation_tools=documentation
        ),
        "monitor2d": lambda: monitor2d_tools(
            project_root=tmp_path, documentation_tools=documentation
        ),
    }
    return builders[module]()


#: Lower-case identifiers that appear in a prompt between backticks and are not tools.
#:
#: Everything derivable is derived below -- parameter field names come from the
#: models, report field names from `SpecialistReport`, and module/executable names
#: from the catalog -- so this holds only what cannot be derived: JSON's null,
#: one module not in this application, and VITESS's lower-case 2D format names.
PROSE_WORDS_THAT_LOOK_LIKE_TOOLS = frozenset(
    {
        "kdsource",
        "matrix",
        "matrix_compact",
        "matrix_integer",
        "null",
        # `ask_user`'s own argument, named where STEP 0 says what to pass it.
        "options",
        "xyz",
        "xyz_compact",
    }
)

#: Anything in a prompt shaped like this is read as a tool name.
TOOL_SHAPED = re.compile(r"`([a-z][a-z0-9_]*)(?:\(\))?`")


def _field_names(model: type[BaseModel]) -> set[str]:
    """Every field name in a model and in the models nested inside it."""
    names: set[str] = set()
    for field_name, field in model.model_fields.items():
        names.add(field_name)
        annotation = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            names |= _field_names(annotation)
    return names


@pytest.mark.parametrize("module", execution_order())
def test_each_prompt_names_exactly_the_tools_that_specialist_has(
    module: str, tmp_path: Path
) -> None:
    """A prompt that names a tool which is not there is how a model gets stuck.

    The first-generation prompts did exactly this: read-in's told the model to
    call `get_instrument_file` and `instrument_file_status`, neither of which
    was in the list its builder returned. A weaker model follows the prompt,
    the call fails, and it has no instruction for what to do instead.

    Checked in both directions, because the opposite mistake -- a tool the
    specialist has and the prompt never mentions -- is a capability the model
    will not discover.

    **Every lower-case backticked identifier is read as a tool name**, and then
    the ones that provably are not are subtracted. Requiring an underscore left
    `execute`, `delete`, `glob`, `grep` and `ls` invisible -- exactly the former
    filesystem capabilities this test must catch if a prompt invents them.
    """
    documentation = specialist_rag_tools()
    prompt = build_module_prompt(
        f"vitess_ai.agents.specialists.{module}",
        parameter_model(module),
        documentation_tools=documentation,
    )
    not_tools = (
        _field_names(parameter_model(module))
        | set(SpecialistReport.model_fields)
        | set(execution_order())
        | {spec.name for spec in upload_modules()}
        | set(cli_executables().values())
        | PROSE_WORDS_THAT_LOOK_LIKE_TOOLS
    )
    named = {token for token in TOOL_SHAPED.findall(prompt) if token not in not_tools}
    available = {tool.name for tool in _specialist_tools(module, tmp_path)}
    if FILESYSTEM_TOOLS is not None:
        available |= set(FILESYSTEM_TOOLS)

    assert named == available


def test_a_specialist_prompt_mentions_documentation_only_when_it_is_bound() -> None:
    """The previous builder appended the RAG note even with an empty tool list.

    A direct graph-builder test then told a weaker model to call three tools it
    did not have. One argument now governs both halves of that contract.
    """
    package = "vitess_ai.agents.specialists.guide"
    without = build_module_prompt(package, parameter_model("guide"))
    documentation = specialist_rag_tools()
    with_tools = build_module_prompt(
        package,
        parameter_model("guide"),
        documentation_tools=documentation,
    )

    assert all(f"`{name}`" not in without for name in SPECIALIST_RAG_TOOLS)
    assert all(f"`{name}`" in with_tools for name in SPECIALIST_RAG_TOOLS)


@pytest.mark.parametrize(
    "invented_tool",
    ["get_instrument_file", "execute", "delete", "glob", "grep", "ls"],
)
def test_tool_candidate_parser_covers_invented_and_one_word_tools(
    invented_tool: str,
) -> None:
    assert TOOL_SHAPED.findall(f"`{invented_tool}`") == [invented_tool]


@pytest.mark.parametrize("module", execution_order())
def test_validation_tool_description_requires_confirmation(
    module: str, tmp_path: Path
) -> None:
    tool = named_tool(
        _specialist_tools(module, tmp_path), f"validate_{module}_parameters"
    )

    assert "only after" in tool.description
    assert "ask_user" in tool.description
    assert "affirmative confirmation" in tool.description


@pytest.mark.parametrize("module", execution_order())
def test_a_module_specialist_is_bound_only_the_tools_its_job_needs(
    module: str, offline_model: Any, tmp_path: Path
) -> None:
    """`FilesystemMiddleware` binds eight tools unless it is told not to.

    A module specialist configuring one set of parameters was reaching a
    conversation with eleven tools, `execute` and `delete` among them. That is
    context spent on tools it will never use, and on a weaker model it is an
    invitation to use them. The allowlist is core's, so this pins what v2 asks
    for rather than what the upstream default happens to be.

    There is no `read_file` either. It survived the first cut on the theory that
    the delegation boundary carries `/findings/` in, so a later module could read
    what an earlier one recorded -- but a `/findings/` file exists only because
    some specialist called `write_file`, none of these five has it, and without
    `ls` or `glob` there is no path to guess at. These specialists hand off
    through `module_results`, a typed state channel.
    """
    specialist = next(
        spec
        for spec in compile_module_specialists(
            project_root=tmp_path,
            gateway=None,
            summarizer_model=offline_model,
            fallback_models=[],
        )
        if spec["module"] == module
    )
    bound = set(specialist["runnable"].nodes["tools"].bound._tools_by_name)

    expected = {f"validate_{module}_parameters", "ask_user", *SPECIALIST_RAG_TOOLS}
    if module in {"readin", "guide"}:
        expected.add("list_staged_files")

    assert bound == expected
    # `vitess_debug_retrieval` exists and is not here. It is for inspecting
    # retrieval when retrieval looks wrong, which is the orchestrator's problem;
    # a specialist whose job is one validation call has no use for it.
    assert "vitess_debug_retrieval" not in bound
    for absent in ("execute", "delete", "read_file", "write_file", "ls", "glob"):
        assert absent not in bound


def test_only_the_modules_that_read_a_file_can_list_staged_files(
    tmp_path: Path,
) -> None:
    """Three modules write files and have nothing staged to look at."""
    with_uploads = {
        name
        for name, tools in (
            ("readin", readin_tools(project_root=tmp_path, gateway=None)),
            ("guide", guide_tools(project_root=tmp_path, gateway=None)),
            ("writeout", writeout_tools(project_root=tmp_path)),
            ("monitor1d", monitor1d_tools(project_root=tmp_path)),
        )
        if any(tool.name == "list_staged_files" for tool in tools)
    }

    assert with_uploads == {"readin", "guide"}


def test_readin_lists_both_trajectory_and_instrument_upload_slots(tmp_path: Path) -> None:
    """Its instrument field is fed by the catalog's separate instrument row."""

    class _Gateway:
        async def inspect_thread(self, _thread_id: str) -> Any:
            return SimpleNamespace(
                failure=None,
                value=SimpleNamespace(
                    uploads=[
                        SimpleNamespace(
                            module="readin",
                            files=[SimpleNamespace(path="uploads/readin/beam.dat", size_bytes=4)],
                        ),
                        SimpleNamespace(
                            module="instrument",
                            files=[
                                SimpleNamespace(
                                    path="uploads/instrument/instrument.inf",
                                    size_bytes=8,
                                )
                            ],
                        ),
                        SimpleNamespace(
                            module="guide",
                            files=[SimpleNamespace(path="uploads/guide/shape.dat", size_bytes=2)],
                        ),
                    ]
                ),
            )

    tool = named_tool(
        readin_tools(project_root=tmp_path, gateway=_Gateway()), "list_staged_files"
    )

    message = asyncio.run(tool.coroutine(runtime=runtime()))
    listed = json.loads(message.text)

    assert [Path(item["path"]).parent.name for item in listed] == [
        "readin",
        "instrument",
    ]


# ---------------------------------------------------------------------------
# What the prompts claim, and what the validator enforces
#
# These came out of the CP4 review, which probed the real validation tools with
# ten configurations the prompts describe as invalid and found all ten recorded
# as "valid and recorded". Two defect classes: a file field whose value was
# empty was skipped rather than checked, and four physics rules existed only as
# prose. The rules live in the schemas now; these tests are what stops them
# going back to the prompt.
# ---------------------------------------------------------------------------


def _blank_file_case(module: str, tmp_path: Path) -> tuple[Any, dict[str, Any]]:
    """One configuration per module whose file field is blank."""
    staged = stage_uploads(tmp_path)
    cases: dict[str, tuple[Any, dict[str, Any]]] = {
        "readin": (
            readin_tools(project_root=tmp_path, gateway=None),
            {"sInputFileName": [""], "Weight": [1.0], "sInstrInfIn": staged["instrument"]},
        ),
        "writeout": (writeout_tools(project_root=tmp_path), {"sOutFileName": ""}),
        "monitor1d": (monitor1d_tools(project_root=tmp_path), {"fMonitorFilename": ""}),
        "monitor2d": (monitor2d_tools(project_root=tmp_path), {"fMonitorFilename": ""}),
    }
    return cases[module]


@pytest.mark.parametrize("module", ["readin", "writeout", "monitor1d", "monitor2d"])
def test_a_blank_file_name_is_not_a_way_of_saying_there_is_no_file(
    module: str, tmp_path: Path
) -> None:
    """A skipped check is not a passed check.

    Every file field was gated on `if value:`, so an empty string was neither
    staged-path-checked nor filename-checked -- it was simply not looked at, and
    the configuration was recorded as valid. `parameters_to_arguments` then drops
    an empty string, so the flag vanished from the command line too:
    `sInputFileName=[""]` produced `-a1.0`, the weight for input file 1, with no
    `-A` beside it. read_in ran with nothing to read and exited 0.
    """
    tools, parameters = _blank_file_case(module, tmp_path)
    tool = named_tool(tools, f"validate_{module}_parameters")

    command = _validate(tool, parameters)

    assert "module_results" not in command.update


@pytest.mark.parametrize(
    ("field_name", "value"),
    [("sInstrInfIn", ""), ("sTraceFileName", "")],
)
def test_an_optional_readin_file_says_no_file_with_null_not_with_blank(
    field_name: str, value: str, tmp_path: Path
) -> None:
    """`None` and `""` are not two spellings of the same thing.

    These two fields do have a way of saying "no file" -- it is `null`, and the
    converter drops the flag with it. A blank string is a third state that means
    nothing to the schema, nothing to the converter and nothing to VITESS.
    """
    staged = stage_uploads(tmp_path)
    tool = named_tool(
        readin_tools(project_root=tmp_path, gateway=None), "validate_readin_parameters"
    )
    base = {
        "sInputFileName": [staged["readin"]],
        "Weight": [1.0],
        "sInstrInfIn": staged["instrument"],
    }

    refused = _validate(tool, {**base, field_name: value})
    accepted = _validate(tool, {**base, field_name: None} if field_name != "sInstrInfIn" else base)

    assert "module_results" not in refused.update
    assert "module_results" in accepted.update


def test_a_blank_shape_file_is_still_how_the_guide_says_it_has_none(
    tmp_path: Path,
) -> None:
    """The one file field where blank is the answer, and it must stay working.

    `GuideParameters.ShapeFileName` defaults to `""`, which the converter turns
    into no `-S` at all -- that is the documented way to run a guide whose shape
    comes from the dimensions rather than from a file. Tightening the blank rule
    for the other four modules must not take this with it, and the rule is
    derived from this field's own default rather than from a second list.
    """
    stage_uploads(tmp_path)
    tool = named_tool(
        guide_tools(project_root=tmp_path, gateway=None), "validate_guide_parameters"
    )

    command = _validate(tool, {"ShapeFileName": ""})

    assert "module_results" in command.update
    recorded = command.update["module_results"]["guide"]["parameters"]
    assert "-S" not in " ".join(parameters_to_arguments(GuideParameters(**recorded)))


@pytest.mark.parametrize(
    ("model", "field_name", "value", "omitted"),
    [
        # Blank is this field's own default: no shape file, omit `-S`.
        (GuideParameters, "ShapeFileName", "", True),
        (GuideParameters, "ShapeFileName", "   ", True),
        (GuideParameters, "ShapeFileName", "guide.dat", False),
        # `None` is how these say "no file", and the annotation admits it.
        (ReadInParameters, "sInstrInfIn", None, True),
        (ReadInParameters, "sTraceFileName", None, True),
        # Required, with a real default: there is no way to say "no file".
        (Monitor1DParameters, "fMonitorFilename", "monitor1D.dat", False),
    ],
)
def test_whether_a_file_field_is_absent_is_read_off_the_schema(
    model: type[BaseModel], field_name: str, value: Any, omitted: bool
) -> None:
    """One source of truth for which file fields are optional.

    The old gate was `if value:`, which treated every falsy value as absent and
    checked none of them. This asks the field instead -- does its annotation
    admit `None`, is its own default blank -- so there is no second table of
    optional fields to fall out of step with the models.
    """
    assert omitted_file_value(model, field_name, value) is omitted


def test_a_required_file_field_refuses_a_blank_name_at_the_tool_too() -> None:
    """`fMonitorFilename` has no way to say "no file", so blank is an error.

    This is the second reading of the same rule `Monitor1DParameters` enforces.
    It is deliberately *not* a second reading of writeout's rule, which depends
    on `bActive` and therefore lives in one place only.
    """
    with pytest.raises(ValueError, match="an empty name is not how"):
        omitted_file_value(Monitor1DParameters, "fMonitorFilename", "")


@pytest.mark.parametrize(
    ("module", "parameters", "claimed_by_the_prompt"),
    [
        ("readin", {"nRep": 0}, "`nRep` must be 1 or more"),
        ("readin", {"FactInt": 0}, "`FactInt` must be greater than 0"),
        ("readin", {"iDetectColor": -2}, "`iDetectColor` must be -1 or more"),
        ("writeout", {"FactInt": 0}, "`FactInt` must be greater than 0"),
        (
            "writeout",
            {"iDetectColor": -2},
            "`iDetectColor` must be an integer of -1 or more",
        ),
        ("monitor1d", {"eParX": 0}, "`eParX` must be set and cannot be `NO_PAR` (0)"),
        (
            "monitor2d",
            {"xParam": 0},
            "`xParam` and `yParam` must be set and cannot be `NO_PAR` (0)",
        ),
        (
            "monitor2d",
            {"yParam": 0},
            "`xParam` and `yParam` must be set and cannot be `NO_PAR` (0)",
        ),
        ("monitor2d", {"format": -1}, "`format` cannot be `NO_2D_FORMAT` (-1)"),
        (
            "monitor1d",
            {"filterVarMin1": -1.0, "filterVarMax1": 1.0},
            "or complete (a real parameter and both limits)",
        ),
        (
            "monitor2d",
            {"lambdaMin": 4.0},
            'A missing limit is read as `0`, not as "no limit"',
        ),
        (
            "monitor1d",
            {
                "filterParam1": 1,
                "filterVarMin1": -1.0,
                "filterVarMax1": 1.0,
                "filterParam2": 5,
                "filterVarMin2": 4.0,
                "filterVarMax2": 12.0,
            },
            "left at `NO_FCOMB` it keeps every neutron passing **either** filter",
        ),
    ],
)
def test_a_rule_a_prompt_states_is_a_rule_the_validator_enforces(
    module: str, parameters: dict[str, Any], claimed_by_the_prompt: str, tmp_path: Path
) -> None:
    """Prose is not an enforcement layer, and a weaker model is why.

    Each of these was recorded as a valid configuration while the module's own
    prompt said in as many words that it could not be. `NO_PAR` (0) and
    `NO_2D_FORMAT` (-1) are sentinels this schema invented -- neither is in the
    VITESS parameter list or among its documented 2D formats -- so a monitor
    configured with them asks VITESS to plot a quantity that does not exist, and
    still exits 0.
    """
    staged = stage_uploads(tmp_path)
    tools = {
        "readin": lambda: readin_tools(project_root=tmp_path, gateway=None),
        "writeout": lambda: writeout_tools(project_root=tmp_path),
        "monitor1d": lambda: monitor1d_tools(project_root=tmp_path),
        "monitor2d": lambda: monitor2d_tools(project_root=tmp_path),
    }[module]()
    base = (
        {
            "sInputFileName": [staged["readin"]],
            "Weight": [1.0],
            "sInstrInfIn": staged["instrument"],
        }
        if module == "readin"
        else {}
    )

    assert claimed_by_the_prompt in _prompt_text(module), (
        f"{module}/AGENT.md no longer says: {claimed_by_the_prompt}. The claim is "
        "half of this test -- without it the parameters below prove nothing about "
        "what the prompt promises."
    )

    command = _validate(
        named_tool(tools, f"validate_{module}_parameters"), {**base, **parameters}
    )

    assert "module_results" not in command.update, (
        f"{module}/AGENT.md says {claimed_by_the_prompt}, and the validator agreed"
    )


def test_colour_zero_is_a_colour_and_not_a_missing_filter(tmp_path: Path) -> None:
    """The one place the prompt was wrong and the validator was right.

    `writeout/AGENT.md` said colour values had to be "-1 for no filter, or a
    positive integer". The VITESS documentation says the range is >= -1, where
    -1 means "write every trajectory" -- so 0 is a colour like any other, and
    refusing it would have made a legal configuration impossible to express.
    The prompt was corrected to match; this keeps the correction from being
    reverted into the schema.
    """
    command = _validate(
        named_tool(writeout_tools(project_root=tmp_path), "validate_writeout_parameters"),
        {"iDetectColor": 0},
    )

    assert "module_results" in command.update


def test_writeout_may_be_switched_off_instead_of_named(tmp_path: Path) -> None:
    """`bActive=False` is how writeout runs without writing; blank is not.

    Requiring the file name outright would make the module's own "don't write
    anything" setting unreachable, so the rule is conditional -- and that is the
    rule the prompt states.
    """
    tool = named_tool(writeout_tools(project_root=tmp_path), "validate_writeout_parameters")

    assert "module_results" in _validate(
        tool, {"bActive": False, "sOutFileName": ""}
    ).update
    assert "module_results" not in _validate(
        tool, {"bActive": True, "sOutFileName": ""}
    ).update


def _prompt_text(module: str) -> str:
    return (
        Path(__file__).parents[1]
        / "src/vitess_ai/agents/specialists"
        / module
        / "AGENT.md"
    ).read_text(encoding="utf-8")


def _order_of_work(module: str) -> str:
    text = _prompt_text(module)
    start = text.index("## THE ORDER OF WORK")
    return text[start : text.index("\n---\n", start)]


def test_every_prompt_carries_the_same_order_of_work_word_for_word() -> None:
    """Five copies of a sequence is five chances to disagree, and they did.

    Before this, three statements in each prompt described two different orders:
    PATH B ended "build, validate, present", the guidelines said "present the
    final configuration before validating it", and the validation rules ended
    "always validate the final JSON before presenting it to the user". Monitor2D
    managed to say "validate, then present the JSON" and, eighty lines later,
    "after validation, return immediately".

    The sequence is authored once and pasted into all five, and this is what
    keeps them identical -- an edit to one has to be an edit to all five.
    """
    texts = {module: _order_of_work(module) for module in execution_order()}
    distinct = set(texts.values())

    assert len(distinct) == 1, (
        "these prompts describe different orders of work: "
        + ", ".join(sorted(texts))
    )
    canonical = distinct.pop()
    for step in (
        "1. **Ask which setup the user wants**",
        "2. **Collect**",
        "3. **Build**",
        "4. **Show it and confirm it in one `ask_user` call**",
        "5. **Validate**",
        "6. **Then stop.**",
    ):
        assert step in canonical


def test_the_two_modules_that_read_a_file_are_told_to_re_read_the_store() -> None:
    """A file can change between turns, and the transcript will not notice.

    Today a file can be uploaded, replaced or removed and the model will carry
    on with the path it saw once -- so it can build a command against a file
    that is gone, or ask for one already provided. The enforceable half is in
    the validator: `staged_upload_path` refuses a path that is no longer a
    staged file. This is the other half, and it is what makes the right file
    being the wrong file visible to the person who chose it.
    """
    carrying = {
        module
        for module in execution_order()
        if "## SAY WHICH FILE YOU ARE USING" in _prompt_text(module)
    }
    blocks = {
        module: _prompt_text(module).split("## SAY WHICH FILE YOU ARE USING")[1].split("---")[0]
        for module in carrying
    }

    # Exactly the two with a `list_staged_files` tool. The other three write
    # files rather than reading them, and have nothing staged to look at.
    assert carrying == {"readin", "guide"}
    assert len(set(blocks.values())) == 1, "the two copies have drifted"
    assert "call `list_staged_files()` **again**" in blocks["readin"]


@pytest.mark.parametrize("module", execution_order())
def test_no_prompt_tells_the_model_to_validate_before_presenting(module: str) -> None:
    """The contradictions, named so they cannot come back one at a time."""
    text = _prompt_text(module)
    tool = f"validate_{module}_parameters"

    for contradiction in (
        "Always validate the final JSON before presenting it to the user",
        "**Present the final configuration** before validating it",
        f"Always use `{tool}` before presenting",
    ):
        assert contradiction not in text, f"{module}/AGENT.md still says: {contradiction}"

    canonical = _order_of_work(module)
    confirm = canonical.index("4. **Show it and confirm it in one `ask_user` call**")
    validate = canonical.index("5. **Validate**")

    # Showing and confirming are now one call, because a specialist's own
    # messages are never displayed -- so "present, then ask" presented into
    # nothing. What must still hold is that neither happens after validation.
    assert confirm < validate
    assert "inside the question text" in canonical
    assert "is never displayed" in canonical
    assert text.count(
        "Show it and confirm it in a single `ask_user` call, with the complete formatted\n"
        "   configuration inside the question text; do not validate until the user confirms."
    ) == 2


@pytest.mark.parametrize("module", execution_order())
def test_no_prompt_names_a_findings_file_no_specialist_can_write(module: str) -> None:
    """`read_file` went, and the paragraph that described it had to go with it.

    A `/findings/` file exists only because some specialist called `write_file`.
    None of these five has it, so the prompt was teaching the model about a
    hand-off that could not happen -- and a weaker model that believes it will
    go looking for one before configuring anything.
    """
    text = _prompt_text(module)

    assert "/findings/" not in text
    assert "read_file" not in text
