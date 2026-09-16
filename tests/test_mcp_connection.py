"""How the application reaches the server, and how it fails when it cannot.

The discovery tests run against the real server object rather than a mock, so
what is checked is the tool set this repository actually ships. The transport
differs -- in the container it is HTTP -- but the tool names and schemas do not.
"""

from __future__ import annotations

import asyncio
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastmcp import FastMCP
from juena_core.mcp import MCPUnavailableError

from vitess_ai.mcp.connection import (
    DEFAULT_BASE_URL,
    TOOL_NAMES,
    discover_vitess_tools,
    health_url,
    mcp_url,
    probe_server_health,
)
from vitess_ai.mcp.server import mcp


def _closed_port() -> int:
    """A port nothing is listening on, found by letting the OS pick and closing."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class _Answering(BaseHTTPRequestHandler):
    status = 503

    def do_GET(self) -> None:  # noqa: N802 - the stdlib spells it this way
        body = b'{"status": "unhealthy"}'
        self.send_response(self.status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


def test_discovery_finds_the_four_tools_the_application_needs() -> None:
    discovered = asyncio.run(discover_vitess_tools(mcp))

    assert sorted(tool.name for tool in discovered) == sorted(TOOL_NAMES)


def test_a_server_that_lost_a_tool_fails_loudly() -> None:
    """Not silently one capability short.

    VITESS execution is the product here, so a half-built agent is worse than a
    container that refuses to start. juena-chatbot's Context7 is the opposite
    case and takes the opposite branch in the same core module.
    """
    partial = FastMCP("Partial")

    @partial.tool
    async def run_simulation() -> str:
        return "ok"

    with pytest.raises(MCPUnavailableError, match="missing tool"):
        asyncio.run(discover_vitess_tools(partial))


def test_both_routes_are_derived_from_one_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    """So the health check and the MCP endpoint cannot point at different servers."""
    monkeypatch.setenv("VITESS_MCP_BASE_URL", "http://elsewhere:9999/")

    assert mcp_url() == "http://elsewhere:9999/mcp"
    assert health_url() == "http://elsewhere:9999/health"


def test_the_default_target_is_the_compose_service_not_a_host_port() -> None:
    """The server is on the internal network; the host has no route to it."""
    assert DEFAULT_BASE_URL == "http://vitess-mcp:9005"
    assert "127.0.0.1" not in DEFAULT_BASE_URL
    assert "localhost" not in DEFAULT_BASE_URL


def test_an_unreachable_server_raises_rather_than_being_tolerated() -> None:
    port = _closed_port()

    with pytest.raises(MCPUnavailableError, match="unreachable"):
        asyncio.run(probe_server_health(f"http://127.0.0.1:{port}/health"))


def test_a_server_that_answers_unhealthy_is_not_accepted() -> None:
    """Answering on the port is not the same as being able to run VITESS."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Answering)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/health"
        with pytest.raises(MCPUnavailableError, match="not healthy"):
            asyncio.run(probe_server_health(url))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
