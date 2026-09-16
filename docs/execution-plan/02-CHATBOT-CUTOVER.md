# Plan 02 — Switching juena-chatbot over

> **Goal:** juena-chatbot stops carrying the infrastructure and consumes `juena-core`
> instead.
>
> **This is the only plan that edits `src/juena/`, and it is the only plan that
> produces evidence.**
>
> **Depends on:** 01, complete, committed and recorded. **Unblocks:** 03.

## Before you start

Read `README.md` and `00-BOUNDARY.md`. Plan 01 must be finished, its verification
passed, its tree clean, and its core commit SHA recorded. Core now has a GitHub remote,
but it still has no release tag: this cutover deliberately consumes the clean sibling
checkout at the recorded SHA through a path dependency.

This plan edits a **different repository** from the one these documents live in:
`/Users/az-ihsan/Documents/kerjaan-ihsan/post-doc/JueNA_knowledge_base/juena-chatbot`.

Work on a branch. **Do not do this plan and plan 03 in the same branch** — the whole
value of the sequencing is that the cutover is proven against a system that already
works, before a second consumer exists to confuse the evidence.

## Why this exists

An extraction validated only against the code you extracted it from is an extraction
validated against itself. Plan 01 produced a package that imports and passes its own
tests; that says nothing about whether the boundary is in the right place.

This plan finds out, using the one instrument available: a 46-module test suite and a
running application that already works.

**The honest possibility this leaves open:** *the boundary is in the wrong place, here
is where, and here is what we move.* Finding that out here is cheap. Finding it out
after v2 depends on it is not.

---

## Step 1 — the baseline, before anything else

Plan 01 recorded this. Record it again now, on a clean tree, because a week has passed:

> **This gate was initially blocked.** `env.example` and `juena` carried the juena-rag
> cutover work. That work is now committed at `ee9248d`; it was not reverted or folded
> into this cutover. A baseline taken over uncommitted changes would not be a baseline,
> because step 3 could not tell an earlier test change from one this refactor lost.

```bash
cd juena-chatbot
git status --short          # must be clean
./juena test-all

# The pass counts cannot show a removed test offset by an added one. Capture the
# actual node ids with the plan's pytest plugin. Preserve pytest's exit status:
# a failed collection must not become a successful grep/sed pipeline.
PLAN_DIR="$(cd ../Vitess-AI-Agent/docs/execution-plan && pwd)"
collect() { # $1 = repository; remaining arguments are uv-run options
    repo="$1"; shift
    if ! collected="$(
        cd "$repo" &&
        PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PLAN_DIR" \
            uv run "$@" pytest --collect-only -q \
                -p 02-collect-nodeids tests/ 2>&1
    )"; then
        printf '%s\n' "$collected" >&2
        return 1
    fi
    printf '%s\n' "$collected" |
        awk -F '\t' '$1 == "NODEID" {sub(/^[^\t]*\t/, ""); print}' |
        sort
}
collect . --extra dev > "$PLAN_DIR/02-baseline-nodeids.txt"
collect ../juena-core --frozen --group dev \
    > "$PLAN_DIR/02-core-baseline-nodeids.txt"
wc -l "$PLAN_DIR/02-baseline-nodeids.txt" \
    "$PLAN_DIR/02-core-baseline-nodeids.txt"
```

**Record the collected node ids, not just the totals.** A pass count is a single number,
and one test removed plus one test added leaves it unchanged. The node id list makes a
swap visible as a diff. Record **both repositories**: core already has tests produced by
Plan 01, including tests copied from the chatbot, so step 3 needs the pre-cutover union
rather than treating every pre-existing core test as a Plan 02 addition.

> **The original `grep '::' | sed …` recipe is not sound for this suite, and was replaced
> after being measured.** Several parametrised ids in `test_agent_prompts.py` and
> `test_specialists.py` embed prompt text containing real newlines, so pytest prints one
> node id across several lines: fragments carrying a `::` are counted as extra tests and
> fragments without one disappear. On the 457-test unit collection it reported **457**
> matching lines only because four real node ids disappeared while four prompt fragments
> were falsely counted in their place. [`02-collect-nodeids.py`](02-collect-nodeids.py)
> reads `item.nodeid` from pytest, so every output line is a real collected test.
>
> It also **digests any parameter that is long or multi-line** (4 of the 473 ids). This
> list is versioned in *this* repository while the tests live in juena-chatbot's, and two
> of those ids carry a specialist prompt verbatim; committing them would copy juena's
> prompt text into a second repository's history, where nothing removes it. A digest is
> stable across the move and still shows a changed parameter as a diff.

If the tree is not clean, stop and find out why before touching anything.

### What actually landed

