"""Assemble the VITESS advanced-mode sweep agent.

**Two registered top-level agents, not one supervisor with two specialists.** `vitess`
and `advanced_mode` differ in *interaction model*, not expertise: one is a guided
conversation that calls `ask_user`, the other a long unattended sweep. A supervisor
able to delegate to `advanced_mode` would run a forty-minute batch inside a tool call
tied to the HTTP connection -- which is precisely the problem juena's background
research subsystem exists to solve and which v2 is deliberately not inheriting. Two
agent ids keep them on separate threads with separate checkpoints, and core's
`/{agent_id}/stream` already takes the id.

What is shared is everything below the interaction: the same five module specialists
(compiled again, unattended), the same validation, the same MCP gateway, the same
artifact store and the same `<verified_by_server>` block.

Three things the first-generation agent did that this does not:

- `InMemorySaver` and `restart_with_new_config(clear_state=True)`. Replacing the saver
  is meaningless against a shared Postgres checkpointer, and it was the mechanism that
  wiped conversation state for **every** user.
- `DynamicModelMiddleware`, which core replaced with `RuntimeModelMiddleware`.
- A `FilesystemBackend` rooted at the whole configured project path, so one
  conversation could read another's files. **No project-filesystem route is mounted
  here**: the sweep reads its inputs through `inspect_thread_folders`, which is already
  scoped to one thread by the MCP server, and the guided agent mounts none either.
  Core still supplies its normal virtual routes for per-user memory and read-only
  findings; neither route exposes `/data/projects`. A per-thread project route would
  have to be swapped at invocation, since the thread is not known when the graph is
  built, and giving one of the two agents a project filesystem the other lacks is an
  asymmetry nothing here needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain.agents import create_agent
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

from juena_core.agents.backends import build_supervisor_backend
from juena_core.agents.specialist_runtime import (
    build_fallback_models,
    build_supervisor_middleware,
    load_markdown,
)
from juena_core.llms_providers import build_chat_model
from juena_core.log import get_logger
from juena_core.schema.llm_models import BlabladorModelName, Provider
from juena_core.server.agent.registry import register_agent_factory
from juena_core.server.agent.runtime_model_middleware import RuntimeModelContext
from juena_core.server.database.checkpointer import get_checkpointer
from juena_core.server.database.store import get_store
from vitess_ai.agents.advanced_mode.tools import build_batch_tools
from vitess_ai.agents.delegation import with_module_delegation_boundary
from vitess_ai.agents.specialists import compile_sweep_specialists
from vitess_ai.agents.vitess_agent import VITESS_FILESYSTEM_TOOLS, project_root
from vitess_ai.mcp.connection import discover_vitess_tools, probe_server_health
from vitess_ai.retrieval import orchestrator_documentation
from vitess_ai.run import VitessGateway
from vitess_ai.state import VitessBridgeState
from vitess_ai.tools import build_vitess_tools, vitess_supervisor_middleware

logger = get_logger(__name__)

ADVANCED_MODE_AGENT_ID = "advanced_mode"
_ADVANCED_FACADE_TOOL_NAMES = (
    "inspect_thread_folders",
    "generate_monitor1d_plot",
    "generate_monitor2d_plot",
)
SUMMARIZER_PROVIDER = Provider.BLABLADOR.value
SUMMARIZER_MODEL = BlabladorModelName.GPT_OSS.value

SWEEP_TASK_DESCRIPTION = """Delegate one VITESS module's configuration to its specialist.

Give the specialist a self-contained objective: which values that module should sweep
over, in your own words, with the relevant context. It cannot see this conversation, it
cannot ask the user anything, and it owns the interpretation of its own parameters --
do not send it field names you invented or expect it to ask you for the rest.

A module that does not vary still has to be delegated to: it records one configuration
using the schema defaults. Delegate to all five before planning the sweep.

Every result arrives as a `<specialist_report>` block paired with a
`<verified_by_server>` block. The second block is written by the server from the actual
VITESS exit codes and the artifact store; it overrides anything the report claims.

