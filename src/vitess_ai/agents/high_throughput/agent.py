"""
High-throughput agent built with LangChain Deep Agents.

This graph is intentionally separate from the supervisor graph and is meant for
advanced, exploratory workflows (multi-step simulation orchestration).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from vitess_ai.core.config import global_config
from vitess_ai.core.llms_providers import create_llm_with_fallback
from vitess_ai.core.log import get_logger
from vitess_ai.agents.high_throughput.prompts import (
    get_high_throughput_system_prompt,
    get_module_subagent_system_prompt,
    get_sim_runner_system_prompt,
)
from vitess_ai.agents.high_throughput.tools import (
    get_shared_high_throughput_tools,
    get_sim_runner_tools,
)


class HighThroughputAgent:
    """
    High-throughput orchestrator using `create_deep_agent(...)`.

    Architecture:
    - Main high-throughput agent orchestrator
    - Module subagents (readin/guide/writeout/monitor)
    - Simulation runner subagent
    - Filesystem backend for persistent analysis context
    """

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        filesystem_root: str | None = None,
    ):
        self.provider = provider or global_config.DEFAULT_PROVIDER
        self.model = model or global_config.DEFAULT_MODEL
        self.filesystem_root = filesystem_root or global_config.VITESS_PROJECT_PATH

        self.logger = get_logger(__name__)
        self.memory = InMemorySaver()
        self.app = None
        self.initialized = False

    def _build_llm(self) -> Any:
        """Build the base LLM used by the agent."""
        return create_llm_with_fallback(
            provider=self.provider,
            model=self.model,
            streaming=True,
        )

    def _build_module_subagents(self) -> list[dict[str, Any]]:
        """Build module-focused subagents from central catalog metadata."""
        from vitess_ai.modules import get_graph_module_metadata

        modules = get_graph_module_metadata()
        module_by_name = {m.name: m for m in modules}

        subagents: list[dict[str, Any]] = []

        for module_name in ("readin", "guide", "writeout", "monitor1d", "monitor2d"):
            module = module_by_name.get(module_name)
            if not module or not module.tool_factory:
                continue
            module_tools = module.tool_factory()
            subagents.append(
                {
                    "name": f"{module_name}-module",
                    "description": module.description,
                    "system_prompt": get_module_subagent_system_prompt(
                        module_name=module_name,
                        module_description=module.description,
                        tool_names=[tool.name for tool in module_tools],
                    ),
                    "tools": module_tools,
                }
            )

        return subagents

    def _build_subagents(self) -> list[dict[str, Any]]:
        """Build full subagent list: modules + sim runner."""
        subagents = self._build_module_subagents()

        subagents.append(
            {
                "name": "sim-runner",
                "description": "Generate and run high-throughput Vitess simulations from module results.",
                "system_prompt": get_sim_runner_system_prompt(),
                "tools": get_sim_runner_tools(),
            }
        )
        return subagents

    async def initialize(self, force_reinitialize: bool = False) -> None:
        """Initialize (or reinitialize) the high-throughput graph."""
        if self.initialized and not force_reinitialize:
            return

        try:
            from deepagents import create_deep_agent
            from deepagents.backends.filesystem import FilesystemBackend
        except ImportError as exc:
            raise RuntimeError(
                "High-throughput agent requires the `deepagents` package. Install it with `pip install deepagents`."
            ) from exc

        if force_reinitialize:
            self.app = None
            self.initialized = False

        llm = self._build_llm()
        subagents = self._build_subagents()

        Path(self.filesystem_root).mkdir(parents=True, exist_ok=True)
        backend = FilesystemBackend(root_dir=self.filesystem_root)
        self.app = create_deep_agent(
            name="high_throughput",
            model=llm,
            tools=get_shared_high_throughput_tools(),
            subagents=subagents,
            backend=backend,
            checkpointer=self.memory,
            system_prompt=get_high_throughput_system_prompt(),
        )
        self.initialized = True
        self.logger.info(
            "High-throughput agent initialized (provider=%s, model=%s, subagents=%s)",
            self.provider,
            self.model,
            [subagent.get("name") for subagent in subagents],
        )

    async def restart_with_new_config(
        self,
        provider: str | None = None,
        model: str | None = None,
        clear_state: bool = True,
    ) -> None:
        """
        Restart high-throughput graph with optional provider/model updates.

        Args:
            provider: Optional provider override.
            model: Optional model override.
            clear_state: If True, reset checkpointer memory.
        """
        if provider:
            self.provider = provider
        if model:
            self.model = model

        if clear_state:
            self.memory = InMemorySaver()

        await self.initialize(force_reinitialize=True)


async def create_default_high_throughput(
    provider: str = global_config.DEFAULT_PROVIDER,
    model: str = global_config.DEFAULT_MODEL,
) -> HighThroughputAgent:
    """Factory helper used by the agent registry."""
    agent = HighThroughputAgent(provider=provider, model=model)
    await agent.initialize()
    return agent
