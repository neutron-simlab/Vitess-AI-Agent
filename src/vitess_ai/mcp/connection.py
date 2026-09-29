"""How the application reaches the VITESS MCP server.

This is the other half of this package: :mod:`vitess_ai.mcp.server` runs inside
the ``vitess-mcp`` container, and this file runs inside the application. They
share the data shapes in ``payloads`` and nothing else.

**Either the server's tools are found, or the app refuses to start.**
juena-chatbot does the opposite for Context7 -- if that optional server cannot
be reached, the app simply has one feature fewer -- and the difference is on
purpose: without running VITESS there is no product here, so an agent built
without those tools would be worse than a container that refuses to start.
Docker Compose already starts this service only after the MCP server passes its
health check, so normally the server is up before anything asks.

There is no middle option. Adding the tools anyway is not possible: asking the
server for its tools is how their descriptions are obtained, so when that fails
there is nothing to add.

``langchain.mcp`` is imported in exactly one place in the whole stack --
``juena_core.mcp`` -- and this file goes through it. So if that beta package
moves, one file needs fixing rather than a search across two applications.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Mapping

import httpx
from juena_core.mcp import MCPUnavailableError, discover_tools

if TYPE_CHECKING:
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
    expected = set(TOOL_NAMES)
    missing = sorted(expected - discovered)
    unexpected = sorted(discovered - expected)
    if missing or unexpected:
        differences = []
        if missing:
            differences.append(f"missing tool(s): {', '.join(missing)}")
        if unexpected:
            differences.append(f"unexpected tool(s): {', '.join(unexpected)}")
        raise MCPUnavailableError(
            "VITESS MCP server tool set mismatch: " + "; ".join(differences)
        )
    return tools
