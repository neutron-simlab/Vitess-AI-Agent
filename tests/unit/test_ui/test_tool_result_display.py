import pytest

from app.ui_components import extract_delegated_tool_summary, should_hide_delegated_tool_body


@pytest.mark.unit
def test_extract_delegated_tool_summary_from_json_string() -> None:
    content = (
        '{"accepted":true,"module":"monitor1d","validation_passed":true,'
        '"parameters":{"fMonitorFilename":"monitor1D.dat","nBinsX":100}}'
    )
    summary = extract_delegated_tool_summary(content, custom_data={})

    assert summary["module"] == "monitor1d"
    assert summary["validation_passed"] is True
    assert summary["parameters_count"] == 1
    assert isinstance(summary["parameters"], dict)


@pytest.mark.unit
def test_extract_delegated_tool_summary_counts_parameter_list() -> None:
    content = {
        "module": "guide",
        "validation_passed": True,
        "parameters": [
            {"eGuideShapeY": 1},
            {"eGuideShapeY": 3},
            {"eGuideShapeY": 5},
        ],
    }
    summary = extract_delegated_tool_summary(content, custom_data={})

    assert summary["module"] == "guide"
    assert summary["parameters_count"] == 3


@pytest.mark.unit
def test_extract_delegated_tool_summary_falls_back_to_subagent_type() -> None:
    summary = extract_delegated_tool_summary(
        content="non-json result payload",
        custom_data={"subagent_type": "readin"},
    )

    assert summary["module"] == "readin"
    assert summary["validation_passed"] is None
    assert summary["parameters_count"] == 0


@pytest.mark.unit
def test_should_hide_delegated_tool_body_default_policy() -> None:
    custom_data = {
        "tool_kind": "delegated_subagent_result",
        "display_mode": "hidden_by_default",
    }

    assert should_hide_delegated_tool_body(custom_data, show_delegated_tool_bodies=False) is True
    assert should_hide_delegated_tool_body(custom_data, show_delegated_tool_bodies=True) is False
    assert (
        should_hide_delegated_tool_body(
            {"tool_kind": "regular_tool_result", "display_mode": "inline"},
            show_delegated_tool_bodies=False,
        )
        is False
    )
