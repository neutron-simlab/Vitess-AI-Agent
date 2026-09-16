# Vitess AI Agent v2

A local VITESS simulation assistant built on `juena-core`.

## The stack

Three Compose services on one internal network, sharing one volume:

```text
browser ──127.0.0.1:9601──▶ vitess-app ──────▶ postgres
                                │
                                ├─ http://vitess-mcp:9005/mcp   (internal only)
                                ▼
                          /data/projects                 (mounted in both)
```

`vitess-mcp` runs the VITESS binaries; `vitess-app` runs the agent, the API and
the UI. **They are the same image with different commands**, which is what keeps
the file layouts on the shared volume identical. Only the UI port is published,
and only on loopback: the MCP server has no authentication of its own, so it
stays on the Compose network.

Application code never runs a VITESS binary directly. Every execution goes
through the MCP service.

## Running it

```sh
git submodule update --init --recursive   # rag/vitess-rag is a path dependency
cp env.example .env                       # then set POSTGRES_PASSWORD
docker compose up -d
docker compose exec vitess-app curl -fsS http://vitess-mcp:9005/health
```

The first build compiles VITESS from source on arm64 (a few minutes) and
downloads the prebuilt release on amd64.

`GET /health` on the MCP service answers 200 only when the five VITESS
executables resolve and the project volume is writable, and Compose holds the
application back until it does.

## Tests

```sh
uv sync
uv run pytest
```

The monitor-file fixtures under `tests/data/` were written by the real VITESS
binaries; `tests/data/README.md` says how to regenerate them.
