"""
Unit tests for the content_and_artifact plot tool pattern.

Covers:
- generate_plot_1d / generate_plot_2d return the correct tuple shape
- langchain_to_chat_message extracts plot_data from ToolMessage.artifact
- Artifact takes priority over content-based extraction
- Backward-compatible content-based extraction still works
- Error / not-found paths return valid tuples
"""
import json
import textwrap
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from vitess_ai.server.utils import langchain_to_chat_message


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_PLOT_JSON_2D = {
    "data": [{"type": "heatmap", "z": [[0, 1], [2, 3]]}],
    "layout": {"title": "Monitor2D"},
}

SAMPLE_PLOT_JSON_1D = {
    "data": [{"type": "scatter", "x": [1, 2], "y": [3, 4]}],
    "layout": {"title": "Monitor1D"},
}


def _make_artifact(monitor_key: str, plot_json: dict) -> dict:
    return {
        "success": True,
        "plot_data": {
            monitor_key: {
                "plot_json": plot_json,
                "title": f"{monitor_key} Results",
                "xaxis": "x",
                "yaxis": "y",
                "plot_type": monitor_key,
            }
        },
    }


# ---------------------------------------------------------------------------
# Unit: langchain_to_chat_message — artifact extraction
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestArtifactExtraction:
    """ToolMessage.artifact → ChatMessage.custom_data['plot_data']."""

    def test_extracts_2d_plot_from_artifact(self):
        artifact = _make_artifact("monitor2d", SAMPLE_PLOT_JSON_2D)
        msg = ToolMessage(
            content="Plot generated.",
            tool_call_id="call-1",
            artifact=artifact,
        )
        chat = langchain_to_chat_message(msg)

        assert "plot_data" in chat.custom_data
        assert "monitor2d" in chat.custom_data["plot_data"]
        assert chat.custom_data["plot_data"]["monitor2d"]["plot_json"] == SAMPLE_PLOT_JSON_2D

    def test_extracts_1d_plot_from_artifact(self):
        artifact = _make_artifact("monitor1d", SAMPLE_PLOT_JSON_1D)
        msg = ToolMessage(
            content="Plot generated.",
            tool_call_id="call-2",
            artifact=artifact,
        )
        chat = langchain_to_chat_message(msg)

        assert "plot_data" in chat.custom_data
        assert "monitor1d" in chat.custom_data["plot_data"]

    def test_content_stays_small_when_artifact_used(self):
        artifact = _make_artifact("monitor2d", SAMPLE_PLOT_JSON_2D)
        msg = ToolMessage(
            content="The plot has been generated and is displayed in the UI.",
            tool_call_id="call-3",
            artifact=artifact,
        )
        chat = langchain_to_chat_message(msg)

        assert chat.content == "The plot has been generated and is displayed in the UI."
        assert "plot_data" in chat.custom_data

    def test_no_artifact_no_false_positive(self):
        msg = ToolMessage(content="some plain result", tool_call_id="call-4")
        chat = langchain_to_chat_message(msg)

        assert "plot_data" not in chat.custom_data

    def test_artifact_without_plot_data_ignored(self):
        msg = ToolMessage(
            content="ok",
            tool_call_id="call-5",
            artifact={"success": True, "other": "data"},
        )
        chat = langchain_to_chat_message(msg)

        assert "plot_data" not in chat.custom_data

    def test_artifact_priority_over_content(self):
        """When both artifact and content carry plot_data, artifact wins."""
        artifact = _make_artifact("monitor2d", SAMPLE_PLOT_JSON_2D)
        content_dict = {
            "success": True,
            "plot_data": {
                "monitor2d": {
                    "plot_json": {"data": [{"type": "heatmap", "z": [[9, 9]]}]},
                    "title": "stale",
                }
            },
        }
        msg = ToolMessage(
            content=json.dumps(content_dict),
            tool_call_id="call-6",
            artifact=artifact,
        )
        chat = langchain_to_chat_message(msg)

        assert chat.custom_data["plot_data"]["monitor2d"]["plot_json"] == SAMPLE_PLOT_JSON_2D


# ---------------------------------------------------------------------------
# Unit: content-only ToolMessage (no artifact) does not set plot_data
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestContentFallback:
    """Content-only plot payloads are not supported; plot_data comes from artifact only."""

    def test_content_json_with_plot_data_not_extracted(self):
        """When ToolMessage has only content (no artifact) with plot_data, custom_data has no plot_data."""
        content_dict = {
            "success": True,
            "plot_data": {
                "monitor1d": {
                    "plot_json": SAMPLE_PLOT_JSON_1D,
                    "title": "Monitor1D Results",
                }
            },
        }
        msg = ToolMessage(
            content=json.dumps(content_dict),
            tool_call_id="call-7",
        )
        chat = langchain_to_chat_message(msg)

        assert "plot_data" not in chat.custom_data

    def test_non_json_content_no_crash(self):
        msg = ToolMessage(content="not json at all", tool_call_id="call-8")
        chat = langchain_to_chat_message(msg)

        assert chat.type == "tool"
        assert "plot_data" not in chat.custom_data


