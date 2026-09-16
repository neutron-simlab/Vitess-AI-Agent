"""How the application reaches the VITESS MCP server.

The other half of this package: :mod:`vitess_ai.mcp.server` runs inside the
``vitess-mcp`` container, and this module runs inside the application. They
share the payload models and nothing else.

**Discovery succeeds or construction fails.** juena-chatbot's Context7 does the
opposite -- an unreachable optional server means one capability fewer -- and the
difference is deliberate: without VITESS execution there is no product here, so
an agent built with the tools missing would be a worse outcome than a container
that refuses to start. Compose already gates this service on the MCP health
route, so the normal case is that the server is up before anything asks.

There is no third option. Registering the tools anyway is not implementable:
discovery is how their schemas are obtained, so there is nothing to register
when it fails.

``langchain.mcp`` is imported in exactly one place in the stack --
``juena_core.mcp`` -- and this module goes through it. That is why a beta
namespace moving is one module to fix rather than a search across two
applications.
"""

from __future__ import annotations

import os
from typing import Mapping

import httpx
from juena_core.mcp import MCPUnavailableError, discover_tools
from langchain_core.tools import BaseTool

__all__ = [
    "DEFAULT_BASE_URL",
    "TOOL_NAMES",
    "health_url",
    "mcp_url",
    "probe_server_health",
    "discover_vitess_tools",
]

#: The Compose service name, not a host port: the server is on the internal
#: network only.
DEFAULT_BASE_URL = "http://vitess-mcp:9005"

#: What the server offers. Asserted after discovery so that a server which
#: started but lost a tool is caught here rather than when a model reaches for
#: one that is not there.
TOOL_NAMES = (
    "generate_monitor1d_plot",
    "generate_monitor2d_plot",
    "inspect_thread_folders",
    "run_simulation",
)


def base_url(environment: Mapping[str, str] | None = None) -> str:
    """The server's root URL. One variable, so the two routes cannot disagree."""
    env = os.environ if environment is None else environment
    return (env.get("VITESS_MCP_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def mcp_url(environment: Mapping[str, str] | None = None) -> str:
    return f"{base_url(environment)}/mcp"


def health_url(environment: Mapping[str, str] | None = None) -> str:
    return f"{base_url(environment)}/health"


async def probe_server_health(
    url: str | None = None, *, timeout_seconds: float = 5.0
) -> None:
    """Raise unless the server answers its health route with 200.

    Called once before the agent is built. It is a cheaper and clearer failure
    than a discovery timeout, and it distinguishes "not running" from "running
    but its VITESS mount is missing" -- the body says which.
    """
    target = url or health_url()
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.get(target)
    except httpx.HTTPError as exc:
        raise MCPUnavailableError(f"VITESS MCP server unreachable at {target}: {exc}") from exc
    if response.status_code != 200:
        raise MCPUnavailableError(
            f"VITESS MCP server is not healthy ({response.status_code}): {response.text}"
        )


async def discover_vitess_tools(target: object | None = None) -> list[BaseTool]:
    """Discover the server's tools, raising if any of the four is missing."""
    tools = await discover_tools(target if target is not None else mcp_url(), label="VITESS")
    discovered = {tool.name for tool in tools}
    missing = sorted(set(TOOL_NAMES) - discovered)
    if missing:
        raise MCPUnavailableError(
            f"VITESS MCP server is missing tool(s): {', '.join(missing)}"
        )
    return tools
