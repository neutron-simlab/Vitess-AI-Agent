from types import SimpleNamespace

import pytest

import vitess_ai.agents.advanced_mode.agent as advanced_mode_agent_module
from vitess_ai.agents.advanced_mode.agent import AdvancedModeAgent


def _fake_tool(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_initialize_mounts_docs_backend_when_rag_data_dir_exists(
    monkeypatch,
    temp_dir,
) -> None:
    captured: dict[str, object] = {}

    def fake_create_deep_agent(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return object()

    class DummyFilesystemBackend:
        def __init__(self, root_dir: str, virtual_mode: bool = False):
            self.root_dir = root_dir
            self.virtual_mode = virtual_mode

    class DummyCompositeBackend:
        def __init__(self, default, routes):
            self.default = default
            self.routes = routes

    monkeypatch.setattr("deepagents.create_deep_agent", fake_create_deep_agent)
    monkeypatch.setattr(
        "deepagents.backends.filesystem.FilesystemBackend",
        DummyFilesystemBackend,
    )
    monkeypatch.setattr(
        "deepagents.backends.composite.CompositeBackend",
        DummyCompositeBackend,
    )
    monkeypatch.setattr(
        advanced_mode_agent_module,
        "get_shared_advanced_mode_tools",
        lambda: [_fake_tool("shared-tool")],
    )

    docs_dir = temp_dir / "docs"
    docs_dir.mkdir()
    monkeypatch.setattr(
        advanced_mode_agent_module.global_config,
        "VITESS_RAG_DATA_DIR",
        str(docs_dir),
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
            }
        ],
    )

    await agent.initialize()

    assert agent.initialized is True
    assert agent.app is not None
    kwargs = captured["kwargs"]
    backend = kwargs["backend"]
    assert backend.default.virtual_mode is True
    assert "/docs/" in backend.routes
    assert backend.routes["/docs/"].root_dir == str(docs_dir.resolve())
    assert backend.routes["/docs/"].virtual_mode is True
