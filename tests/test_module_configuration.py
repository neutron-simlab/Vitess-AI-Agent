"""CP4: a validated configuration reaches the command builder without a model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import pytest
from langchain_core.messages import AIMessage
from langgraph.types import Command
from pydantic import BaseModel, Field

from vitess_ai.agents.delegation import (
    ModuleSpecialistDelegate,
    with_module_delegation_boundary,
)
from vitess_ai.agents.specialists import compile_module_specialists
from vitess_ai.agents.specialists.guide.tools import build_tools as guide_tools
from vitess_ai.agents.specialists.module_specialist import build_module_prompt
from vitess_ai.agents.specialists.monitor1d.tools import build_tools as monitor1d_tools
from vitess_ai.agents.specialists.readin.tools import build_tools as readin_tools
from vitess_ai.agents.specialists.writeout.tools import build_tools as writeout_tools
from vitess_ai.cli.arguments import (
    ParameterConversionError,
    parameters_to_arguments,
)
from vitess_ai.modules.catalog import execution_order
from vitess_ai.modules.parameters import PARAMETER_MODELS, parameter_model
from vitess_ai.schema import GuideParameters, WriteoutParameters
from vitess_ai.schema.module_result import (
    ModuleConfigurationResult,
    module_schema_version,
)
from vitess_ai.state import merge_module_results

from doubles import THREAD_ID, named_tool, runtime, stage_uploads

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


@pytest.mark.parametrize(
    "filename",
    ["outputs/monitor1D.dat", "/data/projects/x/monitor1D.dat", "../escape.dat"],
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
