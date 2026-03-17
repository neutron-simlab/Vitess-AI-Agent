from types import SimpleNamespace

import pytest

import vitess_ai.agents.advanced_mode.agent as advanced_mode_agent_module
from vitess_ai.agents.advanced_mode.agent import AdvancedModeAgent
from vitess_ai.agents.simulator.middleware import DynamicModelMiddleware


def _fake_tool(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name)


@pytest.mark.unit
def test_build_subagents_attach_dynamic_model_middleware(monkeypatch) -> None:
    fake_modules = [
        SimpleNamespace(
            name="readin",
            description="Read input configuration",
            tool_factory=lambda: [_fake_tool("readin-tool")],
        ),
        SimpleNamespace(
            name="guide",
            description="Guide configuration",
            tool_factory=lambda: [_fake_tool("guide-tool")],
        ),
        SimpleNamespace(
            name="writeout",
            description="Write output configuration",
            tool_factory=lambda: [_fake_tool("writeout-tool")],
        ),
        SimpleNamespace(
            name="monitor1d",
            description="Monitor1D configuration",
            tool_factory=lambda: [_fake_tool("monitor1d-tool")],
        ),
        SimpleNamespace(
            name="monitor2d",
            description="Monitor2D configuration",
            tool_factory=lambda: [_fake_tool("monitor2d-tool")],
        ),
    ]

    monkeypatch.setattr(
        "vitess_ai.modules.get_graph_module_metadata",
        lambda: fake_modules,
    )

    agent = AdvancedModeAgent()
    subagents = agent._build_subagents()

    assert len(subagents) == 6
    for spec in subagents:
        middleware = spec.get("middleware", [])
        assert any(isinstance(mw, DynamicModelMiddleware) for mw in middleware)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_initialize_passes_dynamic_model_middleware_to_deep_agent(
    monkeypatch,
    temp_dir,
) -> None:
    captured: dict[str, object] = {}

    def fake_create_deep_agent(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return object()

    class DummyFilesystemBackend:
        def __init__(self, root_dir: str):
            self.root_dir = root_dir

    monkeypatch.setattr("deepagents.create_deep_agent", fake_create_deep_agent)
    monkeypatch.setattr(
        "deepagents.backends.filesystem.FilesystemBackend",
        DummyFilesystemBackend,
    )
    monkeypatch.setattr(
        advanced_mode_agent_module,
        "get_shared_advanced_mode_tools",
        lambda: [_fake_tool("shared-tool")],
    )

    agent = AdvancedModeAgent(filesystem_root=str(temp_dir))
    monkeypatch.setattr(agent, "_build_llm", lambda: SimpleNamespace(streaming=True))
    monkeypatch.setattr(
        agent,
        "_build_subagents",
        lambda: [
            {
                "name": "sim-runner",
                "description": "runner",
                "system_prompt": "prompt",
                "tools": [_fake_tool("runner-tool")],
                "middleware": [DynamicModelMiddleware()],
            }
        ],
    )

    await agent.initialize()

    assert agent.initialized is True
    assert agent.app is not None
    kwargs = captured["kwargs"]
    middleware = kwargs["middleware"]
    assert any(isinstance(mw, DynamicModelMiddleware) for mw in middleware)
