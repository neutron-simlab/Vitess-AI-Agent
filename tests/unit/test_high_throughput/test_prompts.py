import pytest

from vitess_ai.agents.high_throughput.prompts import (
    get_high_throughput_system_prompt,
    get_module_subagent_system_prompt,
)


@pytest.mark.unit
def test_orchestrator_prompt_preserves_structured_parameter_flow() -> None:
    prompt = get_high_throughput_system_prompt()

    assert "Do not lose or omit structured validated parameters needed for downstream tools." in prompt
    assert "Keep user-facing summaries concise where possible." in prompt


@pytest.mark.unit
def test_module_subagent_prompt_requires_structured_payload_after_submit() -> None:
    prompt = get_module_subagent_system_prompt(
        module_name="monitor1d",
        module_description="Monitor 1D validation",
        tool_names=["validate_monitor1d_module", "submit_module_result"],
    )

    assert "After calling submit_module_result, return the structured validated payload" in prompt
    assert "Do not omit validated parameters from the final subagent response." in prompt
