"""Assemble the VITESS supervisor and its five explicitly registered specialists.

This is the rebuild. The first-generation simulator was a hand-rolled graph:
1,375 lines of seven supervisor nodes, five module nodes and six routing
functions, over a `UnifiedState` whose seven methods used attribute access on a
type whose instances are dictionaries -- so they were unreachable. What the
routing functions did was pick a subagent, run it, come back and decide what is
next, which is `SubAgentMiddleware` plus `create_agent`.

**What the graph shape really held was the execution order**, and losing it is
the one way this rebuild could produce something worse: a supervisor that
configures the monitor before the guide runs a simulation that completes and is
physically wrong. So the order moved somewhere explicit and checkable --
`plan_simulation` writes it, `run_simulation` reads it back, and both ends are
server-owned.

There is no legacy fallback. Registering the old graph beside this one would
bring back the process-global registry, `InMemorySaver` and the
`restart_with_new_config` path that wiped every user's conversation state, and
a fallback whose persistence model differs from the real one is a second
architecture with a reassuring name.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

from juena_core.agents.ask_user import build_ask_user_tool
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
from vitess_ai.agents.delegation import with_module_delegation_boundary
from vitess_ai.agents.specialists import compile_module_specialists
from vitess_ai.mcp.connection import discover_vitess_tools, probe_server_health
from vitess_ai.run import VitessGateway
from vitess_ai.state import VitessBridgeState
from vitess_ai.tools import (
    build_vitess_tools,
    plan_simulation,
    vitess_supervisor_middleware,
)

logger = get_logger(__name__)

VITESS_AGENT_ID = "vitess"
SUMMARIZER_PROVIDER = Provider.BLABLADOR.value
SUMMARIZER_MODEL = BlabladorModelName.GPT_OSS.value

#: Where both containers mount the shared project volume. Deployment
#: configuration, not something a request may choose: the first-generation
#: `PUT /config/vitess` let any unauthenticated caller repoint this for every
#: user, mid-simulation.
DEFAULT_PROJECT_ROOT = "/data/projects"

SUPERVISOR_TASK_DESCRIPTION = """Delegate one VITESS module's configuration to its specialist.
Give the specialist a self-contained objective: what the user wants from this module, in
your own words, with the relevant context. It cannot see the conversation.

Delegate in the order `plan_simulation` returned, one specialist at a time, and wait for
each report before starting the next. A specialist records its module's validated
parameters itself; you never carry numbers between them.

Every result arrives as a `<specialist_report>` block paired with a
`<verified_by_server>` block. The second block is written by the server from the actual
VITESS exit codes and the artifact store; it overrides anything the report claims.

Available specialist types:
{available_agents}
"""


@dataclass
class VitessAgentResources:
    """Keep long-lived resources alive for the cached supervisor graph."""

    app: CompiledStateGraph
    gateway: VitessGateway


#: What either VITESS agent's own filesystem is for: core's per-user memory and
#: the read-only `/findings/` view. Not `execute` and not `delete`.
#:
#: Neither works here -- `SupervisorStateBackend` implements no sandbox protocol,
#: so `execute` answers with a message about a backend it does not have, and both
#: refuse any path outside `/memories/`. They are a dead affordance, and `execute`
#: is the specific one a weaker model reaches for when it decides to run VITESS
#: itself. CP4 removed both from the module specialists for the same reason; a
#: supervisor whose only route to a binary is one trusted MCP gateway has the
#: same reason and a stronger one.
VITESS_FILESYSTEM_TOOLS = ("read_file", "write_file", "edit_file", "ls", "glob", "grep")


def project_root() -> Path:
    """The shared volume, from the environment both containers already read."""
    return Path(os.environ.get("VITESS_PROJECT_PATH") or DEFAULT_PROJECT_ROOT)


def build_vitess_graph(
    *,
    supervisor_model: Any,
    summarizer_model: Any,
    fallback_models: list[Any],
    specialists: list[dict[str, Any]],
    tools: list[BaseTool],
    store: Any,
    checkpointer: Any = None,
) -> CompiledStateGraph:
    """Assemble the supervisor from pieces its caller has already chosen.

    Separated from :func:`create_vitess_agent` so that what is assembled and
    what it is assembled from are two readable things rather than one long one.
    """

    middleware = build_supervisor_middleware(
        backend=build_supervisor_backend(store),
        filesystem_tools=VITESS_FILESYSTEM_TOOLS,
        summarizer_model=summarizer_model,
        fallback_models=fallback_models,
        # Already carrying this application's delegation boundary, which returns
        # one field core's does not: the module configuration a specialist just
        # validated. `build_supervisor_middleware` applies core's boundary to
        # anything that has none, and leaves a wrapped specialist alone.
        subagents=with_module_delegation_boundary(specialists),
        task_description=SUPERVISOR_TASK_DESCRIPTION,
        # The two root hooks from 03/CP3a. Without them the answer still
        # arrives -- with no evidence block and no download button, which is the
        # failure mode worth naming because it looks like success.
        extra=tuple(vitess_supervisor_middleware()),
    )
    return create_agent(
        model=supervisor_model,
        tools=tools,
        system_prompt=load_markdown("vitess_ai.agents", "SUPERVISOR.md"),
        middleware=middleware,
        context_schema=RuntimeModelContext,
        state_schema=VitessBridgeState,
        checkpointer=checkpointer,
        store=store,
        name=VITESS_AGENT_ID,
    ).with_config({"recursion_limit": 1000})


async def create_vitess_agent(
    provider: str,
    model: str,
) -> tuple[VitessAgentResources, CompiledStateGraph]:
    """Build the supervisor, its five module specialists and the MCP gateway.

    Discovery is checked before anything is built. There is no degraded VITESS
    agent to fall back to -- without execution there is no product here -- and a
    graph cached for the process lifetime with the tools missing would be worse
    than a container that refuses to start. Compose already gates this service
    on the MCP health route, so the normal case is that the server is up.
    """

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

    agent = build_vitess_graph(
        supervisor_model=build_chat_model(provider=provider, model=model),
        summarizer_model=summarizer_model,
        fallback_models=fallback_models,
        specialists=compile_module_specialists(
            project_root=root,
            gateway=gateway,
            summarizer_model=summarizer_model,
            fallback_models=fallback_models,
        ),
        tools=[
            build_ask_user_tool(VITESS_AGENT_ID),
            plan_simulation,
            *build_vitess_tools(gateway.raw_tools, project_root=root),
        ],
        store=store,
        checkpointer=get_checkpointer(),
    )
    logger.info("VITESS supervisor built against project root %s", root)
    return VitessAgentResources(app=agent, gateway=gateway), agent


register_agent_factory(VITESS_AGENT_ID, create_vitess_agent, set_as_default=True)
