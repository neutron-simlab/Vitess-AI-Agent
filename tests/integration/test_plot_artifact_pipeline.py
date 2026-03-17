"""
Integration tests for the HT plot artifact pipeline.

Exercises the full path:
  monitor file on disk → generate_plot_2d / generate_plot_1d tool
  → ToolMessage with artifact → langchain_to_chat_message → ChatMessage.custom_data

This validates that large Plotly JSON payloads travel through the artifact
field and arrive intact in the ChatMessage that the UI consumes.
"""
import json
import textwrap
from pathlib import Path

import pytest
from langchain_core.messages import ToolMessage

from vitess_ai.server.utils import langchain_to_chat_message


# ---------------------------------------------------------------------------
# Minimal monitor file fixtures
# ---------------------------------------------------------------------------

MONITOR_2D_CONTENT = textwrap.dedent("""\
    #Monitor 2D Intensity: 3 bins: pos_y [cm] 3 bins: pos_z [cm]
    # title: Test 2D Monitor
    # x_label: pos_y [cm]
    # y_label: pos_z [cm]
    3
    -2.0 0.0 2.0
    -2.0 1.0 2.0 3.0
    0.0  4.0 5.0 6.0
    2.0  7.0 8.0 9.0
""")

MONITOR_1D_CONTENT = textwrap.dedent("""\
    #Monitor 1D Intensity: 3 bins: wavelength [AA]
    # title: Test 1D Monitor
    # x_label: wavelength [AA]
    # y_label: Intensity [n/s]
    3
    1.0 100.0 5.0
    2.0 200.0 10.0
    3.0 150.0 7.5
""")


@pytest.fixture
def outputs_dir(tmp_path):
    """Create a thread outputs directory with monitor files."""
    out = tmp_path / "test-thread" / "outputs"
    out.mkdir(parents=True)
    (out / "monitor2D.dat").write_text(MONITOR_2D_CONTENT)
    (out / "monitor1D.dat").write_text(MONITOR_1D_CONTENT)
    return out


# ---------------------------------------------------------------------------
# Integration: generate_plot_2d → artifact → ChatMessage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.integration
class TestPlot2dArtifactPipeline:
    """End-to-end: monitor2D.dat → generate_plot_2d → ChatMessage with plot.

    We call ``tool.coroutine(...)`` to get the raw ``(content, artifact)``
    tuple, then manually wrap it in a ``ToolMessage`` the way LangChain's
    ToolNode would.
    """

    async def test_full_pipeline(self, tmp_path, outputs_dir, monkeypatch):
        from vitess_ai.agents.advanced_mode.tools import generate_plot_2d

        monkeypatch.setattr(
            "vitess_ai.agents.advanced_mode.tools.global_config.VITESS_PROJECT_PATH",
            str(tmp_path),
        )

        content, artifact = await generate_plot_2d.coroutine(
            thread_id="test-thread", run_id=None
        )

        assert isinstance(content, str)
        assert artifact["success"] is True
        assert "monitor2d" in artifact["plot_data"]

        plot_json = artifact["plot_data"]["monitor2d"]["plot_json"]
        assert "data" in plot_json
        assert "layout" in plot_json

        # Simulate what the ToolNode + server does: wrap in ToolMessage and convert
        tool_msg = ToolMessage(
            content=content,
            tool_call_id="call-integration-2d",
            artifact=artifact,
        )
        chat = langchain_to_chat_message(tool_msg)

        assert "plot_data" in chat.custom_data
        assert "monitor2d" in chat.custom_data["plot_data"]
        assert chat.custom_data["plot_data"]["monitor2d"]["plot_json"] == plot_json
        assert len(content) < 200, "Content sent to LLM should be a short message"

    async def test_content_is_small_artifact_is_large(self, tmp_path, outputs_dir, monkeypatch):
        """The whole point: content is tiny, artifact carries the big payload."""
        from vitess_ai.agents.advanced_mode.tools import generate_plot_2d

        monkeypatch.setattr(
            "vitess_ai.agents.advanced_mode.tools.global_config.VITESS_PROJECT_PATH",
            str(tmp_path),
        )

        content, artifact = await generate_plot_2d.coroutine(
            thread_id="test-thread", run_id=None
        )

        content_size = len(content)
        artifact_size = len(json.dumps(artifact))

        assert content_size < artifact_size, (
            f"Content ({content_size} chars) should be smaller than artifact ({artifact_size} chars)"
        )


# ---------------------------------------------------------------------------
# Integration: generate_plot_1d → artifact → ChatMessage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.integration
class TestPlot1dArtifactPipeline:
    """End-to-end: monitor1D.dat → generate_plot_1d → ChatMessage with plot."""

    async def test_full_pipeline(self, tmp_path, outputs_dir, monkeypatch):
        from vitess_ai.agents.advanced_mode.tools import generate_plot_1d

        monkeypatch.setattr(
            "vitess_ai.agents.advanced_mode.tools.global_config.VITESS_PROJECT_PATH",
            str(tmp_path),
        )

        content, artifact = await generate_plot_1d.coroutine(
            thread_id="test-thread", run_id=None
        )

        assert isinstance(content, str)
        assert artifact["success"] is True
        assert "monitor1d" in artifact["plot_data"]

        plot_json = artifact["plot_data"]["monitor1d"]["plot_json"]
        assert "data" in plot_json
        assert "layout" in plot_json

        # Wrap in ToolMessage and convert
        tool_msg = ToolMessage(
            content=content,
            tool_call_id="call-integration-1d",
            artifact=artifact,
        )
        chat = langchain_to_chat_message(tool_msg)

        assert "plot_data" in chat.custom_data
        assert "monitor1d" in chat.custom_data["plot_data"]
        assert chat.custom_data["plot_data"]["monitor1d"]["plot_json"] == plot_json


# ---------------------------------------------------------------------------
# Integration: run_id sub-directory
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.integration
class TestPlotWithRunId:
    """Verify per-run sub-directories are resolved correctly."""

    async def test_2d_plot_with_run_id(self, tmp_path, monkeypatch):
        from vitess_ai.agents.advanced_mode.tools import generate_plot_2d

        monkeypatch.setattr(
            "vitess_ai.agents.advanced_mode.tools.global_config.VITESS_PROJECT_PATH",
            str(tmp_path),
        )

        run_dir = tmp_path / "tid" / "outputs" / "sim_001"
        run_dir.mkdir(parents=True)
        (run_dir / "monitor2D.dat").write_text(MONITOR_2D_CONTENT)

        content, artifact = await generate_plot_2d.coroutine(
            thread_id="tid", run_id="sim_001"
        )

        assert artifact["success"] is True
        assert "monitor2d" in artifact["plot_data"]

    async def test_1d_plot_with_run_id(self, tmp_path, monkeypatch):
        from vitess_ai.agents.advanced_mode.tools import generate_plot_1d

        monkeypatch.setattr(
            "vitess_ai.agents.advanced_mode.tools.global_config.VITESS_PROJECT_PATH",
            str(tmp_path),
        )

        run_dir = tmp_path / "tid" / "outputs" / "sim_002"
        run_dir.mkdir(parents=True)
        (run_dir / "monitor1D.dat").write_text(MONITOR_1D_CONTENT)

        content, artifact = await generate_plot_1d.coroutine(
            thread_id="tid", run_id="sim_002"
        )

        assert artifact["success"] is True
        assert "monitor1d" in artifact["plot_data"]
