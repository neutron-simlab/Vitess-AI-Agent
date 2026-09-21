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

The four tools advertised by that service are also never bound directly to a
model: their schemas contain the conversation id, the simulation id and
validated module state. `vitess_ai.tools.build_vitess_tools()` wraps them in
application façades whose model-visible schemas contain only a human run name
or plot filename. The façades read identity and state through `ToolRuntime`,
validate MCP `structuredContent`, verify every claimed file against the app's
own shared-volume mount, and register deliverable files with `ArtifactStore`.
`vitess_supervisor_middleware()` then attaches those files and the
server-authored `<verified_by_server>` block to the root answer.

## Running it

```sh
git submodule update --init --recursive   # rag/vitess-rag is a path dependency
cp env.example .env                       # then set POSTGRES_PASSWORD and a model key
./vitess install                          # once: add the launcher to ~/.local/bin
vitess up                                 # build and start Postgres, MCP, API, and UI
vitess health
```

After installation, `vitess up`, `vitess down`, `vitess logs`, and
`vitess health` work from any directory. Run `vitess help` for the full list.

The first build compiles the same pinned VITESS source revision on every
architecture (a few minutes). This keeps the binaries aligned with the monitor
formats exercised by the test fixtures.

Use `./vitess index-docs` once, after the stack is running, to embed the bundled
manual. This spends embedding quota and therefore is never done implicitly at
startup. If it has not been run, the documentation tools remain present and
answer `RAG_UNAVAILABLE` instead of silently disappearing.

Documentation queries specifically require `BLABLADOR_API_KEY`: the persisted
index was built with the configured Blablador embedding model. An OpenAI key
may run the chat model, but it cannot embed a query against this collection.

To reuse the first-generation checkout's existing index instead, migrate it
once while the v2 application is stopped. The destination must be empty; do
not merge two Chroma databases. SQLite needs to create journal files even for
queries, so the copied files must belong to the image's uid 10001.

```sh
docker compose stop vitess-app
docker run --rm \
  -v vitess-ai-agent_vitess-rag:/src:ro \
  -v vitess-ai-chroma:/dst \
  alpine sh -c 'test -f /src/chroma_db/chroma.sqlite3 && test -z "$(find /dst -mindepth 1 -maxdepth 1 -print -quit)" && cp -a /src/chroma_db/. /dst/ && chown -R 10001:10001 /dst'
docker compose up -d vitess-app
```

The source volume name is the default Compose name from `Vitess-AI-Agent`; if
that stack used a different project name, substitute its actual volume from
`docker volume ls`. After a future re-index, `collections.config_json_str` in
`chroma.sqlite3` must remain `{}`: Chroma 1.5.9 cannot reopen this copied index
when that field names an embedding function unknown to its registry.

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