Available specialist types:
{available_agents}
"""


@dataclass
class AdvancedModeResources:
    """Keep long-lived resources alive for the cached sweep graph."""

    app: CompiledStateGraph
    gateway: VitessGateway


def _advanced_facade_tools(tools: list[BaseTool]) -> list[BaseTool]:
    """Select the read-only façade tools advanced mode is allowed to expose.

    This is an allowlist rather than "everything except run_simulation". If the
    guided façade later grows another execution or maintenance tool, a sweep
    must not acquire it merely because nobody remembered to extend a denylist.
    """

    indexed: dict[str, BaseTool] = {}
    for item in tools:
        if item.name in indexed:
            raise ValueError(f"Duplicate VITESS façade tool: {item.name}")
        indexed[item.name] = item
    missing = [name for name in _ADVANCED_FACADE_TOOL_NAMES if name not in indexed]
    if missing:
        raise ValueError(
            "Advanced mode is missing required VITESS façade tools: "
            + ", ".join(missing)
        )
    return [indexed[name] for name in _ADVANCED_FACADE_TOOL_NAMES]


def build_advanced_mode_graph(
    *,
    supervisor_model: Any,
    summarizer_model: Any,
    fallback_models: list[Any],
    specialists: list[dict[str, Any]],
    tools: list[BaseTool],
    store: Any,
    backend: Any | None = None,
    checkpointer: Any = None,
) -> CompiledStateGraph:
    """Assemble the sweep orchestrator from pieces its caller has chosen."""

    middleware = build_supervisor_middleware(
        backend=backend if backend is not None else build_supervisor_backend(store),
        filesystem_tools=VITESS_FILESYSTEM_TOOLS,
        summarizer_model=summarizer_model,
        fallback_models=fallback_models,
        subagents=with_module_delegation_boundary(specialists),
        task_description=SWEEP_TASK_DESCRIPTION,
        extra=tuple(vitess_supervisor_middleware(agent_name=ADVANCED_MODE_AGENT_ID)),
    )
    documentation_tools, documentation_policy = orchestrator_documentation(
        unattended=True
    )
    return create_agent(
        model=supervisor_model,
        tools=[*tools, *documentation_tools],
        system_prompt=(
            load_markdown("vitess_ai.agents.advanced_mode", "AGENT.md")
            + "\n"
            + documentation_policy
        ),
        middleware=middleware,
        context_schema=RuntimeModelContext,
        state_schema=VitessBridgeState,
        checkpointer=checkpointer,
        store=store,
        name=ADVANCED_MODE_AGENT_ID,
    ).with_config({"recursion_limit": 1000})


async def create_advanced_mode_agent(
    provider: str,
    model: str,
) -> tuple[AdvancedModeResources, CompiledStateGraph]:
    """Build the sweep orchestrator, its five sweep specialists and the gateway."""

    await probe_server_health()
    gateway = VitessGateway(await discover_vitess_tools())

    root = project_root()
    summarizer_model = build_chat_model(
        provider=SUMMARIZER_PROVIDER,
        model=SUMMARIZER_MODEL,
        temperature=0.0,
    )
    fallback_models = build_fallback_models()
    store = get_store()

    facade = build_vitess_tools(gateway, project_root=root)
    agent = build_advanced_mode_graph(
        supervisor_model=build_chat_model(provider=provider, model=model),
        summarizer_model=summarizer_model,
        fallback_models=fallback_models,
        specialists=compile_sweep_specialists(
            project_root=root,
            gateway=gateway,
            summarizer_model=summarizer_model,
            fallback_models=fallback_models,
        ),
        tools=[
            # No `ask_user` and no `plan_simulation`: nobody is watching a sweep,
            # and its order comes from the catalog inside the batch tools.
            # `run_simulation` is absent too -- a sweep runs its plan, one run at a
            # time, through `run_batch_from_matrix`.
            *_advanced_facade_tools(facade),
            *build_batch_tools(gateway, project_root=root),
        ],
        store=store,
        checkpointer=get_checkpointer(),
    )
    logger.info("VITESS advanced mode built against project root %s", root)
    return AdvancedModeResources(app=agent, gateway=gateway), agent


register_agent_factory(ADVANCED_MODE_AGENT_ID, create_advanced_mode_agent)
