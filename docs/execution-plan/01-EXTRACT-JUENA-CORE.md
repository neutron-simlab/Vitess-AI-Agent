# Plan 01 — Extracting juena-core

> **Goal:** a `juena_core` package that imports, has its own tests, and knows nothing
> about JüNA or VITESS.
>
> **This plan does not edit `src/juena/`.** That is plan 02.
>
> **Depends on:** 00. **Unblocks:** 02.

## Before you start

Read `README.md` and `00-BOUNDARY.md` in this directory. 00 is the decision table this
plan executes; do not re-derive it.

Layout on disk:

```
JueNA_knowledge_base/
├── juena-chatbot/     the source. Untouched by this plan
├── juena-core/        this repository. New
└── juena-rag/         the precedent — its docs/execution-plan/ is the style
```

**Record the baseline before CP1 copies implementation from juena-chatbot.** It is the
only starting point plan 02 can be checked against. CP0a, CP0b and CP0 may proceed while
unrelated chatbot work is being completed because they create only repository scaffolding,
validate dependencies and define stubs; they do not copy application implementation.
CP1 must not begin until this gate passes:

```bash
cd juena-chatbot
git status --short          # must be clean
./juena test                # record the pass count
./juena test-integration    # record the pass count
```

Write both numbers and the source commit SHA down in this file under *What actually
landed* for CP0. Plan 02 uses them later, but CP1 fixes the source snapshot they describe.

### `pyproject.toml`

Follows juena-rag's shape:

```toml
requires-python = ">=3.11, <4.0"
dependencies = [
  # Bounds below are the versions validated together in CP0b.
  # Re-validate and move them deliberately; do not widen them to "make it install".
  "langchain[openai]>=1.4,<2",
  "langgraph>=1.2,<2",
  "deepagents>=0.7.13,<0.8",
  "fastapi", "uvicorn[standard]", "sse-starlette", "httpx", "httpx-sse",
  "pydantic", "typing-extensions>=4.12",
  "langgraph-checkpoint-postgres", "psycopg[binary,pool]",
  "sqlalchemy[asyncio]", "pyyaml", "pillow",
]

[project.optional-dependencies]
ui  = ["streamlit>=1.53.0"]
mcp = ["langchain[mcp]>=1.4,<2"]   # built-in; the standalone adapter is retired
```

`>=3.11` because core must run on the lower of the two applications' floors.

Everything not listed above is an optional extra. A colleague installing `juena-core` to
build a third agent must not acquire `pysaml2`, `podman`, `chromadb` or `streamlit`.

### The dependency policy

**Recent stable versions, deliberately upgraded and tested together — not permanent old
pins, and not unbounded ranges that change silently during a Docker rebuild.**

1. **Select the latest stable LangChain-family releases at execution time.** As of
   2026-09-15 that is `langchain 1.4.0` (which is also where MCP now lives),
   `langgraph 1.2.11` and `deepagents 0.7.13`. Check again on the day; these move.
2. **Validate them as one compatibility set.** Middleware, state schemas, MCP façades and
   subagent contracts are coupled — a set is the unit that works, not a package.
3. **Commit the resolved versions in `uv.lock`**, so Docker and both applications build
   the same thing.
4. **Declare bounded ranges in `pyproject.toml`, based on what was actually validated.**
5. **Move the bounds deliberately**, re-running CP0b. Widening a bound because an install
   failed is how an unvalidated set arrives in production.

> **`langchain-mcp-adapters` is retired. Do not install it.**
> LangChain 1.4.0 (released 2026-09-01) ships MCP inside the library, in the
> `langchain.mcp` namespace built on FastMCP, and it **replaces** the standalone package.
> Install it with the `mcp` extra.
>
> This supersedes every MCP instruction in revisions 2 and 3, including a finding those
> revisions spent two review rounds arguing about — that `MultiServerMCPClient.__aenter__`
> raises. It does, and it no longer matters: **`MCPAdapter` *is* an async context
> manager**, by design. The lifecycle inverts rather than being refined.
>
> **`langchain.mcp` is beta.** Importing from it raises `LangChainBetaWarning` once per
> process, and the API may change. That is accepted deliberately — the alternative is a
> package its maintainers have stopped maintaining — and the cost is contained by keeping
> every import of it inside `juena_core.mcp` (CP5), so a breaking change is one module to
> fix rather than two applications.

Authoritative upstream references for CP0b:

- [LangChain's migration guide from `langchain-mcp-adapters`](https://docs.langchain.com/oss/python/migrate/langchain-mcp-adapters)
- [LangChain's built-in MCP tool contract](https://docs.langchain.com/oss/python/langchain/mcp/tools)
- [LangChain's runtime context and execution-identity contract](https://docs.langchain.com/oss/python/langchain/runtime)
- [FastMCP's current stable release](https://pypi.org/project/fastmcp/)

---

## Checkpoint 0a — bootstrap the repository

**The very first step, because nothing else creates it.** Every later checkpoint assumes
`juena-core/` exists; three revisions of this plan assumed it into being.

```bash
cd JueNA_knowledge_base
mkdir juena-core && cd juena-core
git init
uv init --package --name juena-core     # or write pyproject.toml by hand
```

What lands: the `pyproject.toml` above, `src/juena_core/__init__.py`, a `.gitignore`
covering `.venv/`, `__pycache__/` and `dist/`, plus `scripts/`, `tests/`, and an initial
commit. Do not blanket-ignore `docs/`: architecture and execution documents are source
material and must be versioned wherever they live.

No remote (D7). The sibling path dependency resolves to `../juena-core`, so the directory
name matters and is not negotiable without editing both applications.

**Done when**, from inside the newly created repository, `git log --oneline` shows one
commit and `git status --short` is empty — the clean-tree condition 01/CP6 requires
before any accepted build.

---

## Checkpoint 0b — the dependency set, before anything is built

**Runs before CP0.** Every contract in these plans rests on library behaviour, and three
separate revisions of this document have already described that behaviour wrongly. This
checkpoint replaces reasoning about the libraries with a script that exercises them.

Resolve the latest stable set, then prove each coupled contract in a scratch project:

| What | Passes when |
|---|---|
| **MCP discovery** | `async with MCPAdapter(url) as adapter: await adapter.list_tools()` returns the expected tools against a throwaway FastMCP server. The deployed VITESS integration has one server and uses its HTTP URL directly, preserving the server's tool names. If a multi-server target is tested, its config is the `{"mcpServers": {...}}` shape and transport is inferred — there is no `transport` key |
| **Adapter lifetime** | a discovered tool succeeds after its `async with MCPAdapter(...)` discovery block exits, confirming the current source contract that the tool retains and re-enters its FastMCP client. If it does not, stop and amend CP5 — **measure it; do not reason around it** |
| **Reconnection** | a tool call succeeds after the MCP server restarts, without rebuilding the agent |
| **Middleware sees runtime** | a `@wrap_tool_call` middleware reads all three channels deliberately: state from `request.state`, public execution identity from `request.runtime.execution_info`, and typed application context from `request.runtime.context` when `context_schema` and invocation `context` are supplied |
| **Middleware returns `Command`** | `wrap_tool_call` returning `Command(update=...)` writes state *and* the tool message. Its signature is `(request: ToolCallRequest, handler) -> ToolMessage \| Command` |
| **`structured_content`** | `message.artifact["structured_content"]` carries a FastMCP tool's `structuredContent` — an `MCPToolArtifact`, reachable without parsing model-visible text |
| **Façade schemas** | each façade tool's `args_schema` contains **no** `thread_id`, `simulation_run_id`, `module_results` or `run_specs` (03/CP3a) |
| **Beta warning** | `LangChainBetaWarning` is raised and handled deliberately — not suppressed globally, and not turned into an error by juena's `filterwarnings` |
| **deepagents signatures** | `create_deep_agent(...)` accepts the kwargs 03/CP5 passes; the subagent dict's `middleware` key still behaves |
| **Graph + checkpointing** | a two-node graph compiles and round-trips through `AsyncPostgresSaver` against a real Postgres |

**Done when** the nine measurable dependency checks pass, the façade-schema check is
carried forward as a hard done-when condition for 03/CP3a, `uv.lock` is committed, and
the validated versions are written into *What actually landed* — as the record of what
the bounds mean. A checkpoint cannot test an interface that does not exist yet.

**If one fails**, that is a finding, not a blocker to route around: record it, and either
choose the last release where it holds or amend the contract that depended on it. Do not
widen a bound and move on.

### What actually landed

**Resolved 2026-09-15.** `langchain==1.4.0`, `langchain-core==1.6.3`,
`langgraph==1.2.11`, `langgraph-checkpoint-postgres==3.1.2`, `deepagents==0.7.14`
(above the `>=0.7.13,<0.8` floor validated — the plan's 0.7.13 reference was the
latest at drafting time, not a hard requirement), `fastmcp==4.0.3`, `mcp==2.2.0`,
`pydantic==2.13.5`, `sqlalchemy==2.0.53`. Committed in `uv.lock`. `fastmcp` and
`pytest`/`pytest-asyncio` are dev-only (`[dependency-groups] dev`) — the base
package does not depend on `fastmcp`; `langchain[mcp]` already pulls it in as
*its own* transitive dependency, which is exactly why core's test harness
declares it explicitly rather than importing it by luck.

Permanent tests in `tests/cp0b/`, run against a throwaway FastMCP server
(`tests/cp0b/scratch_server.py`) and, for row 10, a throwaway Postgres
(`docker compose -f tests/compose.postgres.yml up -d --wait`):

| # | Check | Result |
|---|---|---|
| 1 | MCP discovery | **Pass.** `async with MCPAdapter(target)` discovers `{"echo", "add"}` both from an in-process `FastMCP` instance and from a bare URL string |
| 2 | Adapter lifetime | **Pass, confirmed.** A discovered tool succeeds after the `async with` block exits — the lifecycle inversion the plan text already asserted, now measured rather than reasoned about |
| 3 | Reconnection | **Pass.** The *same* tool object, discovered before a server restart, succeeds again after the server process is killed and a fresh one started on the same port — no new `MCPAdapter`, no new `list_tools()` |
| 4 | Middleware sees runtime | **Pass, with two corrections.** The earlier test omitted `context_schema` and invocation `context`, so `request.runtime.context is None` was expected and did not disprove typed context. The permanent test now supplies both and asserts that context is present. It also asserts `request.runtime.execution_info.thread_id`, the current public execution-identity API. `runtime.config["configurable"]["thread_id"]` contains the matching checkpoint key, but the façade need not depend on that nested representation. Principal and other typed application values remain in `.context` |
| 5 | Middleware returns `Command` | **Pass, with a finding.** The test asserts both parts of the contract: the tool message remains in `messages`, and a declared state field is updated. A separate negative regression proves that `Command(update={...})` silently drops an undeclared key. `execution_events` and every similar channel must therefore be declared wherever its writer attaches |
| — | (unlisted) sync vs async hook | **Finding, not in the original table.** A permanent negative regression proves that a `@wrap_tool_call` function defined *sync* raises `NotImplementedError` under `agent.ainvoke()`/`astream()`. Every wrap-tool middleware juena_core defines must be async, matching the server's all-async SSE design |
| 6 | `structured_content` | **Pass.** `message.artifact["structured_content"]` carries the FastMCP tool's `structuredContent` exactly (`{"total": 5}` for a Pydantic-model return) |
| 7 | Façade schemas | **Deferred, not a compatibility check.** No façade tool exists yet — nothing to assert until 03/CP3a builds one. Left as that checkpoint's own done-when condition |
| 8 | Beta warning | **Pass.** Importing `langchain.mcp` raises `LangChainBetaWarning`; permanent test guards against a future release silently dropping it (which would mean the namespace left beta without this plan noticing) |
| 9 | deepagents signatures | **Pass, run end to end.** `create_deep_agent` accepts the exact kwargs `vitess_ai/agents/advanced_mode/agent.py` passes (`name`, `model`, `tools`, `middleware`, `subagents`, `backend`, `checkpointer`, `system_prompt`); a full delegation turn through the `task` tool confirms a subagent dict's `middleware` key actually executes during delegation, not just that the shape type-checks |
| 10 | Graph + checkpointing | **Pass.** A two-node graph round-trips through `AsyncPostgresSaver` against a real Postgres; state reloads correctly from a second saver instance against the same DSN |

Nine of ten contract rows are measurable now and pass. The suite contains eleven test
cases (`uv run pytest tests/cp0b -q` — `11 passed`), including explicit negative
regressions for an undeclared `Command` update and a sync `@wrap_tool_call`. The tenth
row (façade schemas) has nothing to assert against yet and is correctly deferred rather
than faked. Two things surfaced that the original table did not anticipate — the
sync/async split on `@wrap_tool_call`, and the separation between typed context and
public execution identity — both are recorded above and guarded by tests that fail on a
future regression.

---

## Checkpoint 0 — the package imports, and the import rule is executable

The smallest step, and the only one that makes everything after it checkable.

Create `src/juena_core/__init__.py` and the module tree from 00 as **stubs** — every
name defined, nothing implemented. Then write the check that governs the whole
repository.

`juena-core/scripts/check-imports.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
if grep -rnE '^\s*(from|import) (juena|vitess_ai|juena_rag)\b' src/ tests/; then
    echo "juena_core imported an application. The dependency runs one way." >&2
    exit 1
fi
echo "import direction ok"
```

Two details that matter:

- **`juena\b` does not match `juena_core`.** In a regular expression `\b` is a word
  boundary, and `_` counts as a word character, so `juena_core` has no boundary after
  `juena`. The check is exact and needs no exclusion list.
- **`tests/` is included deliberately.** A test that pulls the chatbot in is the way
  this rule actually gets broken, and it would otherwise go unnoticed until someone
  installed core on its own.

**Then write the same check properly, as a test.** The shell version is the fast gate
for a commit hook; the test version is the one that cannot be fooled. Walk `src/` with
`ast.parse`, collect every `ast.Import` and `ast.ImportFrom`, and assert no module root
is a forbidden application — matching the bare name **and** any submodule, so `import
juena` is rejected as well as `from juena.core import x`:

```python
# tests/test_import_boundary.py
for path in (ROOT / "src").rglob("*.py"):
    for node in ast.walk(ast.parse(path.read_text())):
        ...  # assert the module root is not a forbidden application
```

`grep` misses an import split across lines by parentheses, and it reads a matching string
inside a docstring as a violation. The AST does neither. **Keep both** — they fail at
different times and cost nothing.

**The check runs in both directions.** Core must not import an application, *and* each
application's router must expose the route set `BaseAgentClient` calls (decision 10).
A client method with no matching route is a 404 that nothing catches until someone
clicks it. That second half lives in each application's suite, not here.

**Done when:**

```bash
uv run python -c "import juena_core; print(sorted(juena_core.__all__))"
./scripts/check-imports.sh
```

both succeed.

### What actually landed

**Completed 2026-09-15.** The complete 54-module skeleton imports, every declared
top-level name exists, and the executable import boundary covers both `src/` and
`tests/`. The AST regression includes bare imports, submodules split across lines,
`juena_core` itself and import-looking docstring text. The checkpoint gates report:

```text
uv run python -c "import juena_core; print(sorted(juena_core.__all__))"  # pass
./scripts/check-imports.sh                                               # import direction ok
uv run pytest tests/test_import_boundary.py tests/test_stub_contracts.py -q
# 73 passed
```

Review corrected three contracts in the interrupted skeleton:

- `BaseAgentClient` remains synchronous, including synchronous generator methods for
  `stream` and `resume_stream`; the first draft incorrectly made every method async.
- The UI `Chat` carries required `agent_id`, matching the persistence contract in CP3.
- The shared registry starts with `DEFAULT_AGENT = None`, and `initialize_client`
  requires an application-owned `agent_id`. Core no longer silently names JüNA as the
  default application.

**Observed chatbot baseline before CP1:** at source commit `e4a5eb3`, `./juena test`
reported **452 passed, 5 skipped** and `./juena test-integration` reported **16 passed**.
This is explicitly a dirty-checkout observation, not the clean reproducible baseline the
gate asked for: `env.example` and `juena` were modified and `.claude/` was untracked.
The seven files copied by CP1 were individually checked and matched `e4a5eb3` exactly,
so the extraction source itself is identifiable. Plan 02 must still rerun both baselines
from a clean chatbot checkout before judging the cutover.

---

## Checkpoint 1 — configuration and logging

This is first because **importing any `juena` module today loads `.env` and can
raise**, and copying that structure into a shared package would make `import
juena_core` fail on a laptop with no `.env`.

The chain, verified:

- `src/juena/core/config.py:394` is `global_config = Config.initialize()`, at module
  scope.
- `initialize()` calls `validate_required()`, which raises `ValueError` when a provider
  key is missing.
- `src/juena/core/log.py:11` does `from juena.core.config import Config` at module
  level.
- `get_logger` is imported by nearly every module in the package.

So: import anything, and you have loaded and validated configuration.

### What lands

**`juena_core/config.py`** — a frozen `CoreSettings` dataclass carrying the 25 fields
listed in 00, including `BIND_HOST` and `API_PUBLISHED` from decision 17, plus:

```python
def configure(settings: CoreSettings) -> None: ...
def settings() -> CoreSettings:
    # raises RuntimeError("juena_core.configure() has not been called")
```

**No `os.getenv`. No `load_dotenv`. No validation that prints.** Reading the environment
is the application's job.

**`juena_core/log.py`** — identical to `juena/core/log.py`, except `_get_log_level(None)`
reads `settings().LOG_LEVEL` **at call time**, and falls back to `"INFO"` when
`configure()` has not run yet. A logger must never be the thing that refuses to start.

**`juena_core/llms_providers.py`** — `get_config()` becomes `settings()`. The tests that
already patch that seam move with it.

**`juena_core/schema/`** — `server.py`, `llm_models.py`, `agents.py`,
`upload_limits.py`, `interrupts.py` (the generic half of `schema/sandbox.py`, per 00).
`CreateChatInput.agent_id` is established here with the rest of the wire schema; CP3
then makes persistence and route authorization enforce it as one coordinated change.

**Watch for `repo_root()`.** `juena/core/paths.py` walks up from `__file__` looking for
a `pyproject.toml`; from inside an installed package that finds the wrong directory or
nothing. Core takes `LOG_DIR`, `ARTIFACT_ROOT` and every other root from
`CoreSettings`. Do not port `repo_root()` into core.

**Done when:**

```bash
env -i PATH="$PATH" uv run python -c \
  "import juena_core.log, juena_core.schema.server, juena_core.llms_providers"
```

imports successfully with an **empty environment** and no `.env` file anywhere.

That is the property the current package does not have, and it is the whole point of
this checkpoint. `env -i` starts a command with no environment variables at all.

### What actually landed

**Completed 2026-09-15 in `juena-core` commit `c85aa9c`.** CP1 replaces the configuration,
logging, provider and schema stubs with working implementations:

- `CoreSettings` has the complete 25-field boundary and is frozen. `configure()` is
  idempotent for an equal value but refuses a different second process configuration,
  preventing cached models and later process-level resources from retaining stale keys.
  The package top level exports `CoreSettings`, `configure` and `settings`.
- `config.py` contains no environment or dotenv access. Logging reads `LOG_LEVEL` only
  when configuring a logger and falls back to `INFO` before application configuration.
- `llms_providers.py` now uses `settings()` and retains cached LangChain model
  construction and the measured Blablador context profiles. A new regression caught an
  inherited bug: Blablador identifiers contain commas, so the old comma split corrupted
  a configured MiniMax identifier. Filtering now matches complete known identifiers at
  list boundaries.
- The server, model, agent and generic interrupt schemas are implemented. Mutable Pydantic
  container defaults use factories. `CreateChatInput` requires `agent_id` now; CP3 still
  owns the corresponding database and authorization change.
- Upload defaults remain available to shared UI code as immutable values, while
  `is_text_readable_filename` and `validate_attachments` accept application-owned suffix
  sets and `validate_attachments` accepts application-owned byte/file limits. A permanent
  test exercises VITESS-like `.dat` and `.h5` policy without changing core globals.
- The unused direct `python-dotenv` dependency was removed. `typing-extensions>=4.12` is
  direct because Python 3.11 Pydantic schemas must import `TypedDict` from it. `uv.lock`
  was regenerated without changing the validated LangChain-family versions.

The gates, from a frozen lock:

```text
env -i PATH="$PATH" uv run python -c \
  "import juena_core.log, juena_core.schema.server, juena_core.llms_providers"
# pass, no output

uv run --frozen --group dev pytest \
  tests/test_config_and_log.py tests/test_cp1_imports.py \
  tests/test_llms_providers.py tests/test_schemas.py \
  tests/test_stub_contracts.py tests/test_import_boundary.py -q
# 101 passed

uv run --frozen --group dev pytest tests -q
# 112 passed, 1 expected LangChain MCP beta warning

./scripts/check-imports.sh
# import direction ok
```

The full run used the repository's real Postgres service and the existing real MCP
round trips. The temporary Postgres service was removed after the run. `repo_root()` was
not copied.

---

## Checkpoint 2 — the agent kit

### What lands

`agents/ask_user.py`, `agents/loop_guard.py`, `agents/findings.py`,
`agents/backends.py`, `agents/delegation.py`, `agents/specialist_runtime.py`,
`agents/specialist_outcome.py`, plus `artifacts.py`, `runtime_context.py`, and the new
`build_supervisor_middleware`.

**Four edits, and they are the point of the checkpoint.**

**1. `specialist_outcome.py` stops importing `juena.sandbox`.**
Today it imports `juena.sandbox.artifacts.get_artifact_store` and
`juena.sandbox.runtime._context_value`. After:

- `_executions(state)` reads `state["execution_events"]` and validates each entry
  against `juena_core.schema.interrupts.ExecutionEvidence`.
- `_identity(runtime)` uses `juena_core.runtime_context._context_value`.
- `_own_artifacts` calls `juena_core.artifacts.get_artifact_store()`.

`execution_events` is a plain state channel. juena-chatbot's sandbox backend writes it;
v2's MCP wrapper writes it. **One channel name, two writers** — no protocol class, no
injected reader.

**2. `specialist_runtime.py` stops importing `SandboxExecutionMiddleware` and
`requires_execution_approval`.**
`build_specialist_middleware` gains `execution_middleware: Sequence = ()` and
`interrupt_on: dict | None = None`, replacing the `enable_execution_approval: bool`
flag. juena-chatbot passes its two; v2 passes nothing.

> **Keep the `unattended` coupling intact.** `ask_user_bound=not unattended` and the
> absent execution backend must keep moving together. Dropping `ask_user` while leaving
> the execution tool mounted is how you run commands with nobody to approve them.

**3. `build_supervisor_middleware` is written**, per 00's decision, with the single
`extra=` splice point and a docstring explaining where it splices and why.

**4. The root execution-evidence pair is written** (00, decision 15). 03/CP3a depends on
both existing, and an earlier revision referenced them from plan 03 without ever
scheduling them here:

- **`ExecutionEvidenceMiddleware`** — reads the `execution_events` channel and appends the
  server-authored `<verified_by_server>` block to the **root** response.
  `SpecialistOutcomeMiddleware` cannot do this: it is installed inside
  `build_specialist_middleware` (`specialist_runtime.py:249`) and runs within specialists
  only. Factor the composition logic out of it rather than writing it twice.
- **`ArtifactMessageMiddleware`** moves into core alongside it, out of juena's sandbox
  package. It is already generic; it lived there by accident of history.

**`execution_events` is declared here, with its lifetime settled.** A `PrivateStateAttr`
with a list reducer, because several modules in one pipeline each append.

> **A list reducer on a checkpointed root graph accumulates forever.** The supervisor's
> state persists across turns, so with no boundary, turn five's answer re-reports the
> executions of turns one to four — as fresh evidence, inside a `<verified_by_server>`
> block, which is the one place in this system that must never overstate what happened.
>
> **Settle it at declaration time, not later:** each entry carries the `graph_run_id` it
> belongs to (00, decision 16), and `ExecutionEvidenceMiddleware` reports only entries
> from the current invocation. The channel may keep history; the *block* is scoped to this
> turn. Test with two consecutive executing turns, asserting the second answer names only
> its own.

**Done when:**

```bash
uv run pytest tests/ -q          # the tests moved in this checkpoint pass
./scripts/check-imports.sh

uv run python - <<'PY'
from juena_core.agents.specialist_runtime import build_supervisor_middleware
print([type(m).__name__ for m in build_supervisor_middleware(...)])
PY
```

and the printed order matches `juena_agent.py`'s stack **exactly**:

```
RepeatedToolCallMiddleware, FilesystemMiddleware, MemoryMiddleware,
SubAgentMiddleware, _DeepAgentsSummarizationMiddleware, PatchToolCallsMiddleware,
<extra…>, RuntimeModelMiddleware,
ModelFallbackMiddleware, ModelRetryMiddleware, ToolRetryMiddleware,
ModelCallLimitMiddleware, ToolCallLimitMiddleware, ToolCallLimitMiddleware
```

**Turn that assertion into a permanent test.** Middleware order is nesting order, not a
list of independent plugins — a reorder changes model behaviour silently, and this test
is the only thing that would catch it.

### What actually landed

Implemented in core commit `a97b3c1` (`feat: extract the shared agent kit`).

- The seven agent-kit modules, `ArtifactStore`, and the runtime-context helper are now
  working core implementations. `GUARD_FLAG = "juena_repeated_tool_call"` remains
  unchanged for checkpoint compatibility, while application imports and sandbox-specific
  naming were removed.
- `build_specialist_middleware` accepts the application-owned
  `execution_middleware`/`interrupt_on` pair. A partial pair is rejected, and unattended
  specialists reject both while omitting the `ask_user` limiter.
- `build_supervisor_middleware` owns the canonical stack and its single `extra=` splice
  point. The memory prompt override lives here, not on `build_supervisor_backend`: the
  middleware is the component that consumes the prompt.
- `ExecutionEvidence` now requires `graph_run_id`. `execution_events` is a private
  list-reduced state channel, and root evidence is filtered by
  `runtime.execution_info.run_id`. A real checkpointed two-turn agent test proves the
  second response cannot re-report the first turn's execution.
- Root artifact evidence resolves the event's server-authored artifact ids from the
  store. This remains correct regardless of whether `ArtifactMessageMiddleware` has
  already claimed the in-memory delivery queue.

Two plan assumptions were corrected from measured library behavior:

1. Deep Agents 0.7.14's summarization factory returns
   `_DeepAgentsSummarizationMiddleware`, not `SummarizationMiddleware`. The permanent
   class-order test asserts the resolved implementation's actual name and position.
2. LangGraph's public graph-invocation id is `runtime.execution_info.run_id`.
   `Runtime.config` does not expose top-level `run_id`; CP2's first real two-turn run
   caught the distinction.

Verification against the committed tree:

```text
focused CP2 plus schema suite     76 passed
full frozen-lock suite           187 passed, 1 expected LangChain MCP beta warning
clean-environment CP2 imports    pass, no output
./scripts/check-imports.sh       import direction ok
git diff --check                 pass
```

The full run included the existing real MCP round trips and real Postgres tests. The
temporary Postgres service was removed afterward. No juena-chatbot file was changed.

---

## Checkpoint 3 — persistence and identity

### What lands

`server/database/connection.py`, `checkpointer.py`, `store.py`, `models.py`, and
`server/identity.py`.

**`models.py`** holds `Base`, `utc_now`, `User`, `AuthSession`, `Chat`.

**`Chat` gains `agent_id`** (decision 13). It has none today —
`juena/server/database/models.py:101-112` is `thread_id`, `user_id`, `title`, `summary`,
`created_at`, `updated_at` — because juena-chatbot has exactly one agent. v2 has two, and
`/{agent_id}/stream` will otherwise resume any thread under any graph:

```python
agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
```

It is written at creation, and checked on lookup and resume. Not nullable, because a
conversation that does not know its own graph is the bug being prevented. juena-chatbot
backfills its single value in plan 02.

> **A column is not a feature.** At the `e4a5eb3` source snapshot, nothing on the path
> could populate it: `CreateChatInput` (`schema/server.py:127`) carried only `thread_id`
> and `title`; `create_chat` (`clients/client.py:174`) posted exactly those two; and
> `ensure_owned_chat` (`server/chat/repository.py:30`) constructs
> `Chat(thread_id=..., user_id=...)`. CP1 now establishes the wire-schema field, but
> adding a non-null column without the rest of this list would still produce a
> `NOT NULL` violation on the first conversation.

**The complete write-and-read contract**, all of it in core but split across the
checkpoint that owns each component:

| Where | Checkpoint | Change |
|---|---|---|
| `schema/server.py` — `CreateChatInput` | CP1 | requires `agent_id: str` |
| `clients/base.py` — `create_chat` | CP5 | sends the required `agent_id` in the body; CP1 already established the signature |
| `server/chat/repository.py` — `ensure_owned_chat` | CP3 | takes `agent_id`, sets it on creation, and **raises `ChatNotFoundError` when an existing chat's `agent_id` differs** — the same shape as the existing owner check, and for the same reason: a mismatch must not reveal that the row exists |
| listing and serialisation | CP3 repository, CP4 routes, CP5 client | the repository can filter by `agent_id` and returns it with each chat, so the UI can restore the right mode rather than guess |
| stream authorisation | CP4 | `_authorize_thread` compares the path's `agent_id` against the stored one |
| resume | CP4 | `/resume` and `/{agent_id}/resume` do the same |
| pending-interrupt lookup | CP4 | same, so a card from one agent cannot be answered into the other |

**Tests — cross-agent rejection, in both directions.** CP3 proves the repository refuses
a wrong owner or agent as *not found* rather than *forbidden*. CP4 repeats that contract
through the real stream, resume and pending-interrupt routes, because only that
checkpoint has a server through which to exercise them.

juena-chatbot registers `"juena"` with `set_as_default=True` and behaves exactly as
before. Core's initial `DEFAULT_AGENT` is `None`; serving without an application having
registered a default fails loudly instead of silently choosing JüNA.

`User.subject` / `User.issuer` map to the **existing** columns `saml_subject` /
`idp_entity_id` by positional name:

```python
subject: Mapped[str] = mapped_column("saml_subject", Text, nullable=False)
issuer:  Mapped[str] = mapped_column("idp_entity_id", Text, nullable=False)
```

There is no Alembic in this project — the schema is created by
`Base.metadata.create_all`, which **never renames a column**. A rename would silently
leave the old column beside a new empty one, and juena-chatbot has live rows.

**`identity.py`** holds `Principal`, `hash_session_token`, `upsert_principal`,
`create_auth_session`, `revoke_auth_session`, `revoke_sessions_for_subject`,
`session_principal` (the cookie-reading dependency, formerly `get_current_user`), and
`local_principal`.

`SESSION_COOKIE_NAME` stays `"juena_session"` — it is a live cookie name, and renaming
it logs everyone out.

**`local_principal` is v2's entire identity story** (decision 9, part 3, and decision
17): a dependency returning a `Principal` built from a configured, stable UUID, so the
`users` row, thread ownership and memory namespace are real and consistent across
restarts.

Two obligations that a real identity provider satisfies for free span CP3's identity
primitives and CP4's application factory:

**1. The guard runs at construction, not as a dependency.** CP3's `local_principal`
refuses to construct when `API_PUBLISHED` is true or `BIND_HOST` is not loopback. CP4's
`create_app` checks the fixed-principal marker again when it assembles the application.
A *dependency* cannot enforce this: it runs on a request, so it would fail the first call
rather than refuse to boot, and by then the port is already open. The topology it assumes
is decision 17 — Streamlit published on `127.0.0.1`, the API bound to container loopback
and not published at all.

**2. Its `users` row is upserted inside the database lifespan.** CP3 supplies and tests
the idempotent `ensure_principal_row` operation. CP4 calls it from the application
lifespan, **after** `database_lifespan` has an engine and **before** the app serves.
`Chat.user_id` is a foreign key to `users.id`; a principal that merely *claims* a UUID
produces a foreign-key violation on the first conversation.

The guard, fixed-principal marker and row operation land and are tested **in CP3 with the
provider**. Their integration into `create_app` belongs to CP4, where that factory first
becomes callable; there is no usable server window between the two checkpoints.

**Done when** a throwaway script creates the three tables against a real Postgres and
round-trips a session:

```bash
docker compose -f tests/compose.postgres.yml up -d
uv run pytest tests/test_identity_postgres.py -q
psql "$DATABASE_URL" -c '\d users'
psql "$DATABASE_URL" -c '\d chats'
```

with these things true:

- `\d users` still shows columns named `saml_subject` and `idp_entity_id`;
- `\d chats` shows the new `agent_id`, not null;
- the session service round-trips and revokes a real persisted session;
- constructing `local_principal` fails when `API_PUBLISHED=true` or `BIND_HOST` is not
  loopback;
- `ensure_principal_row` is idempotent, rejects a changed configured UUID, and creates
  the foreign-key target needed to insert a `Chat`.

### What actually landed

**Completed 2026-09-15 in core commits `0cfc1e2` and `219aed8`.**
`server/database/{models,connection,checkpointer,store}.py`, `server/identity.py`, and the
ownership half of `server/chat/repository.py` are working implementations. Verified
against a real Postgres:

```text
\d users     idp_entity_id, saml_subject   (uq_users_idp_subject intact)
\d chats     agent_id varchar(64) not null
tests/test_identity_postgres.py            15 passed
full frozen-lock suite                    203 passed, 1 expected MCP beta warning
./scripts/check-imports.sh                 import direction ok
clean-environment import of the new modules  pass, no output
```

- `User.subject`/`User.issuer` are attribute renames over the original
  `saml_subject`/`idp_entity_id` columns, and the unique constraint still names the
  columns. A test reads the live column names back rather than trusting the model.
- `Chat.agent_id` is `String(64)`, not null, matching `CreateChatInput.agent_id`'s
  `max_length=64` from CP1.
- `upsert_principal` takes the fields (`subject`, `issuer`, `email`, `display_name`)
  rather than an identity object and returns a `Principal`, so core never learns what a
  SAML assertion is. `create_auth_session` takes that `Principal`; the application's SAML
  endpoint keeps its existing two-call shape.

**Three decisions taken while implementing, each recorded because it is not in the plan
above:**

1. **`local_principal` takes its UUID as an argument, not a `CoreSettings` field.**
   Adding one would force juena-chatbot to configure a value it never reads. The
   application owns where the id comes from; core owns what it means.
2. **The publication guard is `refuse_published_api(dependency)` in `identity.py`, called
   by `local_principal` itself at construction** — not only from `create_app`, which does
   not exist until CP4. CP4's `create_app` will call it again so a fixed dependency
   supplied from elsewhere cannot bypass the factory-level check (required in that
   checkpoint below and noted in `service.py`'s docstring with `ensure_principal_row`).
   The CP3 helper already asserts both of decision 17's conditions:
   `API_PUBLISHED` is false *and* `BIND_HOST` is loopback.
3. **`get_owned_chat`'s `agent_id` is keyword-only with no default.** It accepts `None` —
   renaming a conversation is addressed by thread alone and those routes carry no agent —
   but omitting it is impossible. A default would let a CP4 resume route skip the
   cross-agent check by omission, which is precisely the bug decision 13 exists to
   prevent, and it would pass every test that did not probe for it. `list_owned_chats`
   keeps its `None` default deliberately: listing everything shows too much rather than
   granting anything. A signature test locks the asymmetry.

**What this checkpoint did *not* do, and why:**

- **`load_thread_messages` stays a stub, now pointing at CP4.** It is the one function in
  `repository.py` that reads message *content* rather than ownership, and it needs
  `server/utils.langchain_to_chat_message`, which lands with the rest of the server.
- **Three rows of the write-and-read path are CP4's**, because they live in the routes,
  not in persistence: `_authorize_thread`, `/resume` and `/{agent_id}/resume`, and the
  pending-interrupt lookup. The repository enforces the rule they must call; the
  cross-agent rejection test here covers `ensure_owned_chat` and `get_owned_chat` in both
  directions (wrong agent, and another user's thread), each refused as *not found*.
- **`clients/base.py` needed no change** — CP1 had already given `create_chat` its
  required `agent_id` and `list_chats` its optional one. The bodies land in CP5.

---

## Checkpoint 4 — the server

### What lands

`server/errors.py`, `server/utils.py`, `server/agent/registry.py`,
`server/agent/input_handler.py`, `server/agent/runtime_model_middleware.py`,
`server/streaming/`, `server/chat/`, and `server/service.py` as `create_app(...)`:

```python
def create_app(*, principal, extra_routers=(), extra_lifespans=()) -> FastAPI: ...
```

**Two side-effect-import traps get their comments here.** Transplant the existing one
from `juena/server/service.py:30-35` — it already explains the agent-registry trap
better than a new comment would:

> Imported for its side effect: the module self-registers the agent factory. Importing
> *this* module has to be enough, because the process serving the API is not always
> `main.py` — production runs `uvicorn juena.server.service:app`. Registering only from
> `main.py` leaves those processes with an empty registry, so every invocation would
> 404.

The second trap is the database models, from CP3: a model class never imported is never
created by `create_all`, and it fails at first write rather than at startup. Same
mitigation — `# noqa: F401` with a comment — plus a test asserting
`set(Base.metadata.tables)`.

**`processor.py`'s approval branch** becomes the `register_interrupt_event(kind,
builder)` dictionary from 00. Core knows the clarification kind; the application
registers its own.

**Done when:**

```bash
uv run pytest tests/ -q

uv run python - <<'PY'
from uuid import uuid4
from juena_core.server.service import create_app
from juena_core.server.identity import local_principal
app = create_app(principal=local_principal(user_id=uuid4()))
# NOT `r.path for r in app.routes`: since FastAPI 0.141 an included router is
# one opaque private `_IncludedRouter` entry there, so that expression prints
# only /health. The OpenAPI schema is public and flattens inclusion.
print(sorted(app.openapi()["paths"]))
PY
```

prints `/chats`, `/chats/{thread_id}`, `/stream`, `/stream_with_files`, `/resume`,
**`/{agent_id}/stream`, `/{agent_id}/stream_with_files`, `/{agent_id}/resume`**,
`/threads/{thread_id}`, `/threads/{thread_id}/pending-interrupt`,
`/artifacts/{artifact_id}`, `/health` — and **nothing under `/auth/`**, because SAML is
not here.

The route-list check is necessary but not sufficient. CP4 also has integration tests
which prove:

- `create_app` rejects a fixed principal when `API_PUBLISHED=true` or `BIND_HOST` is not
  loopback, while a real identity provider remains publishable;
- entering the real application lifespan creates the fixed principal's `users` row
  before serving, so a `Chat` insert succeeds without a manual test call to
  `ensure_principal_row`;
- a thread created under `vitess` cannot be streamed, resumed or queried for a pending
  interrupt under `advanced_mode`; every mismatch is returned as *not found*.

The three `/{agent_id}/…` variants are not optional: `BaseAgentClient` calls them, and v2
has two agents, so they are the only way to address the second one. An earlier draft
omitted them from this list.

### What actually landed

**Completed 2026-09-15 in core commit `e11f734`, then corrected after review in
`5df150a`.** `server/errors.py`, `server/utils.py`,
`server/agent/{registry,input_handler,runtime_model_middleware}.py`,
`server/streaming/{events,handlers,processor}.py`,
`server/chat/{input_constants,input_types,input_utils,inputs,endpoints}.py`,
`load_thread_messages` in `server/chat/repository.py`, and `server/service.py` as
`create_app(...)` are working implementations. Two modules are **new, not in CP0's stub
tree**: `server/interrupts.py` and `server/api/`.

```text
create_app route list          all 12 documented paths, plus the pre-existing
                               /threads/{thread_id}/pending-approval alias;
                               nothing under /auth/
tests/test_server_contracts.py        33 passed
tests/test_server_routes_postgres.py  14 passed
full frozen-lock suite               255 passed (203 at CP3, +47 new tests,
                                     +5 new import-boundary parametrisations)
./scripts/check-imports.sh           import direction ok
clean-environment import of the new modules  pass
```

Both new test files were checked by breaking the code they cover: removing
`ensure_principal_row` from the lifespan fails 11 of the 14 route tests, and dropping the
`agent_id` comparison from the repository fails exactly the six agent-scoped ones and
nothing else.

**The post-implementation review found and fixed two runtime defects that those green
tests did not cover:**

- `PreparedCodeChatInputs.workspace_files` was merged before the upload manifest and
  turn-scoped `current_message`/code/error files were added. A process-backed workspace
  therefore saw only the raw upload while the graph saw the complete input set. The merge
  now happens after every state update is assembled, and a regression asserts the
  workspace view equals every non-deletion file sent to the graph.
- the first request cache in `get_agent()` had no concurrency guard. Two simultaneous
  first requests both ran the factory, returned different graphs and leaked the instance
  overwritten in `_agent_registry`. Agent-specific async locks now serialize only the
  first build of each id; a concurrent regression proves one factory call and one shared
  graph.

The exact frozen-lock suite passes with 255 tests after these corrections. A successful
`/simulator/stream` request was also exercised manually against the real throwaway
Postgres/checkpointer and emitted its thread and thinking SSE events. This is a server
smoke check, not a substitute for plan 02's full application/model streaming check.

**The plan's own acceptance command does not run.** `sorted(r.path for r in app.routes)`
prints only `/health` on the installed FastAPI 0.141.1 / Starlette 1.6.0: an included
router is one opaque `_IncludedRouter` entry in `app.routes`, and `_IncludedRouter` is
private. Route enumeration goes through `app.openapi()["paths"]`, which is public and
flattens inclusion. The route list itself is unchanged and complete.

**Decisions taken while implementing, each recorded because it diverges from a plan
above:**

1. **`server/api/` is in core after all** — 00-BOUNDARY.md decision 10 says it stays in
   each application. Two of that decision's three reasons have since expired: artifacts
   became core's in CP2, and approvals became an application-registered interrupt kind in
   this checkpoint. The third, materialising a thread's files where a process can open
   them, is a seam **both** applications need — VITESS binaries read real files from disk
   exactly as a sandbox mount does — so it is a parameter, not a reason for two copies.
   Keeping two would put the SSE ordering, the ownership check, the artifact drain and the
   thread-event emission in two places that must not drift, and CP4's own acceptance
   check cannot pass without it: `create_app(principal=…)` has to produce `/stream`.
   Decision 10's actual worry — a `BaseAgentClient` method with no matching route — gets
   *worse* if core defines the client but not the routes.
2. **`register_interrupt_kind(kind, *, event, resume)` replaces decision 5's
   `register_interrupt_event(kind, builder)`,** and lives in the new
   `server/interrupts.py` rather than in `service.py`. Two changes, both forced:
   - An event builder alone lets core **show** a card it cannot **resume**. The user
     answers, `/resume` finds no way to turn the reply into a `Command`, and the run stays
     paused with nothing naming the cause. Rendering and resuming have one owner and one
     lifetime, so they register together.
   - The registry cannot live in `service.py`: `processor.py` needs it, and `service.py`
     imports the routers which import `processor`. Its own stub docstring described that
     cycle. `service.py` re-exports `register_interrupt_kind`, so the documented call site
     is unchanged.
   The event builder doubles as the classifier — it returns `None` for an interrupt that
   is not its kind — so a kind cannot be recognised but unrenderable. Core registers
   exactly `clarification`; a test asserts that an unregistered HumanInTheLoop approval is
   neither classified nor rendered.
3. **`get_default_agent()` raises `RuntimeError`, not `AgentNotFoundError`.** The first
   draft raised the latter, and a test caught that `AgentNotFoundError.__init__` overwrites
   the message with `Agent '<default>' not found`, burying the explanation in `details`.
   Nothing is missing from the *request*: the application never imported its agent module.
   A 404 sends whoever is debugging to look at the request instead of at the import, so
   this now fails like `settings()` and `get_checkpointer()` do, with a message naming the
   fix. The route helper no longer translates it.
4. **Three app-specific literals became declared parameters**, because core shipping them
   would state things that are false elsewhere:
   - `StreamPolicy(custom_event_types, silent_tools)` replaces the hardcoded
     `"sandbox_status"` and `tool_name == "execute"` in `processor.py`. `custom_event_types`
     is an **allowlist**: the `custom` stream mode carries whatever any middleware wrote, so
     forwarding by default would put internal payloads on a user's wire.
   - `approval_required_event(..., extra_limits=)` keeps the LangChain
     `action_requests`/`review_configs` unpacking, which is shared, but the card's
     `network: none, 2 vCPU, 4 GB` describes juena-chatbot's Podman sandbox and would be a
     false promise from anywhere else.
   - `build_inputs_manifest(..., closing_note=)` — the final paragraph is prompt text that
     names specialists and objectives. Core's default states only a fact.
5. **`shutdown_agents()` closes `aclose()`/`close()` on the agent instance**, replacing
   `getattr(instance, "context7_runtime").client`. Core cannot know what an application's
   resources hold; one documented method is the contract.
6. **`PreparedCodeChatInputs.sandbox_files` is renamed `workspace_files`**, and the
   staging call becomes `ThreadWorkspace(stage=…, delete=…)` on `create_app`. Core computes
   the merged file set and never learns where it lands.
7. **`streaming/__init__.py` stays a bare `__all__`**, like `database/__init__.py`.
   Re-exporting `StreamEventProcessor` from it closes the cycle
   `processor → interrupts → streaming.events → streaming/__init__ → processor`.

**Obligations this creates for plan 02**, none of which a test in core can catch:

| Cutover step | Why |
|---|---|
| `JuenaAgentResources` may add `aclose()` — **nothing breaks if it does not** | `shutdown_agents` no longer reaches for `context7_runtime.client`. Per README finding 12 that close is *already* a silent no-op, since the client exposes neither `close` nor `aclose`, so this changes no behaviour today. It matters the day a resources object holds something that genuinely needs closing |
| `service.py` passes `closing_note=` with juena's **exact** current sentence | plan 02 requires no prompt text to change, and this string is prompt text |
| `service.py` passes `StreamPolicy(custom_event_types={"sandbox_status"}, silent_tools={"execute"})` | without it the sandbox status events stop reaching the UI and `execute` stdout starts reaching the transcript |
| `service.py` passes `extra_limits={"network": "none", "cpu": "2 vCPU", "memory": "4 GB"}` to its approval event builder | the card loses its limits block otherwise |
| the approval kind is registered with **both** an event and a resume builder | `sandbox/approvals.py`'s `_execute_resume` becomes that resume builder; `interrupt_kind`, `get_pending_interrupt` and `get_first_pending_interrupt` are core's now |
| `ThreadWorkspace(stage=stage_runtime_inputs, delete=delete_runtime_workspace)` | otherwise nothing copies `/inputs` into the sandbox mount |
| `sandbox_files` call sites become `workspace_files` | a mechanical rename |
| `ResumeInput` union is composed in juena-chatbot and passed as `resume_input=` | core defines `ResumeBase` and the clarification arm only |

**What this checkpoint did *not* do:**

- **`/auth/dev-login` did not move.** 00's decision 9 part 3 proposed lifting
  juena-chatbot's `AUTH_DEV_BYPASS` endpoint into core as v2's identity story. CP3's
  `local_principal` already is that story, and it is strictly better: no route, no
  session table write, and a guard that refuses at construction rather than one that
  refuses at request time. A second development identity path in core would be one more
  way to serve an unauthenticated API.
- **No route runs a language model.** The agent registered in the route tests is a
  two-node graph compiled against the real checkpointer. Every property under test is
  decided before the graph is invoked, or by the checkpointer after it.
- **`StreamEventProcessor` is not covered end-to-end through `/stream`.** The SSE frames
  a real turn produces are plan 02's fourth verification item, against the running system.

---

## Checkpoint 5 — the client and the UI shell

### What lands

**`clients/base.py` — `BaseAgentClient`, not the whole client** (decision 10). Core owns
transport, `_parse_sse_data`, and only the methods for routes core owns: `health`,
`list_chats`, `create_chat`, `get_chat`, `update_chat`, `stream`, `resume_stream`,
`get_artifact`, `get_pending_interrupt`, `delete_thread`. It does **not** get
`get_current_user` (`/auth/me`) or `list_research` (`/research`) — those routes are the
application’s, and each app subclasses to add what it actually serves.

The client stays **synchronous**. Streamlit consumes it synchronously today, and
`stream`/`resume_stream` remain ordinary generator methods. `create_chat` takes required,
keyword-only `agent_id`; `list_chats` accepts an optional agent filter. The UI `Chat`
also carries `agent_id`, so restoring a conversation restores its graph identity.

`ui/math_rendering.py`, `ui/chat_storage.py`, `ui/client_setup.py`, `ui/streaming.py`,
`ui/components.py` — the last two being the split halves of `chat_interface.py` and
`ui_components.py` per 00. All of `ui/` sits behind the `[ui]` extra.

`ui/client_setup.py` requires `agent_id` with no default. The source's
`JUENA_AGENT_ID = "juena"` remains in juena-chatbot's thin wrapper; v2 passes the mode it
is constructing. A shared package must not smuggle one application's identity into the
other.

**`juena_core/mcp.py`** — the MCP connection layer, behind the `[mcp]` extra, and **the
only module in either application stack that imports `langchain.mcp`.**

That containment is the point. The namespace is beta and may change; keeping every import
inside one module means a breaking release is one file to fix rather than a search across
two applications.

```python
from langchain.mcp import MCPAdapter          # raises LangChainBetaWarning once

async with MCPAdapter("http://vitess-mcp:9005/mcp") as adapter:
    tools = await adapter.list_tools()
# The returned tools stay callable; each opens the reentrant client for its invocation.
```

Three things that differ from the retired `langchain-mcp-adapters`, and each changes code
written against it:

- **`MCPAdapter` is an async context manager.** `MultiServerMCPClient` was not — its
  `__aenter__` raised. In the current LangChain source, `list_tools()` enters the adapter
  for discovery and each returned tool retains the reentrant FastMCP client, so it remains
  callable after the discovery context exits. CP0b verifies that contract against the
  exact installed release before CP5 relies on it.
- **The config shape is `{"mcpServers": {...}}`** — FastMCP's `MCPConfig` — and **the
  transport is inferred** from each entry. There is no `transport` key any more. A single
  server may be passed as a bare URL.
- **Discovery is `await adapter.list_tools()`**, not `get_tools()`.

Two contracts core keeps from the old design, because they were about *policy*, not the
library:

- **An optional integration returns `None` on failure.** Context7 is nobody's product; if
  it is unreachable, its tools should not exist rather than exist and fail.
- **That is deliberately not the contract for VITESS execution**, where the tools *are*
  the product. 03/CP3 makes MCP healthy before construction instead. The difference is a
  decision, not an inconsistency.

The helper returns the discovered tools, not a live adapter resource. `shutdown_agents`
therefore has no `MCPAdapter` cleanup to perform. Its existing defensive `close`/`aclose`
probe may remain for other application-owned resources, but it must not claim to close an
adapter or call `__aexit__` outside the context that entered it.

**Done when:**

```bash
uv sync                                    # base install
uv run python -c "import juena_core.clients.base"            # works
uv sync --extra ui
uv run python -c "import juena_core.ui.streaming"            # works
```

and then **the real test, against the built wheel in a clean environment**:

```bash
uv build
.venv/bin/python -m venv /tmp/cleanroom
/tmp/cleanroom/bin/pip install dist/juena_core-*.whl
/tmp/cleanroom/bin/python -c "import juena_core.clients.base"
/tmp/cleanroom/bin/python -c "import juena_core.ui.streaming" \
  && echo "PACKAGING BUG: streamlit module imported without the [ui] extra" && exit 1
```

Two details, both of which decide whether this test means anything:

- **Import a module that really needs Streamlit** — `juena_core.ui.streaming` — not the
  `juena_core.ui` namespace. An empty `__init__.py` imports fine with no dependencies and
  the check would pass while the packaging is broken.
- **Only the clean room counts.** The development virtual environment already has
  Streamlit installed, so the first sequence passes regardless of what the metadata says.
- **Use the project's Python to create it.** On the implementation machine the macOS
  system `python3` is 3.9.6, below this package's declared `>=3.11`; using it fails before
  the packaging property under test is reached. The environment is still clean — only
  its interpreter comes from `.venv`, not any installed package.

**The development virtual environment already has Streamlit installed**, so the first
sequence can pass while the packaging metadata is wrong. Only the clean room proves it.

**Packaging note:** core depends on nothing by URL, and both applications resolve it
through `[tool.uv.sources]` as the sibling path declared in CP6. No Hatch direct-reference
exception is needed.

### What actually landed

**Completed 2026-09-15 in core commit `23de400`.** All seven CP5 stubs are working
implementations: `clients/base.py`, `mcp.py` and
`ui/{math_rendering,chat_storage,client_setup,streaming,components}.py`. Four focused test
files make the client wire contract, MCP failure policy, UI state-machine seams and math
normalisation permanent.

```text
tests/test_{client_contracts,mcp_helpers,ui_contracts,math_rendering}.py  30 passed
full frozen-lock suite                                                   289 passed
./scripts/check-imports.sh                                               import direction ok
development import of clients.base and ui.streaming                     pass
built-wheel Python 3.11 clean room, no extras:
  import juena_core.clients.base                                         pass
  import juena_core.mcp                                                  pass
  import juena_core.ui.streaming                                         fails on missing
                                                                          streamlit, as required
```

The full suite ran against the real throwaway Postgres service and retained CP0b's real
MCP round trips. The two warnings are the expected `LangChainBetaWarning` for
`langchain.mcp` and Starlette's upstream AnyIO alias deprecation. `uv.lock` did not
change. A source scan confirms `juena_core.mcp` is the only production module importing
`langchain.mcp`.

**Decisions made while finishing the interrupted implementation:**

1. **Unknown SSE objects pass through unchanged.** Core parses its own event vocabulary;
   an application event keeps its type and fields so the `custom_status` renderer can
   consume it. The source client's `unknown` summary destroyed exactly the data the
   application seam needs.
2. **`resume_stream` requires an interrupt `kind` and accepts its fields generically.**
   `clarification` is core's one known kind; an application supplies the discriminator it
   registered in CP4 for approvals or future interrupts. Hard-coding
   `execute_approval` here would merely move a juena-chatbot literal into core.
3. **`initialize_client` requires `timeout` as well as `agent_id`.** The source read an
   application global. Reading `CoreSettings` instead would make server configuration an
   undocumented precondition of constructing a browser-side HTTP client. Each UI passes
   its own timeout explicitly.
4. **Every HTTP 401 becomes `AgentAuthenticationError`.** Session expiry is not a generic
   transport failure on one privileged route only; applications can now handle it
   consistently for chat, stream, artifact and thread calls.
5. **MCP import and policy are separate.** `_load_adapter_class()` delays the beta/extra
   import until discovery. `discover_tools` raises `MCPUnavailableError` for a required
   service; `discover_optional_tools` logs and returns `None`. Both use the measured
   `async with MCPAdapter(...): await adapter.list_tools()` lifecycle.

**The completion review found five bugs before commit:**

- `get_pending_interrupt` omitted `agent_id`. The server therefore resolved the default
  graph and returned 404 for a thread owned by v2's other agent. It now always sends the
  client-selected agent and refuses to guess when none is selected.
- a failed pending-interrupt lookup was still cached in `approval_checked_threads`, so a
  transient API failure suppressed restoration for the rest of that Streamlit session.
  Only a successful lookup, including a successful empty result, is cached now.
- a failed clarification resume restored the interrupt but left `clarify_answer:*` set,
  permanently disabling the question card. Both approval and clarification submission
  keys are cleared when resume fails.
- artifact reconciliation chose either stored ids or live ids. If both existed, a
  live-only file disappeared; it now keeps the stored order and appends the live-only
  ids.
- every complete `ChatMessage`, including a tool payload, set the assistant-completion
  flag. With tool-payload streaming enabled, a tool result arriving first suppressed all
  later answer tokens from the live placeholder. Only a complete AI message sets it now.

The clean-room command above was corrected after the first run exposed the host's Python
3.9 rather than a wheel defect. Re-running with the project's Python 3.11.13 proved the
intended metadata boundary: Streamlit is present only under the `[ui]` extra, while the
base client and lazy MCP wrapper import without it.

---

## Checkpoint 6 — lock it

**D7 is settled: `juena-core` is a sibling directory consumed as a uv path source, with
a committed `uv.lock`. No remote, no tag, no build credentials.**

```toml
# in juena-chatbot and vitess-ai-agent
[tool.uv.sources]
juena-core = { path = "../juena-core" }
```

**What the lock does and does not do.** `uv lock` records the resolved *third-party*
versions from CP0b, and `uv sync --frozen` installs exactly those. It does **not** freeze
the source bytes of a local directory: a path dependency is installed from whatever is in
`../juena-core` at the time, and directory dependencies cannot participate in
hash-checking. So `--frozen` guarantees the dependency set, **not** the core revision.

An earlier revision said core was "pinned by the committed `uv.lock`". That is wrong, and
believing it would mean an uncommitted experiment in core silently becoming what an
application was built against.

**So the revision is pinned by discipline, recorded:**

- **`juena-core` has a clean git tree before any accepted build.** `git status --short`
  in core is part of the build, not a habit.
- **The core commit SHA is recorded in each application's build record**, alongside the
  resolved dependency set. `git -C ../juena-core rev-parse HEAD`.
- **The resulting image digest is recorded.** That is the only identifier that actually
  freezes the bytes, and it is what a later "which core was this built from?" is answered
  with.

This is weaker than a tag plus a hash, and it is the right trade while core and both
applications sit in one working copy on one machine. **It stops being sufficient the day
a second person builds an image** — which is the same threshold that reopens the remote.

juena-chatbot's existing unpinned `juena-rag @ git+…` is the counter-example: acceptable
with one consumer, and a way to break the other application silently with two.

**Docker.** A path dependency has to be inside the build context, so the image **COPYs
core in** rather than fetching it:

```dockerfile
COPY juena-core/ /src/juena-core/
COPY vitess-ai-agent/ /src/app/
RUN cd /src/app && uv sync --frozen
```

**Built from the parent directory.** One context, decided here rather than left open:

```yaml
# vitess-ai-agent/docker-compose.yml
services:
  vitess-app:
    build:
      context: ..                       # JueNA_knowledge_base/
      dockerfile: vitess-ai-agent/Dockerfile
```

and the existing chatbot makes the same context choice explicitly:

```yaml
# juena-chatbot/docker-compose.yml
services:
  juena-chatbot:
    build:
      context: ..                       # JueNA_knowledge_base/
      dockerfile: juena-chatbot/Dockerfile
```

Not vendoring-by-launcher. A copy step that runs outside `docker build` is a step that can
be skipped, run stale, or forgotten in CI — and "it builds on my machine and not in
Compose" is precisely the failure this choice creates. A parent context is visible in the
Compose file, where anyone debugging the build will look.

Its cost is a larger build context. Because the context root is the parent directory,
an application-level `.dockerignore` would not be read. Each application therefore keeps
a **Dockerfile-specific ignore file beside its Dockerfile** — `Dockerfile.dockerignore` —
excluding sibling `.git/` and `.venv/` directories, `rag/vitess-rag/chroma_db/`, model
caches, generated VITESS build output and other large local material while explicitly
retaining the application and `juena-core` sources. Docker gives this file precedence over
a context-root `.dockerignore`; see Docker's
[build-context documentation](https://docs.docker.com/build/concepts/context/#dockerignore-files).
Write and test both files in this checkpoint.

**Done when** both applications `uv sync --frozen` against the sibling, `uv.lock` is
committed in each, `docker compose build` succeeds from the parent context with **no
credentials configured anywhere**, and the build record for one image names the core
commit SHA and the resulting image digest.

*When a second person needs core*, add a remote and switch the source — deferred with the
rest of production. The recorded core commit SHA, not the lock, names the revision to tag.

### What actually landed

*(Fill in after the work.)*

---

## Verification

Run after **every** checkpoint, not just at the end:

```bash
cd juena-core
uv run pytest -q
./scripts/check-imports.sh
env -i PATH="$PATH" uv run python -c "import juena_core.log"
```

The third command is the one that regresses quietly. Any module that grows an
import-time configuration read will break it, and it will not break anything else until
someone checks out the repository on a fresh machine.

## What could go wrong

| Risk | Guard |
|---|---|
| `import juena_core.config` raises on a developer laptop — **the most likely single failure**, because the code being copied does exactly that today | CP1's `env -i` import test |
| A core module grows an import-time `settings()` call, reintroducing the problem | the same test, run after every checkpoint |
| `repo_root()` gets ported and silently resolves to `site-packages` | it is not in the disposition table; CP1 says explicitly not to port it |
| The middleware order changes during the move and nothing notices | CP2's class-name-order test, made permanent |
| A `[ui]`-only import leaks into the base package | CP5's clean-room wheel test — **the developer venv already has Streamlit and will mask this** |
| A `BaseAgentClient` method has no matching route in an application | the reverse-direction route test (CP0) |
| An accepted image cannot be traced to the local core source that built it | CP6 records a clean core commit SHA and the resulting image digest |
| `local_principal` ships without its loopback refusal | the refusal and its test land in CP3, together |

## Status

| | |
|---|---|
| **Depends on** | 00 |
| **Unblocks** | 02 |
| **Executed** | CP0a, CP0b, CP0, CP1, CP2, CP3, CP4 and CP5 complete through core commit `23de400`; CP6 is next |
| **Decided** | the package layout; `>=3.11`; recent bounded LangChain-family versions validated in CP0b; `CoreSettings` + `configure()`; extras are `[ui]` and `[mcp]`; `BaseAgentClient` rather than the whole client; `Chat.agent_id`; `local_principal` with a publication guard; `MCPAdapter` imports contained in `juena_core.mcp`; discovered tools are stateless after discovery, subject to CP0b verification |
| **Open** | nothing blocking. Publishing core to a package index, and adding a remote at all, are deferred with the rest of production |
| **Revised** | 2026-09-15 after [REVIEW.md](REVIEW.md) — AST import test, client split, corrected MCP lifecycle, clean-room wheel test, `agent_id`, `local_principal` |
