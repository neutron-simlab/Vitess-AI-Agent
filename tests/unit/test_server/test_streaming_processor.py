import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from vitess_ai.server.streaming.processor import StreamEventProcessor


def _parse_sse_payload(sse_line: str) -> dict:
    assert sse_line.startswith("data: ")
    return json.loads(sse_line[len("data: "):].strip())


async def _collect_sse(processor: StreamEventProcessor, stream_event: tuple) -> list[dict]:
    payloads: list[dict] = []
    async for sse_line in processor.process_event(stream_event):
        payloads.append(_parse_sse_payload(sse_line))
    return payloads


def _build_processor() -> StreamEventProcessor:
    agent = MagicMock()
    state = MagicMock()
    state.values = {}
    agent.aget_state = AsyncMock(return_value=state)
    return StreamEventProcessor(
        agent=agent,
        config={},
        run_id="run-1",
        user_input_message="test",
        default_module="advanced_mode",
        enable_task_lifecycle=True,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_task_lifecycle_pending_running_complete() -> None:
    processor = _build_processor()

    pending_event = (
        tuple(),
        "updates",
        {
            "model": {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "task",
                                "id": "task-1",
                                "args": {
                                    "subagent_type": "researcher",
                                    "description": "Research latest AI safety developments",
                                },
                            }
                        ],
                    )
                ]
            }
        },
    )
    pending_payloads = await _collect_sse(processor, pending_event)
    pending_lifecycle = [p for p in pending_payloads if p.get("type") == "task_lifecycle"]
    assert len(pending_lifecycle) == 1
    assert pending_lifecycle[0]["content"]["phase"] == "pending"
    assert pending_lifecycle[0]["content"]["status"] == "pending"
    assert pending_lifecycle[0]["content"]["task_id"] == "task-1"

    running_event = (
        ("tools:pregel-1",),
        "updates",
        {"worker": {"messages": []}},
    )
    running_payloads = await _collect_sse(processor, running_event)
    running_lifecycle = [p for p in running_payloads if p.get("type") == "task_lifecycle"]
    assert len(running_lifecycle) == 1
    assert running_lifecycle[0]["content"]["phase"] == "running"
    assert running_lifecycle[0]["content"]["pregel_id"] == "pregel-1"
    assert running_lifecycle[0]["content"]["task_id"] == "task-1"

    complete_event = (
        tuple(),
        "updates",
        {
            "tools": {
                "messages": [
                    ToolMessage(content="completed result", tool_call_id="task-1")
                ]
            }
        },
    )
    complete_payloads = await _collect_sse(processor, complete_event)
    complete_lifecycle = [p for p in complete_payloads if p.get("type") == "task_lifecycle"]
    assert len(complete_lifecycle) == 1
    assert complete_lifecycle[0]["content"]["phase"] == "complete"
    assert complete_lifecycle[0]["content"]["status"] == "complete"
    assert complete_lifecycle[0]["content"]["task_id"] == "task-1"
    assert complete_lifecycle[0]["content"]["pregel_id"] == "pregel-1"
    assert "completed result" in (complete_lifecycle[0]["content"]["result_preview"] or "")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_task_lifecycle_running_uses_fifo_pending_order() -> None:
    processor = _build_processor()

    pending_two_event = (
        tuple(),
        "updates",
        {
            "model": {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "task",
                                "id": "task-1",
                                "args": {"subagent_type": "researcher", "description": "Task one"},
                            },
                            {
                                "name": "task",
                                "id": "task-2",
                                "args": {"subagent_type": "planner", "description": "Task two"},
                            },
                        ],
                    )
                ]
            }
        },
    )
    await _collect_sse(processor, pending_two_event)

    running_one = await _collect_sse(
        processor,
        (("tools:pregel-1",), "updates", {"worker": {"messages": []}}),
    )
    running_two = await _collect_sse(
        processor,
        (("tools:pregel-2",), "updates", {"worker": {"messages": []}}),
    )

    first_running = [p for p in running_one if p.get("type") == "task_lifecycle"][0]
    second_running = [p for p in running_two if p.get("type") == "task_lifecycle"][0]
    assert first_running["content"]["task_id"] == "task-1"
    assert second_running["content"]["task_id"] == "task-2"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_task_lifecycle_pending_is_idempotent() -> None:
    processor = _build_processor()
    pending_event = (
        tuple(),
        "updates",
        {
            "model": {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "task",
                                "id": "task-1",
                                "args": {"subagent_type": "researcher", "description": "Task one"},
                            }
                        ],
                    )
                ]
            }
        },
    )

    first_payloads = await _collect_sse(processor, pending_event)
    second_payloads = await _collect_sse(processor, pending_event)
    first_lifecycle = [p for p in first_payloads if p.get("type") == "task_lifecycle"]
    second_lifecycle = [p for p in second_payloads if p.get("type") == "task_lifecycle"]

    assert len(first_lifecycle) == 1
    assert second_lifecycle == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_task_lifecycle_complete_unknown_task_is_ignored() -> None:
    processor = _build_processor()
    complete_unknown_event = (
        tuple(),
        "updates",
        {
            "tools": {
                "messages": [
                    ToolMessage(content="unknown task result", tool_call_id="missing-task")
                ]
            }
        },
    )

    payloads = await _collect_sse(processor, complete_unknown_event)
    lifecycle_payloads = [p for p in payloads if p.get("type") == "task_lifecycle"]
    assert lifecycle_payloads == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delegated_tool_message_gets_tool_classification_metadata() -> None:
    processor = _build_processor()

    # Register delegated task first (pending phase)
    await _collect_sse(
        processor,
        (
            tuple(),
            "updates",
            {
                "model": {
                    "messages": [
                        AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "name": "task",
                                    "id": "task-1",
                                    "args": {
                                        "subagent_type": "monitor1d",
                                        "description": "Validate default monitor1d parameters",
                                    },
                                }
                            ],
                        )
                    ]
                }
            },
        ),
    )

    payloads = await _collect_sse(
        processor,
        (
            tuple(),
            "updates",
            {
                "tools": {
                    "messages": [
                        ToolMessage(
                            content='{"module":"monitor1d","validation_passed":true,"parameters":{"nBinsX":100}}',
                            tool_call_id="task-1",
                        )
                    ]
                }
            },
        ),
    )

    tool_messages = [
        p["content"]
        for p in payloads
        if p.get("type") == "message" and isinstance(p.get("content"), dict) and p["content"].get("type") == "tool"
    ]
    assert len(tool_messages) == 1
    custom_data = tool_messages[0].get("custom_data", {})
    assert custom_data.get("tool_kind") == "delegated_subagent_result"
    assert custom_data.get("subagent_type") == "monitor1d"
    assert custom_data.get("delegated_task_id") == "task-1"
    assert custom_data.get("display_mode") == "hidden_by_default"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_non_delegated_tool_message_is_regular_tool_result() -> None:
    processor = _build_processor()

    payloads = await _collect_sse(
        processor,
        (
            tuple(),
            "updates",
            {
                "tools": {
                    "messages": [
                        ToolMessage(
                            content='{"ok":true}',
                            tool_call_id="non-task-id",
                        )
                    ]
                }
            },
        ),
    )

    tool_messages = [
        p["content"]
        for p in payloads
        if p.get("type") == "message" and isinstance(p.get("content"), dict) and p["content"].get("type") == "tool"
    ]
    assert len(tool_messages) == 1
    custom_data = tool_messages[0].get("custom_data", {})
    assert custom_data.get("tool_kind") == "regular_tool_result"
    assert custom_data.get("display_mode") == "inline"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_plot_tool_message_is_classified_as_plot_tool_result() -> None:
    processor = _build_processor()

    payloads = await _collect_sse(
        processor,
        (
            tuple(),
            "updates",
            {
                "tools": {
                    "messages": [
                        ToolMessage(
                            content="plot generated",
                            tool_call_id="plot-1",
                            artifact={
                                "plot_data": {
                                    "monitor1d": {
                                        "plot_json": {"data": [], "layout": {}},
                                        "title": "Monitor1D Results",
                                    }
                                }
                            },
                        )
                    ]
                }
            },
        ),
    )

    tool_messages = [
        p["content"]
        for p in payloads
        if p.get("type") == "message" and isinstance(p.get("content"), dict) and p["content"].get("type") == "tool"
    ]
    assert len(tool_messages) == 1
    custom_data = tool_messages[0].get("custom_data", {})
    assert custom_data.get("tool_kind") == "plot_tool_result"
    assert custom_data.get("display_mode") == "inline"