# ---------------------------------------------------------------------------
# Unit: simulator-style AIMessage plot_data (additional_kwargs)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSimulatorAIMessagePlotData:
    """Simulator attaches plot_data via AIMessage.additional_kwargs."""

    def test_ai_message_additional_kwargs_plot_data(self):
        plot_data = _make_artifact("monitor2d", SAMPLE_PLOT_JSON_2D)["plot_data"]
        msg = AIMessage(
            content="Plots generated.",
            additional_kwargs={"plot_data": plot_data},
        )
        chat = langchain_to_chat_message(msg)

        assert "plot_data" in chat.custom_data
        assert "monitor2d" in chat.custom_data["plot_data"]


# ---------------------------------------------------------------------------
# Unit: generate_plot_1d / generate_plot_2d response_format
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestToolResponseFormat:
    """Verify the tools declare content_and_artifact format."""

    def test_generate_plot_1d_response_format(self):
        from vitess_ai.agents.advanced_mode.tools import generate_plot_1d

        assert generate_plot_1d.response_format == "content_and_artifact"

    def test_generate_plot_2d_response_format(self):
        from vitess_ai.agents.advanced_mode.tools import generate_plot_2d

        assert generate_plot_2d.response_format == "content_and_artifact"


# ---------------------------------------------------------------------------
# Unit: generate_plot_* error paths return valid tuples
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.unit
class TestPlotToolErrorPaths:
    """Error / not-found paths must still return (str, dict) tuples.

    We call the underlying coroutine directly (``tool.coroutine``) because
    ``ainvoke`` with ``content_and_artifact`` format only returns the content
    string; the tuple shape is only visible at the raw-function level and
    when the ToolNode builds the ToolMessage.
    """

    async def test_generate_plot_2d_no_thread_id(self, monkeypatch):
        from vitess_ai.agents.advanced_mode.tools import generate_plot_2d

        monkeypatch.delenv("THREAD_ID", raising=False)

        content, artifact = await generate_plot_2d.coroutine(
            thread_id=None, run_id=None
        )

        assert isinstance(content, str)
        assert isinstance(artifact, dict)
        assert artifact.get("success") is False

    async def test_generate_plot_1d_no_thread_id(self, monkeypatch):
        from vitess_ai.agents.advanced_mode.tools import generate_plot_1d

        monkeypatch.delenv("THREAD_ID", raising=False)

        content, artifact = await generate_plot_1d.coroutine(
            thread_id=None, run_id=None
        )

        assert isinstance(content, str)
        assert isinstance(artifact, dict)
        assert artifact.get("success") is False

    async def test_generate_plot_2d_missing_output_dir(self, tmp_path, monkeypatch):
        from vitess_ai.agents.advanced_mode.tools import generate_plot_2d

        monkeypatch.setattr(
            "vitess_ai.agents.advanced_mode.tools.global_config.VITESS_PROJECT_PATH",
            str(tmp_path),
        )

        content, artifact = await generate_plot_2d.coroutine(
            thread_id="nonexistent-thread", run_id=None
        )

        assert isinstance(content, str)
        assert isinstance(artifact, dict)
        assert artifact.get("success") is False

    async def test_generate_plot_2d_no_monitor_file(self, tmp_path, monkeypatch):
        from vitess_ai.agents.advanced_mode.tools import generate_plot_2d

        monkeypatch.setattr(
            "vitess_ai.agents.advanced_mode.tools.global_config.VITESS_PROJECT_PATH",
            str(tmp_path),
        )
        outputs = tmp_path / "tid" / "outputs"
        outputs.mkdir(parents=True)

        content, artifact = await generate_plot_2d.coroutine(
            thread_id="tid", run_id=None
        )

        assert isinstance(content, str)
        assert "not found" in content.lower()
        assert isinstance(artifact, dict)
        assert artifact["plot_data"] == {}

    async def test_generate_plot_1d_no_monitor_file(self, tmp_path, monkeypatch):
        from vitess_ai.agents.advanced_mode.tools import generate_plot_1d

        monkeypatch.setattr(
            "vitess_ai.agents.advanced_mode.tools.global_config.VITESS_PROJECT_PATH",
            str(tmp_path),
        )
        outputs = tmp_path / "tid" / "outputs"
        outputs.mkdir(parents=True)

        content, artifact = await generate_plot_1d.coroutine(
            thread_id="tid", run_id=None
        )

        assert isinstance(content, str)
        assert "not found" in content.lower()
        assert isinstance(artifact, dict)
        assert artifact["plot_data"] == {}