**Step 1 completed 2026-09-16 at juena-chatbot commit `ee9248d`** (`update:juena-rag-cutover`
— the juena-rag work named above is finished and committed, so the tree is clean and the
baseline is reproducible, unlike 01/CP0's dirty-checkout observation).

```text
git status --short          (empty)
./juena test                452 passed, 5 skipped
./juena test-integration    16 passed
chatbot collected node ids  473 across 46 test modules
core collected node ids     385 across 38 test modules
pre-cutover identity union  745 unique; 113 shared by both repositories
```

457 + 16 = 473, so the collected list and the two runs agree exactly. The list is
[`02-baseline-nodeids.txt`](02-baseline-nodeids.txt), versioned beside this plan rather
than left in `/tmp`, because step 3 diffs against it a week later. Core's frozen list is
[`02-core-baseline-nodeids.txt`](02-core-baseline-nodeids.txt), collected at `d086c01`.
Normalising the chatbot list to compare-on-identity
(`sed 's|^[^:]*::||' | sort -u`) still yields 473 lines, so the chatbot baseline contains
no duplicate identities after the module path is removed.

The two pre-cutover lists are deliberately not disjoint. Core already contains **113**
generic test identities copied or rewritten during Plan 01; **112** belong to the 13
modules that move whole below, and `test_registration_wraps_every_specialist` is the
generic half of `test_findings_lifecycle`. Their union has **745** unique identities:
473 + 385 - 113. Step 3 must collapse those duplicates, preserve that union, and then
account for any genuinely new Plan 02 tests.

The cutover branch is `juena-core-cutover`, taken from `juena-rag-cutover`. Core is at
`d086c01` (`docs: add MIT license`), one documentation commit after the `cc45ec5` handoff
recorded in 01/CP7; its tree is clean.

---

## Step 2 — delete and re-point, module by module

For each module core now owns: delete it from `src/juena/` and replace every import of
it with the `juena_core` equivalent.

Do this **in plan 01's checkpoint order** — configuration → agent kit → persistence →
server → client and UI — running `./juena test` after each group. The suite will go red
in predictable ways, and each red is one search-and-replace.

Add the dependency first:

```toml
dependencies = ["juena-core[ui,mcp,sandbox]"]

[tool.uv.sources]
juena-core = { path = "../juena-core" }
```

This happens **after** the step-1 baseline, not in plan 01. The pre-cutover application
pins `deepagents==0.6.12`, while core requires `>=0.7.13,<0.8`; uv proves those constraints
are unsatisfiable. Remove the application's redundant direct LangChain/deepagents bounds
as their modules are re-pointed, remove `langchain-mcp-adapters` when Context7 moves to
`juena_core.mcp`, regenerate the lock once, and explain the dependency-node changes with
the same care as test-node changes. Upgrading first and calling the result a baseline
would make the baseline measure a different application.

**The lock pins the dependency set; it does not pin core's source** — a path dependency installs whatever is in the sibling directory, and cannot be hash-checked. Core's revision is pinned by discipline instead: a clean core tree, and its commit SHA recorded in the build record (D7, 01/CP7). juena-chatbot's
existing unpinned `juena-rag @ git+…` is the counter-example: acceptable with one
consumer, and a way to break the other application silently with two. Run
`uv sync --frozen` so the lock is enforced rather than refreshed.

### The one thing that is not mechanical

**`src/juena/core/config.py` stays, almost unchanged.** It keeps its `Config` class, its
`os.getenv` calls, its `validate_required()` and its `global_config =
Config.initialize()`. It **gains** one thing — a call, at the end, building a
`CoreSettings` from its own values and handing it over:

```python
juena_core.configure(CoreSettings(
    OPENAI_API_KEY=Config.OPENAI_API_KEY,
    DATABASE_URL=Config.DATABASE_URL,
    ...
))
```

**Do not move `Config` into core.** Its `validate_required()` knows about SAML,
production HTTPS, and whether this particular deployment should enable its optional
sandbox. Core supplies a settings object but never reads that environment. This is the
decision from 00: *an application extends core configuration by not extending it.*

### The sandbox re-point is explicit

CP7 changed the boundary after the original test split was written. Delete the generic
Python implementation from `src/juena/sandbox/` and re-point its consumers to
`juena_core.sandbox`. Keep only `software.py` and
`repository-requirements.txt` in the application package; keep the sandbox Dockerfile,
systemd unit, Compose mounts, launcher commands and runbooks in juena-chatbot.

Immediately after configuring base core, construct the optional settings from the
application's existing `Config` values:

```python
from juena_core.sandbox.config import SandboxRuntimeSettings, configure_sandbox

configure_sandbox(SandboxRuntimeSettings(
    enabled=Config.SANDBOX_ENABLED,
    identity_secret=Config.SANDBOX_IDENTITY_SECRET,
    workspace_root=Config.SANDBOX_WORKSPACE_ROOT,
    concurrency=Config.SANDBOX_CONCURRENCY,
    execution_timeout_seconds=Config.SANDBOX_EXECUTION_TIMEOUT_SECONDS,
    max_output_bytes=Config.SANDBOX_MAX_OUTPUT_BYTES,
    workspace_limit_bytes=Config.SANDBOX_WORKSPACE_LIMIT_BYTES,
    idle_ttl_seconds=Config.SANDBOX_IDLE_TTL_SECONDS,
    cpu_limit=Config.SANDBOX_CPU_LIMIT,
    memory_limit=Config.SANDBOX_MEMORY_LIMIT,
))
```

The service registers `register_sandbox_interrupt()`, passes
`SandboxResumeInput`, `ThreadWorkspace(stage=stage_runtime_inputs,
delete=delete_runtime_workspace)`, the current sandbox `StreamPolicy`, and
`sandbox_lifespan` to `create_app()`. The software specialist imports
`build_sandbox_backend`, `SandboxExecutionMiddleware`, `sandbox_interrupt_on` and
`sandbox_enabled` from core. Preserve the all-or-nothing middleware/approval pair.

Change the host worker entrypoint to:

```bash
uv run python -m juena_core.sandbox.worker
```

`sandbox` is a `juena-core` dependency extra selected in `pyproject.toml`, not an
extra declared by the `juena` project. Passing `--extra sandbox` to `uv run` would
ask uv for an application extra that does not exist.

Do not move the Podman socket into the application container. The worker remains a
non-root host process; it and the API share only Postgres and the configured workspace
root. Confirm the API-side settings and the worker environment agree on concurrency,
CPU/memory, workspace quota and TTL.

### Two things that are new code, not a re-point

**`AgentClient` subclasses `BaseAgentClient`** (00, decision 10). Core does not get
`get_current_user` or `list_research`, because `/auth/me` and `/research` are
juena-chatbot's routes. The subclass adds both, and `client_setup.py` builds it instead
of the core class. `test_agent_client` splits along the same line.

**`chats.agent_id` needs a backfill.** The column arrives from core not-nullable (01/CP3)
and there is no Alembic, so `create_all` will not add it to an existing table at all.
Run it once, by hand, and record that you did:

```sql
ALTER TABLE chats ADD COLUMN IF NOT EXISTS agent_id VARCHAR(64);
UPDATE chats SET agent_id = 'juena' WHERE agent_id IS NULL;
ALTER TABLE chats ALTER COLUMN agent_id SET NOT NULL;
```

`'juena'` because that is the only agent this application has ever registered
(`JUENA_AGENT_ID`). Take a dump first — this is the one step in the plan that touches
live rows.

### What actually landed

**Step 2 completed 2026-09-16 in juena-chatbot commits `b5cd33a`, `21210ac` and
`aa23497`**, against core `78fc3dd` and `347d5a5`. 122 files, +1,816 / −10,347:
44 application modules deleted, their imports re-pointed, and five pieces of genuinely
new code written. The latter commits are review corrections; findings 3, 6 and 7 below
record their substantive changes.

```text
./juena test-integration            16 passed   (baseline: 16)
reduced pre-step-3 unit selection   340 passed, 5 skipped, 18 failed
prompt files                        byte-identical
core suite                          384 passed, 5 skipped
./scripts/check-imports.sh          import direction ok
chats.agent_id backfill             209 rows, all 'juena', column NOT NULL
docker compose build                fails -- see finding 8; step 3.5 precedes step 4
```

That unit number is an explicitly reduced diagnostic run, not `./juena test`: the full
command stops during collection while files that still import removed source-only names
remain in the application. Step 3 owns those moves and the identity reconciliation; the
Step 2 acceptance evidence is the green Postgres wiring suite plus the focused tests for
each changed seam.

#### The dependency set

`deepagents 0.6.12 → 0.7.14`, `langchain 1.3.14 → 1.4.0`, `langgraph 1.2.10 → 1.2.11`,
`starlette 0.50.0 → 1.6.0`, `streamlit 1.61.1 → 1.64.0`, `langchain-mcp-adapters`
**removed**. `langgraph-checkpoint-postgres`, `psycopg` and `sqlalchemy` were explicitly
upgraded to core's validated versions; the first `uv lock` had silently kept the
application's older exact pins, which would have shipped a set core never tested.
SQLAlchemy resolves to **2.0.54** here against core's locked 2.0.53 — a patch inside
core's declared bound, recorded rather than pinned down.

Direct dependencies now declare only what this application imports itself. Core carries
the validated bounds for the shared framework family, while this application's
`uv.lock` pins the complete resolved set. Duplicating those framework bounds here could
contradict core — `deepagents==0.6.12` against core's `>=0.7.13,<0.8` was exactly that.

#### Five things that were new code, not a re-point

| What | Why |
|---|---|
| `juena.clients.client.AgentClient(BaseAgentClient)` | `/auth/me` and `/research` are this application's routes (decision 10) |
| `juena.server.auth.principal` | the one place that turns a `SamlIdentity` into core's `Principal`; core's `upsert_principal` takes fields, never an assertion |
| `juena.server.service` | ~120 lines of `create_app(...)` arguments: the resume union, the `ThreadWorkspace`, the `StreamPolicy`, the manifest's closing paragraph, and three extra lifespans |
| `juena.server.database.models` | only `SamlLoginRequest` and `ResearchJob` remain; `Base`, `User`, `AuthSession`, `Chat` are core's, `sandbox_jobs` is core's optional model |
| `app/client_setup.py` | rebuilt thin: supplies `AgentClient`, `JUENA_AGENT_ID` and the application timeout to core's subclass-aware factory |

`juena.tools.context7` was rewritten onto `juena_core.mcp`: FastMCP's
`{"mcpServers": {...}}` config with the transport inferred, and no client to hold. That
is what made removing `langchain-mcp-adapters` possible rather than merely tidy.

#### Findings — things this step surfaced that no test in core could

**1. `create_app` closed agents before an application's own lifespans unwound.** A
boundary defect, fixed in core (`78fc3dd`) rather than shimmed. juena-chatbot ran
`research_runner.shutdown()` — which waits for specialists running detached from any
request — and only then closed its agents. Entering the extra lifespans inside the `try`
whose `finally` called `shutdown_agents()` inverted that. The permanent regression in
core's `test_server_contracts.py` was checked by reverting the fix and watching it fail.

**2. Patching `global_config` no longer reaches core, and the Postgres suite was about
to run against the development database again** — the exact regression `40c846b` fixed.
`connection.py` opens its pool against `settings().DATABASE_URL`, and core does not read
`global_config` by design. Sixteen hand-written patches became one autouse fixture that
sets *both* and asserts the result, because the failure is silent: the tests still pass,
against the wrong database, destroying rows someone was using.

**3. Deep Agents 0.7 overwrites an existing path where 0.6.12 refused it.**
`StateBackend.write` used to return "... because it already exists" and send the model to
`edit_file`; it now calls `update_file_data`. `/findings/<slug>.md` is written across
turns, so a second `write` silently replaced a finished report.

> **Corrected in review.** This was first recorded as accepted, with the AGENT.md
> sentence "extend it with `edit_file`" named as the only guard. A prompt is not a
> guard: it is advice a model may ignore, and the evidence it protects is the one thing
> `<verified_by_server>` exists to keep honest. The contract is restored where it
> belongs — `FindingsStateBackend.write` refuses an existing path and names `edit_file`,
> whatever upstream does (core `347d5a5`). The server-side merge in
> `juena.research.delivery` writes state directly rather than through the backend, so it
> is unaffected. **No prompt file changed**, and the prompt sentence is a courtesy again
> rather than load-bearing.

**4. Core's settings are configured only when `juena.core.config` is imported.** Before
the cutover, `juena.core.log` imported `Config` at module scope and `get_logger` was
imported nearly everywhere, so importing almost anything read `.env`. Core deliberately
does not, so configuration became an explicit act. All four entry points already perform
it — `main.py`, `juena.server.service`, `app/streamlit_app.py` — and `tests/conftest.py`
is the fourth, now saying so. `python -m juena_core.sandbox.worker` needs no core
settings at all: it reads `SandboxWorkerSettings.from_env()` and nothing else.

**5. `uv sync --frozen` silently keeps a stale copy of core.** A path dependency is
installed as a *copy*, and the version does not change when its source does, so nothing
reinstalls. `juena_core.__file__` still resolves inside the virtual environment, so the
check in step 3 passes while the bytes are old. **After changing core, sync with
`--reinstall-package juena-core`** and verify a symbol you just changed.

**6. `initialize_client` in core could not be used by an application that subclasses
`BaseAgentClient`** — which, by decision 10, is every application that serves a route of
its own. It hardcoded the class. **Fixed in review** rather than worked around: it takes
a `client_class`, and `app/client_setup.py` passes `AgentClient` while still owning
`JUENA_AGENT_ID` and the timeout. One construction site, two applications.

**7. The approval card promised 2 vCPU / 4 GB while the worker ran 1 vCPU / 2 GB.**
Found in review. `./juena` exported `SANDBOX_CPU_LIMIT=1` / `SANDBOX_MEMORY_LIMIT=2g`
for the host worker alone; the API never received them, so `sandbox_settings()` fell back
to core's defaults and the card described a machine twice the size of the one Podman
would enforce. The plan named this risk and nothing checked it.

Fixed on all four sides: `Config` reads the same four variables (`SANDBOX_CPU_LIMIT`,
`SANDBOX_MEMORY_LIMIT`, `SANDBOX_WORKSPACE_LIMIT_BYTES`, `SANDBOX_IDLE_TTL_SECONDS`) and
passes them to `configure_sandbox`; `docker-compose.yml` passes them into the API
container; `./juena` exports one set for both consumers; `env.example` and
`deploy/sandbox-worker.env.example` carry them. Two permanent checks, each proven by
breaking the code: core's `test_approval_card_reports_the_configured_worker_limits` now
configures **1 / 2g** rather than asserting the defaults it was handed — the old version
passed whether the card read configuration or hardcoded it — and
`test_sandbox_api_uses_the_worker_limit_environment` reads them back through a real
subprocess. `./juena up` then runs `verify_sandbox_limits_agree`, comparing what the API
container holds against a non-secret snapshot written when the current worker process
started, and refuses to continue on a difference or an unreadable value. The review's
first version compared against the current shell instead, which said nothing about an
already-running worker, and omitted concurrency; the final check covers concurrency,
CPU, memory, workspace quota and TTL.

**8. The application image cannot be built with the old build context.**
Measured, not predicted: `docker compose build` fails with
`Distribution not found at: file:///juena-core`. `context: .` cannot see the sibling
directory that `[tool.uv.sources]` points at, and the running container is still a
pre-cutover image. The old ordering put the parent-context build in step 6, after the
step-4 runtime proof that requires that image. The review moved the build into step 3.5.
Nothing else about step 4 has been attempted, and no running-system claim in this record
rests on the pre-cutover container.

#### Reclassifications for step 3, found by executing step 2

- **`test_api_endpoints_files` moves to core**, rather than staying. Both tests reach
  into core's router: `_authorize_thread` is now a closure inside `build_api_router`,
  and `router` is a factory. Preserve both identities at the route boundary.
- **`test_postgres_integration` stays whole.** Its former private-helper recency
  assertion cannot stay there; the destination regression is named below.

  > **Corrected in review.** The comment left in its place said core asserts recency
  > "in `test_server_routes_postgres.py`", and it did not: the assertion was removed
  > from the application before its replacement existed, on the strength of a claim
  > nobody had checked. `test_authorizing_a_message_touches_chat_recency` now exists
  > there, driving a real `/{agent_id}/stream` request against a real database, and it
  > was verified by deleting `chat.updated_at = utc_now()` and watching it fail. A
  > "moved to core" note in a diff is worth nothing until the destination is named and
  > run.
- **`test_client_setup` stays.** Its assertion is application policy: combine
  `Config.TIMEOUT_SECONDS`, `JUENA_AGENT_ID` and JüNA's `AgentClient` subclass through
  core's generic factory.
- **`test_chat_interface` splits.** Generic SSE folding, status dispatch and interrupt
  cards are core's; sandbox wording, starter topics, upload validation and page
  composition remain JüNA's.
- `test_chat_storage` and `test_sidebar` now import `AgentClient` from this application
  while testing core's `ChatStorage`; step 3 decides which side each belongs on.

#### Operational half

`./juena`, the systemd unit and `deploy/SANDBOX.md` now start
`python -m juena_core.sandbox.worker`. Nothing else about the worker moved: it is still
a non-root host process, it still reads its own environment, and no container gained a
Podman socket.

The `chats.agent_id` backfill ran once against the development database, after
`pg_dump` (39 MB, kept in the ignored `.sandbox/backups/`): 209 rows, all `'juena'`,
column now `NOT NULL`.


---

## Step 3 — split the tests, then reconcile

**A test that exercises a core module moves to juena-core. A test that exercises the
wiring stays here.**

The 46 modules, mapped by what they import after CP7's boundary amendment:

### Moves to juena-core — 22

`test_agent_backends` · `test_agent_input_handler` · `test_api_endpoints_files` ·
`test_ask_user` · `test_chat_storage` · `test_code_chat_inputs` ·
`test_llm_models` · `test_loop_guard` · `test_math_rendering` ·
`test_runtime_model_middleware` · `test_server_utils` · `test_streaming_handlers` ·
`test_specialist_outcome` · `test_artifact_message_middleware` ·
`test_sandbox_artifacts` · `test_sandbox_backend` · `test_sandbox_approvals` ·
`test_sandbox_executor` · `test_sandbox_middleware` ·
`test_sandbox_pipeline_integration` · `test_sandbox_worker` ·
`test_sandbox_workspace`

### Stays — 20

`test_agent_prompts` · `test_agent_resources` · `test_bootstrap` ·
`test_client_setup` · `test_config_paths` · `test_context7_tools` ·
`test_juena_agent_runtime` · `test_main` · `test_postgres_integration` ·
`test_rag_index` · `test_repo_config` · `test_repo_manager` ·
`test_repo_search_tools` · `test_research` · `test_saml_auth` · `test_sidebar` ·
`test_specialists` · `test_starters` · `test_supervisor_routing` · `test_tavily_tools`

### Splits — 4

| Module | Core half | App half |
|---|---|---|
| `test_agent_client` | `BaseAgentClient` transport, SSE parsing, core routes | `get_current_user` (`/auth/me`), `list_research` (`/research`) |
| `test_chat_interface` | SSE chunk folding, status dispatch and generic interrupt cards | sandbox wording/renderers, starters, upload validation and page composition |
| `test_findings_lifecycle` | `test_registration_wraps_every_specialist` already exists in core's `test_findings_and_delegation.py`; delete the duplicate app copy | background-job merge, conflict and delivery lifecycle |
| `test_ui_components` | message, token and artifact rendering | logo and header |

`test_agent_client` moved from the "moves whole" column once the client itself split
(00, decision 10). The four former sandbox-related splits now move whole because both
their generic contracts and optional implementation are core-owned. The baseline audit
also found one already-copied generic test inside `test_findings_lifecycle`, so that file
now splits rather than retaining a duplicate. The Step 2 review corrected
`test_client_setup` to stay, `test_api_endpoints_files` to move, and
`test_chat_interface` to split. **22 move, 20 stay, 4 split.**
`test_sandbox_config` and `test_simple_chat_example` are pre-existing core tests rather
than chatbot baseline nodes that move.

**`test_postgres_integration.py` does not split.** After the re-point it imports core
server/sandbox modules beside `juena.research`, application identity and application
configuration — which is exactly what makes it worth keeping whole. It is the only test
that exercises that wiring against a real database.

### The reconciliation, which is the instrument

Collect node ids from both repositories, normalise the paths, and **diff against the
unique pre-cutover union** — do not compare totals and do not compare only against the
chatbot list. The latter would misclassify core's 272 core-only identities as additions.

Node ids look like `tests/test_loop_guard.py::test_blocks_repeat`. A test that moves or
splits may change its module path while retaining the same test identity, so **compare
on the part after the first `::`**. The chatbot list is unique on that identity; the
cross-repository baseline has the 113 known overlaps described above. Do not use
`sort -u` after combining the post-cutover repositories, because that would hide a test
accidentally left in both.

```bash
# Run from the directory that contains all three sibling repositories.
cd /Users/az-ihsan/Documents/kerjaan-ihsan/post-doc/JueNA_knowledge_base
PLAN_DIR="$(pwd)/Vitess-AI-Agent/docs/execution-plan"

# One line per collected test, whatever a parametrised id contains. This is the
# same failure-preserving collector used in step 1.
collect() { # $1 = repository; remaining arguments are uv-run options
    repo="$1"; shift
    if ! collected="$(
        cd "$repo" &&
        PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PLAN_DIR" \
            uv run "$@" pytest --collect-only -q \
                -p 02-collect-nodeids tests/ 2>&1
    )"; then
        printf '%s\n' "$collected" >&2
        return 1
    fi
    printf '%s\n' "$collected" |
        awk -F '\t' '$1 == "NODEID" {sub(/^[^\t]*\t/, ""); print}' |
        sort
}
collect juena-core    --frozen --group dev > /tmp/after-core.txt
collect juena-chatbot --extra dev          > /tmp/after-app.txt

identity_only() { sed 's|^[^:]*::||' | sort; }
cat "$PLAN_DIR/02-baseline-nodeids.txt" \
    "$PLAN_DIR/02-core-baseline-nodeids.txt" |
    identity_only | uniq > /tmp/before-identities.txt
cat /tmp/after-core.txt /tmp/after-app.txt |
    identity_only > /tmp/after-identities-all.txt

# Every pre-cutover cross-repository duplicate must collapse during the cutover.
# Do not use `sort -u` here: that would hide a test left in both repositories.
uniq -d /tmp/after-identities-all.txt > /tmp/after-duplicates.txt
if [ -s /tmp/after-duplicates.txt ]; then
    printf 'duplicate post-cutover test identities:\n' >&2
    cat /tmp/after-duplicates.txt >&2
    exit 1
fi

uniq /tmp/after-identities-all.txt > /tmp/after-identities.txt
# Count identities, not the formatting lines emitted by `diff`: a replacement
# produces `<`, `---` and `>` lines, but it is one removal and one addition.
comm -13 /tmp/before-identities.txt /tmp/after-identities.txt \
    > /tmp/after-additions.txt
comm -23 /tmp/before-identities.txt /tmp/after-identities.txt \
    > /tmp/after-removals.txt
wc -l /tmp/after-additions.txt /tmp/after-removals.txt
diff /tmp/before-identities.txt /tmp/after-identities.txt
```

Reading `item.nodeid` from pytest also drops the `N tests collected in 1.23s` footer,
which would otherwise appear as a spurious difference every run. Use the **same**
collector on both repositories and on the step-1 baseline.

Moves disappear from the identity diff by design. Every line that remains is explained
in writing as either **added** (deliberately, named) or **removed** (deliberately, with
the reason), and `/tmp/after-duplicates.txt` must stay empty. Nothing else is acceptable.

A test that *vanished* in the move is the failure this catches, and it is the failure
most likely to happen: a file is moved, its imports are not updated, and pytest silently
collects fewer files and reports green. **Comparing counts would hide exactly this**
whenever a removal happens to coincide with an addition — which, in a refactor that adds
tests, it very often does.

### Verify that the installed core is the code being imported

An editable install, a stale `site-packages` copy, or a path entry can leave the suite
testing the old in-repo modules while everything looks green:

```bash
uv run python -c "import juena_core, sys; print(juena_core.__file__)"
```

It must resolve inside the virtual environment from the pinned revision — not to a
working copy. Check this once here and once again after the final sync. A venv path alone
does not prove freshness: uv installs this path dependency as a copy and may keep it
after the sibling source changes. Reinstall and compare a module changed by the recorded
core commit:

```bash
uv sync --frozen --extra dev --reinstall-package juena-core
uv run python - <<'PY'
from hashlib import sha256
from pathlib import Path
import juena_core.agents.backends as installed

source = Path("../juena-core/src/juena_core/agents/backends.py")
assert sha256(Path(installed.__file__).read_bytes()).digest() == sha256(source.read_bytes()).digest()
print(installed.__file__)
PY
```

### What actually landed

**Step 3 completed 2026-09-16** in core `b9e2304` and chatbot `8a8f448`; its review
corrections are core `4eca16e` and chatbot `ed4a307`. The reconciliation passed with
**no duplicate identities** and 35 changed identities — 18 additions and 17 removals —
every one of which is named below. The first execution record incorrectly reported 21
additions and 20 removals. A fresh `comm` comparison gives 18/17; classic `diff` prints
69 lines for the same sets — 35 identity lines plus 34 hunk markers and separators — so
its raw output length is not an identity count.

```text
juena-core  tests/                        500 collected  495 passed, 5 skipped
juena-chatbot ./juena test                230 collected  230 passed
juena-chatbot ./juena test-integration     16 passed     (baseline: 16)
post-cutover unique identities            746            (pre-cutover union: 745)
duplicate identities across both repos       0
added identities                             18
removed identities                           17
./scripts/check-imports.sh                import direction ok
agent prompt Markdown and @tool docstrings byte-identical to chatbot `ee9248d`
installed juena_core                      in the venv, byte-identical to the sibling source
```

Neither repository's `src/` changed. This step moved tests and nothing else, apart from
the `pyproject.toml` test configuration and development dependency recorded under *What
else changed* below.

#### Moving meant four different things

Plan 01 wrote core's tests fresh, as **contracts**; juena-chatbot's are the detailed
**behavioural** suite for the same code. So "22 modules move" resolved into four
different operations, and which one applied was decided by comparing identities, never
by comparing file names:

| Operation | Modules | What happened |
|---|---|---|
| **Deleted as superseded** | 13 | `test_agent_backends`, `test_artifact_message_middleware`, `test_ask_user`, `test_loop_guard`, `test_specialist_outcome` and the eight `test_sandbox_*` modules. Core already held every identity, at equal or finer grain. |
| **Moved whole** | 9 | `test_agent_input_handler`, `test_code_chat_inputs`, `test_llm_models`, `test_runtime_model_middleware`, `test_server_utils`, `test_streaming_handlers`, `test_ui_components`, plus `test_math_rendering` and `test_chat_storage`, which **replaced** plan-01 placeholders rather than joining them. |
| **Moved and partly superseded** | 1 | `test_api_endpoints_files`: the deletion contract moved to core and the recency contract already existed there under the same identity. Nothing remained application-owned. |
| **Split** | 3 | `test_agent_client`, `test_chat_interface`, `test_findings_lifecycle`. |

#### Reclassifications, found by doing it

- **`test_ui_components` moves whole; it does not split.** The plan's split line kept
  "logo and header" here. The file contains no logo or header test — all 19 of its
  identities drive a renderer core now owns. That the page draws this product's header
  is asserted from `test_chat_interface`, where it always was.
- **`test_api_endpoints_files` is a move plus a delete, not a split.**
  `test_delete_thread_endpoint_removes_persisted_state` moved to core's
  `test_server_contracts.py`, rebuilt on `build_api_router` because `delete_thread` is a
  closure inside it now, and extended to assert all three stores a thread leaves traces
  in — checkpointer, artifact store and workspace. Its sibling
  `test_authorizing_a_message_touches_chat_recency` was deleted here: the same identity
  already exists in core's `test_server_routes_postgres.py`, against a real database, as
  the step-2 review recorded.
- **`test_findings_lifecycle` loses four identities, not one.** The plan named the
  `test_registration_wraps_every_specialist` duplicate. Three more tests in that file
  drive `SpecialistDelegate`, which is core's, and core's versions assert strictly more.
  One of the application's copies asserted `"sandbox_execution_events" not in result` —
  a channel renamed in 01/CP7 — so it had been passing vacuously. What stayed is the
  background-job merge, conflict and delivery lifecycle, which is this application's.
- **`test_agent_client` splits 5/2, not 8/2.** Three of its identities are gone rather
  than moved; they are named under *Removals* below.

#### A new file, and two placeholders replaced

`juena-core/tests/test_ui_streaming.py` is the core half of `test_chat_interface`: 16
moved identities covering the stream loop, the chunk classifiers, the status container
and the two interrupt cards. Three things changed in the move, and all three are the
couplings CP5 turned into parameters — the decision key is `interrupt_decision:` rather
than `sandbox_decision:`, an approval card is drawn only when the caller supplies an
`ApprovalCard`, and `stream_and_display_resume` takes `kind=` with the arm's fields as
keywords instead of a positional decision.

`juena-core/tests/test_ui_components.py` is the 19 identities of the application's
module, re-pointed at `juena_core.ui.components` and otherwise unchanged. It replaced
two of CP5's coarser contracts, which its own docstring names.

#### Additions — 18, each deliberate

Two are this step's, written because the split itself removed a guarantee:

| Added | Why |
|---|---|
| `test_an_approval_goes_unrendered_when_no_card_is_supplied` (core) | `render_pending_interrupt(approval=None)` is v2's case, and drawing nothing is the honest outcome — core has no kind to resume with. Proved by deleting `and approval is not None` and watching the card renderer be entered. |
| `test_a_pending_interrupt_replaces_the_composer` (chatbot) | Every page test now mocks `render_sandbox_interrupt`, so without this one nothing would say the page consults it at all. Proved by deleting the `return` and watching `st.chat_input` be called. |

Nine are one parametrisation: `test_module_does_not_import_an_application[...]` gains a
case per file that arrived in `juena-core/tests/`, `conftest.py` included. Covering the
moved tests is exactly why that rule runs over `tests/` as well as `src/`.

The remaining seven are **step 2's**, appearing here only because the reconciliation runs
now and the baselines predate core `78fc3dd` and `347d5a5`. Each is recorded in step 2's
findings: `test_extra_lifespans_unwind_before_the_agents_they_may_be_using` (finding 1);
`test_findings_keep_create_and_edit_apart_whatever_deep_agents_does` and
`test_write_file_cannot_replace_an_existing_finding` (finding 3);
`test_initialize_client_builds_an_application_client_subclass` (finding 6);
`test_sandbox_api_uses_the_worker_limit_environment` (finding 7); and
`test_an_unreachable_context7_costs_a_capability_not_a_startup` with
`test_shutdown_closes_an_instance_that_asks_to_be_closed` from the Context7 rewrite onto
`juena_core.mcp` — which is also why
`test_load_optional_context7_tools_logs_warning_and_returns_none_on_failure`,
`test_shutdown_agents_closes_cached_context7_clients` and
`test_existing_path_write_behaviour_is_left_to_the_backend` leave.

#### Removals — 17, each with the identity that covers the same ground

**Plan-01 placeholders replaced by the behavioural suite (8).** Five in
`test_math_rendering` — `test_normalize_math_markdown_rewrites_aliases`,
`test_normalize_math_markdown_skips_code`,
`test_repair_latex_delimiters_wraps_bare_equation`,
`test_command_reference_prose_is_not_treated_as_equation`,
`test_trailing_equation_fragment_is_repaired` — each covered at finer grain by the
16-test file that replaced them. `test_chat_storage_is_never_shared_between_sessions`,
built on `Mock`, replaced by
`test_chat_storage_never_shares_clients_between_browser_sessions` on a real
`BaseAgentClient`. `test_sanitize_assistant_content_removes_unrenderable_local_images`
and `test_artifact_history_fetch_uses_the_session_client`, replaced by the finer suite
in `test_ui_components.py`.

**Older identities superseded by a differently named core contract (8).**
`test_the_supervisors_private_working_memory_does_not_reach_a_specialist` and
`test_a_state_field_nobody_allowlisted_does_not_cross_either` →
`test_only_inputs_and_findings_cross_into_a_specialist`, which asserts both the file
allowlist and that no unlisted state field crosses.
`test_only_the_report_and_new_findings_come_back` →
`test_only_the_report_and_changed_findings_cross_back`. The reasoning those three
carried was transplanted into core's versions, which had none.
`test_stream_uses_multipart_endpoint_when_attachments_are_present` →
`test_stream_uses_multipart_and_leaves_the_read_timeout_open`, extended here with the
`write` and `pool` halves of the timeout assertion.
`test_resume_stream_posts_exact_decision` →
`test_resume_stream_keeps_interrupt_kind_application_defined`, extended here to assert
that the provider and model travel with a resumed turn. The three old Context7 contracts
— `test_load_optional_context7_tools_logs_warning_and_returns_none_on_failure`,
`test_shutdown_agents_closes_cached_context7_clients` and
`test_existing_path_write_behaviour_is_left_to_the_backend` — were replaced by the two
stricter lifecycle contracts named under *Additions*.

`test_authorizing_a_message_touches_chat_recency` and
`test_registration_wraps_every_specialist` do not appear in this removal list: their
application copies were deleted, but the same identities survive in core. Collapsing a
cross-repository duplicate is deliberately invisible in a unique-set delta.

**A contract that no longer exists (1).**
`test_resume_stream_rejects_an_ambiguous_reply` asserted that the client refuses a
resume carrying neither a decision nor an answer. CP5's `resume_stream` takes an
explicit `kind` and passes the arm's fields straight through, so there is no ambiguity
left for the client to detect; the server's discriminated union rejects a bad arm
instead. Nothing replaces it, because nothing should.

#### What else changed

`juena-core/pyproject.toml` gains `[tool.pytest.ini_options]` with `testpaths` and the
`LangChainDeprecationWarning`-as-error filter juena-chatbot has carried since before the
extraction. Core had no pytest configuration at all, so the warning that announces a
framework call is about to stop working was scrolling past in a green run — and with two
consumers, both would inherit the breakage from core at once.

The review also adds `streamlit>=1.53.0` to core's development group. Moving the UI
behavioural tests made Streamlit a test dependency, but the first run reused a venv that
had previously installed the `ui` extra. In a genuinely isolated frozen environment,
`uv run --group dev` failed at `import streamlit`; the development group now makes the
documented test command self-contained without making Streamlit a base runtime
dependency. Both lock files were refreshed: core records the development dependency,
and the chatbot's lock records the updated metadata of its path dependency. No resolved
runtime version changed.

`juena-core/tests/conftest.py` gives the moved tests configured settings through a
`configured` fixture and a `settings_factory`, rather than a sixth copy of
`make_settings`. The four modules that keep their own copy do so because their defaults
— a DEBUG log level, a real database DSN, populated API keys — are what those tests are
about.
---

## Step 3.5 — build the first consumer before runtime proof

Step 4 exercises the Compose application, so its image must already contain the
cutover. A sibling path dependency cannot be copied from the old `context: .`; building
after the runtime proof is impossible sequencing.

Only after step 3's suites and identity reconciliation pass:

1. commit the Step 3 changes, then verify both the chatbot and core trees are clean;
2. record `git -C ../juena-core rev-parse HEAD` and prove
   `uv sync --frozen --extra dev --reinstall-package juena-core`;
3. change the Compose build to parent context (`context: ..`,
   `dockerfile: juena-chatbot/Dockerfile`) and make every Dockerfile `COPY` source
   relative to that context, including `juena-core/`;
4. add `Dockerfile.dockerignore` beside the Dockerfile. Because the context is the
   parent, the repository `.dockerignore` is not consulted. Exclude sibling `.git/`,
   `.venv/`, caches, databases, models and unrelated repositories, while explicitly
   retaining only `juena-chatbot/` and `juena-core/` inputs needed by the build;
5. run `docker compose build` with no Git/core credentials, then record the core SHA,
   resolved dependency set and image digest in the application's build record.

The Dockerfile performs the copy. Do not add a launcher command that vendors core
before the build: that copy can be skipped or stale and is invisible where build
failures are debugged.

---

## Step 4 — prove it against the running system

Unit tests do not cover the four paths that matter. Each is one conversation.

```bash
./juena rag-up && ./juena up && ./juena health
```

**1. Delegation and the verified report.** Ask a repository question. Confirm the
supervisor delegates to `software-specialist`, that the returned message carries
**both** `<specialist_report>` and `<verified_by_server>`, and that the UI shows the
supervisor's answer rather than the specialist's working notes.

**2. Sandbox with approval.** Use the "Plot with Python" starter. Confirm the approval
card appears, that approving actually runs the command, and that the PNG arrives as an
artifact. This exercises the interrupt-kind dictionary from 00 and the lifted
`ArtifactStore` in one go.

**3. `ask_user`.** Ask something deliberately ambiguous. Confirm the clarification card
appears and that answering resumes the **same** thread.

**4. Background research, collected on a later turn.** Start one, send another message,
and confirm the result is reconciled in. This depends on `findings.py` having crossed
the boundary intact.

**Then reload the browser and reopen a conversation that existed before the cutover.**
The checkpointer, the `juena_display_text` key and the message ids are all core's now.
A pre-cutover thread must render identically after it. This is the check that catches a
renamed literal.

---

## Step 5 — the SAML check that is easy to skip

```bash
AUTH_DEV_BYPASS=false ./juena up
./juena sp-metadata
```

The metadata document must still be produced, and a **real login must still work**.

The identity seam is the change most likely to look completely fine under
`AUTH_DEV_BYPASS=true` and be broken in production. Running only the development path
proves nothing about the one that matters.

---

## Step 6 — lock the direction

Add to `./juena`:

```bash
cmd_check_imports() { ## Fail if juena-core reached back into an application
    ( cd "${JUENA_CORE_REPO:-$REPO_ROOT/../juena-core}" && ./scripts/check-imports.sh )
}
```

and call it from `cmd_test`.

It is the rule that is cheapest to keep and most expensive to have broken. Nothing else
enforces it.

---

## What actually landed — steps 3.5 to 6

**Completed 2026-09-16 on branch `juena-core-cutover-runtime`**, taken off the
reviewed step-3 commits so that branch stayed still during its review. Core is on
a branch of the same name.

```text
juena-core          tests/                   497 passed, 5 skipped
juena-chatbot       ./juena test             230 passed
juena-chatbot       ./juena test-integration  16 passed     (baseline: 16)
./juena check-imports                        import direction ok
02-compare-prompts.py ee9248d..HEAD          9 Markdown files, 6 @tool docstrings unchanged
build context transferred                    2.79 MB  (unfiltered parent: ~9 GB)
four step-4 conversations                    all four behave, one after a fix
pre-cutover threads reopened                 10 threads, 61 artifacts, 0 failures
```

**Step 4 found a defect that made the sandbox unreachable.** It is written up
first because it is the reason this plan exists.

### The defect: approving a command guaranteed it would not run

Every sandbox `execute` failed with
`RuntimeError: Sandbox execution requires a graph run_id`, retried three times
by `ToolRetryMiddleware` and surfaced to the model as a tool failure. The model
then proposed a slightly different command, which raised a fresh approval card,
which failed the same way. Four approvals produced four failures and no plot,
and the run ended with the agent explaining that it could only write the script.
Nothing in the transcript said the sandbox was broken.

**Where it came from.** 01/CP7 gave `ExecutionEvidence` a required
`graph_run_id` and added `_graph_run_id(runtime)` to obtain it, reading
`runtime.execution_info.run_id` and falling back to `runtime.config["run_id"]`.
Neither exists where that code runs:

- LangGraph's `Runtime` **has no `config`** at all — its own docstring says so;
- `ExecutionInfo.run_id` is filled from the config of *the graph that is
  running*. A subgraph does not inherit its parent's, so inside one it is
  `None`.

`execute` is bound on a specialist, and a specialist is a subgraph. So the id
was absent on every call the tool has ever served. Measured rather than
reasoned: a probe built from a real `create_agent` graph reports
`execution_info.run_id` as the config's value at top level and `None` one level
down.

**Why the suite was green.** `tests/test_sandbox_middleware.py` built its
runtime by hand as `SimpleNamespace(context=…, config={"run_id": "run-1"})` — an
object with a `config` attribute, which the real `Runtime` does not have, and a
`run_id` the real one does not carry. The stand-in was more generous than the
producer, so the tests passed against a condition that never occurs.

**The fix, in core.** The invocation id now travels in the runtime *context*,
which is passed into subgraphs unchanged, instead of the config, which
deliberately is not. `RuntimeModelContext` gains `run_id`;
`AgentInputHandler.build_run_context` sets it to the same value it puts in the
config; both `_graph_run_id` helpers read the context first and keep the old two
sources for a caller that invokes an agent directly. juena-chatbot's background
research runner, which builds its own context and never had a config `run_id`
at all, now passes `research:{job_id}`.

This is not a boundary correction and `00-BOUNDARY.md` needs no amendment. The
module is in the right repository; the id it needed was being read from the
wrong place.

**What now guards it.** Two tests in
`juena-core/tests/test_sandbox_middleware.py`. The first builds a real
`create_agent` graph with the real middleware and invokes it with a context
carrying the id and a config without one — the subgraph's exact condition — and
asserts the command reaches the tool. The second asserts the id written into the
evidence is the context's. Removing the context lookup makes both fail with the
production `RuntimeError`, which is how they were checked.

**One thing found and not fixed.** `ExecutionEvidenceMiddleware` is defined in
core and installed by nobody, so the root-level `<verified_by_server>` block for
undelegated execution is never produced. juena-chatbot always delegates, so
nothing is missing there; v2 should decide whether it wants that block before
03/CP4 relies on it.

### Step 3.5 — the parent-context build

The build context moved from this repository to its parent, so the Dockerfile
can `COPY juena-core/`. Three consequences, each in the files:

1. every `COPY` source is prefixed with a repository name;
2. core lands at `/juena-core`, because uv resolves `../juena-core` from the
   project directory `/app`;
3. `.dockerignore` is no longer consulted by any build. Docker looks for an
   ignore file named after the Dockerfile and falls back only to one at the
   context root, which is the parent and has none.

`Dockerfile.dockerignore` therefore excludes `*` and re-admits only
`juena-chatbot` and `juena-core`. The parent holds roughly nine gigabytes across
a dozen unrelated repositories, several carrying real credentials in their own
`.env`. It was verified by building a throwaway image that copied the whole
context and listed it, not by reading the rules: 2.79 MB, no `.env`, no `.git`,
no `.venv`, and all three prompt files present. An ignore rule that fails to
match looks exactly like one that works.

`deploy/BUILD-RECORD.md` is new and holds one entry per accepted image: core
SHA and clean tree, this repository's SHA, the `uv.lock` digest, the pinned
juena-rag revision and the image ID. No credentials are used by the build —
core is copied from the context and juena-rag is cloned anonymously over public
HTTPS.

**The step as written has no suite run, and that cost something.**
`tests/test_agent_resources.py` guards that the prompt Markdown reaches the
image, and it asserted `COPY src/ ./src/` and three `!src/**/*.md` exceptions in
`.dockerignore` — all three now false. It was caught on the next step's test run
rather than by the step that broke it. The guard now asserts the mechanism that
is actually in force, including that the new ignore file excludes no Markdown
at all: the old file kept the prompts through four exceptions to a blanket
`*.md` exclusion, so a fifth prompt in a new place would have been dropped
silently.

### Step 4 — the four conversations

Driven through `app.client_setup.initialize_client`, the same factory the
Streamlit page calls, so the server, the SSE vocabulary, the interrupt registry
and the artifact store are exercised exactly as the page exercises them. **What
this does not cover is the rendering**: that the card *appears*, and that the
PNG appears *in the chat*, was read off the stream rather than off a browser.
The renderers themselves are covered by core's UI tests.

1. **Delegation and the verified report.** The supervisor delegated to
   `software-specialist` and the result carried both blocks with
   `STATUS: VERIFIED`; the message the page would show is the supervisor's
   prose, not the specialist's working notes. Two earlier attempts returned
   `STATUS: UNVERIFIED` because the specialist looped on an identical
   `read_file` until the loop guard ended its run, and the machinery did the
   right thing with that: no structured report, so `NO_REPORT`, so the
   supervisor was directed to `ask_user` rather than to invent a result. The
   failure arm and the success arm were both observed.
2. **Sandbox with approval.** After the fix: one approval card, one approved
   command, exit 0, and `sine_plot.png` (74,908 bytes, 1482×880) delivered as
   an artifact and downloaded through the API. Before the fix, four approvals
   and nothing.
3. **`ask_user`.** "Fit my data." raised a clarification card with four options;
   answering it resumed **the same thread id**, and the persisted history holds
   the original question and the answer.
4. **Background research, collected later.** Both arms. A failed job was
   delivered as a failure and a succeeded job delivered its verified report,
   each on a later turn, each stamped `collected_at` by
   `ResearchDeliveryMiddleware`. The supervisor called `list_research` and
   `check_research` when asked whether there was news; it did not volunteer
   this unprompted, which is prompt behaviour and the prompts are byte-identical.

**Reopening pre-cutover threads.** Ten threads owned by the development user,
dating from 2026-08-05, all reopened with every message and every id intact.
They hold 61 artifact references and **all 61 downloaded through core's artifact
endpoint at their recorded byte size** — the strongest evidence available that
the lifted `ArtifactStore` reads pre-cutover data. In the checkpoint blobs the
loop-guard literal `juena_repeated_tool_call` appears 13 times, unchanged.
`juena_display_text` appears nowhere in the live database, so its preservation
is asserted by core's tests and not by this deployment's data — worth stating
rather than claiming a check that did not happen. `sandbox_execution_events`
appears nowhere either, which is why 01/CP7's rename touched no live state, and
also why juena-chatbot's old test asserting its absence had been passing
vacuously.

### Step 5 — SAML with the bypass off

`AUTH_DEV_BYPASS` reaches the container through the mounted `.env`, not through
Compose, so setting it on the launcher's command line changes nothing — it has
to be changed in the file. With it off:

- `/auth/dev-login` answers **404**, the production refusal working;
- `/auth/me` and `/chats` answer **401** through core's identity dependency;
- `/auth/login` answers **303** to `ifflogin.fz-juelich.de/saml/sso/redirect`
  with a signed `SAMLRequest`, which decodes to a complete `AuthnRequest`
  naming the SP as issuer, persistent `NameIDPolicy` and the right ACS URL;
  the request id is recorded in `saml_login_requests` for the ACS handler to
  correlate against;
- `./juena sp-metadata` produces a 4,007-byte `EntityDescriptor` with the SP
  certificate, one `AssertionConsumerService` and two `SingleLogoutService`
  endpoints.

**The one thing not done is the one the step names**: a human typing credentials
at the institute IdP. Everything up to the redirect is proved; the assertion
coming back is not. The `.env` was restored byte-identically afterwards.

### Step 6 — locking the direction

`cmd_check_imports` is in `./juena` and `cmd_test` calls it first, so the rule
runs on every unit-suite invocation rather than only on `test-all`. It warns and
passes when juena-core is not checked out beside the repository, because a
contributor without core should not be blocked from running tests by a check
that cannot run. Verified by adding `import juena` to
`juena_core/src/juena_core/log.py`: `./juena test` exits 1, names the file and
line, and pytest never starts.

### Commits

| Repository | Commit | |
|---|---|---|
| juena-core | `4eca16e` | the review's Streamlit development dependency |
| juena-core | `a64c978` | the subagent execution-evidence fix and its two tests |
| juena-chatbot | `ed4a307` | relock after core's development group changed |
| juena-chatbot | `2a9c1d7` | parent-context build |
| juena-chatbot | `6ef1a8b` | first build record |
| juena-chatbot | `6e536af` | invocation id for background research |
| juena-chatbot | `387d7be` | the packaging guard, rewritten for the new build |
| juena-chatbot | `0767d39` | `check-imports` in `./juena`, called from `cmd_test` |
| juena-chatbot | `43d4123` | build record for the proved image |

---

## Verification

1. **The collected node ids diff clean** against the step-1 baseline, with every moved,
   added and removed test explained in writing. Not the totals — the ids.
2. `./juena test-all` is green, and `juena_core.__file__` resolves into the virtual
   environment rather than a working copy.
3. `./scripts/check-imports.sh` in juena-core returns nothing.
4. All four conversations in step 4 behave as they did before the cutover.
5. A pre-cutover thread reopens and renders identically.
6. A real SAML login works with `AUTH_DEV_BYPASS=false`.
7. **No model-facing prompt text changed.** The authored Markdown below
   `src/juena/agents` and every LangChain `@tool` docstring are byte-identical to the
   recorded pre-cutover commit:

   ```bash
   uv run python ../Vitess-AI-Agent/docs/execution-plan/02-compare-prompts.py \
       ee9248d HEAD
   ```

   The earlier whole-`*.md` command was both over-broad and ineffective after commit:
   it compared the clean worktree to `HEAD`, and `deploy/SANDBOX.md` legitimately changes
   the worker module path in this cutover. The model's contract is not part of this
   refactor. A difference reported by the focused verifier means something crossed the
   boundary that should not have.
8. The parent-context Docker build succeeds, and its build record names the clean core
   SHA and image digest.
9. Compose gives no API/UI container a Podman socket; the host worker alone can reach
   rootless Podman, and its limits match `SandboxRuntimeSettings`.

---

## What could go wrong

| Risk | Guard |
|---|---|
| **A test disappears in the split and pytest reports green.** The likeliest failure | the pre/post identity-union diff and separate duplicate check in step 3 — a count comparison would miss a removal paired with an addition |
| The suite tests in-repo modules, not the installed core | `juena_core.__file__` resolves into the venv |
| `agent_id` backfill forgotten; `create_all` cannot add a not-null column to a live table | step 2's `ALTER`, run once, after a dump |
| `AUTH_DEV_BYPASS=true` hides a broken SAML path | step 5 |
| **Two SQLAlchemy `Base` objects.** If the app defines its own `DeclarativeBase` instead of importing core's, `create_all` builds core's tables from one metadata and the app's from another, and the `user_id` foreign keys fail at create time with an unresolved-table error | the `set(Base.metadata.tables)` test from 01/CP4 |
| A renamed literal (`juena_repeated_tool_call`, `juena_display_text`) breaks existing threads invisibly | step 4's reopen-an-old-thread check |
| Middleware order changes during the re-point | the class-name-order test from 01/CP2 |
| The API container receives the Podman socket | inspect resolved Compose mounts; only the non-root host worker may connect to Podman |
| API approval/admission limits differ from worker enforcement | compare `SandboxRuntimeSettings` with the worker environment in the configuration test and running-system preflight |
| The chatbot is built from an uncommitted or unrecorded core revision | require a clean core tree and record its commit SHA plus the resulting image digest (01/CP7) |

## If the boundary turns out to be wrong

That is a result, not a failure, and this is the plan designed to produce it. Record it
in `00-BOUNDARY.md` as an amendment naming the module, what forced the move, and which
direction it went. Amend core, rerun the affected Plan 01 verification, commit the result
and record the new core SHA before continuing. **Do not** work around a bad boundary with
a shim in the application — the shim outlives the memory of why it is there, and v2
inherits it.

## Status

| | |
|---|---|
| **Depends on** | 01, verified, committed, clean, with its core SHA recorded |
| **Unblocks** | 03 |
| **Executed** | steps 1, 2 and 3 complete. Step 1: clean baselines at chatbot `ee9248d` (473 node ids) and core `d086c01` (385 node ids), a 745-identity union with 113 expected overlaps, branch `juena-core-cutover`. Step 2: chatbot `b5cd33a`+`21210ac`+`aa23497` against core `78fc3dd`+`347d5a5` — 44 modules deleted, integration suite green at its baseline 16, prompts byte-identical, `chats.agent_id` backfilled over 209 live rows, and three defects fixed in core. Step 3: core `b9e2304`+`4eca16e`, chatbot `8a8f448`+`ed4a307`; 13 superseded modules were deleted, 9 moved whole, 1 moved with its other identity already superseded, and 3 split. The reconciliation passes at 746 unique identities, **zero cross-repository duplicates**, 18 deliberate additions and 17 deliberate removals. Steps 3.5, 4, 5 and 6 complete on branch `juena-core-cutover-runtime`, core at `a64c978`: the parent-context build ships a 2.79 MB context and its image is recorded in `deploy/BUILD-RECORD.md`; all four conversations behave and ten pre-cutover threads reopen with 61 artifacts intact; the SAML path produces a signed AuthnRequest and SP metadata with the bypass off; `./juena test` now runs the import check first. **Step 4 found and fixed a defect that made the sandbox unreachable** -- every approved `execute` raised `Sandbox execution requires a graph run_id`, because 01/CP7 read that id from a place that does not exist inside a subagent, which is the only place the tool is bound |
| **Decided** | the test split (22 / 20 / 4); `Config` stays in the app; generic sandbox Python moves to optional core while deployment assets stay; the two-baseline identity diff is the instrument; prompts must not change; `AgentClient` subclasses core's `BaseAgentClient`; `agent_id` is backfilled to `'juena'` |
| **Open** | one thing the plan cannot close: a **real SAML login** still needs a person to enter institute credentials. Everything up to the redirect is proved. Separately, `ExecutionEvidenceMiddleware` is defined in core and installed by nobody, so an undelegated run produces no `<verified_by_server>` block; harmless here, a decision for 03/CP4 |
| **Revised** | 2026-09-16 after steps 3.5--6 — step 3.5 gains a suite run in practice, because the build change broke `test_agent_resources.py` and the step as written never runs the tests; step 5 records that `AUTH_DEV_BYPASS` reaches the container through the mounted `.env` rather than Compose, so setting it on the launcher's command line does nothing; step 6's check warns rather than fails when juena-core is not checked out beside the repository. Earlier, 2026-09-16 after the Step 3 review — the reconciliation counts identities with `comm` (18 added / 17 removed), replacing the earlier incorrect 21/20 tally; the executed allocation is stated consistently as 13 superseded / 9 moved / 1 moved-and-partly-superseded / 3 split; and core's development group installs Streamlit so the frozen test command works in an isolated environment. The four implementation reclassifications remain: `test_ui_components` moves whole, `test_api_endpoints_files` is a move plus a delete, `test_findings_lifecycle` loses four application identities rather than one, and `test_agent_client` splits 5/2. Earlier Step 2 and Step 1 reviews, baseline corrections and 01/CP7 amendments remain in force |
