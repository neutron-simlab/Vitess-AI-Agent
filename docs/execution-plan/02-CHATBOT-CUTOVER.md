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
uv run --extra sandbox python -m juena_core.sandbox.worker
```

Do not move the Podman socket into the application container. The worker remains a
non-root host process; it and the API share only Postgres and the configured workspace
root. Confirm the API-side settings and the worker environment agree on concurrency,
CPU/memory, workspace quota and TTL.

### Two things that are new code, not a re-point

**`JuenaAgentClient` subclasses `BaseAgentClient`** (00, decision 10). Core does not get
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

**Step 2 completed 2026-09-16 in juena-chatbot commits `b5cd33a` and `21210ac`**, against
core `78fc3dd` and `347d5a5`. 119 files, +1,693 / −10,342: 44 application modules
deleted, their imports re-pointed, and five pieces of genuinely new code written. The
second commit on each side is the review's, and findings 3, 6 and 7 below record what it
changed.

```text
./juena test-integration            16 passed   (baseline: 16)
./juena test (test placement aside) 340 passed, 5 skipped, 18 failed
prompt files                        byte-identical
core suite                          384 passed, 5 skipped
./scripts/check-imports.sh          import direction ok
chats.agent_id backfill             209 rows, all 'juena', column NOT NULL
docker compose build                fails -- see finding 8; step 4 waits on step 6
```

**Every one of those 18 failures, and the 7 modules excluded from that run, is a test
whose *placement* step 3 decides** — files that move to core whole, or split. Not one is
an application defect: `test_agent_backends`, `test_code_chat_inputs`,
`test_sandbox_middleware`, `test_specialist_outcome`, `test_streaming_handlers`,
`test_artifact_message_middleware`, `test_sandbox_{approvals,artifacts,backend,executor}`
already exist in core under the same names, adapted; `test_agent_client`,
`test_chat_interface`, `test_ui_components` and `test_api_endpoints_files` split.

#### The dependency set

`deepagents 0.6.12 → 0.7.14`, `langchain 1.3.14 → 1.4.0`, `langgraph 1.2.10 → 1.2.11`,
`starlette 0.50.0 → 1.6.0`, `streamlit 1.61.1 → 1.64.0`, `langchain-mcp-adapters`
**removed**. `langgraph-checkpoint-postgres`, `psycopg` and `sqlalchemy` were explicitly
upgraded to core's validated versions; the first `uv lock` had silently kept the
application's older exact pins, which would have shipped a set core never tested.
SQLAlchemy resolves to **2.0.54** here against core's locked 2.0.53 — a patch inside
core's declared bound, recorded rather than pinned down.

Direct dependencies now declare only what this application imports itself, without
bounds: core pins the set they belong to, and a second bound could only duplicate or
contradict it — `deepagents==0.6.12` against core's `>=0.7.13,<0.8` being exactly that.

#### Five things that were new code, not a re-point

| What | Why |
|---|---|
| `juena.clients.client.AgentClient(BaseAgentClient)` | `/auth/me` and `/research` are this application's routes (decision 10) |
| `juena.server.auth.principal` | the one place that turns a `SamlIdentity` into core's `Principal`; core's `upsert_principal` takes fields, never an assertion |
| `juena.server.service` | ~120 lines of `create_app(...)` arguments: the resume union, the `ThreadWorkspace`, the `StreamPolicy`, the manifest's closing paragraph, and three extra lifespans |
| `juena.server.database.models` | only `SamlLoginRequest` and `ResearchJob` remain; `Base`, `User`, `AuthSession`, `Chat` are core's, `sandbox_jobs` is core's optional model |
| `app/client_setup.py` | rebuilt thin. Core's `initialize_client` builds a `BaseAgentClient`, which no application that subclasses can use — see *findings* below |

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
container holds against what the worker was started with, and refuses to continue on a
difference or an unreadable value.

**8. The application image cannot be built until step 6 moves the build context.**
Measured, not predicted: `docker compose build` fails with
`Distribution not found at: file:///juena-core`. `context: .` cannot see the sibling
directory that `[tool.uv.sources]` points at, and the running container is still a
pre-cutover image. **Step 4 is therefore blocked on step 6's Docker change**, which the
plan orders the other way round. Nothing else about step 4 has been attempted, and no
running-system claim in this record rests on a container.

#### Reclassifications for step 3, found by executing step 2

- **`test_api_endpoints_files` splits**, rather than staying. Both its tests reach into
  core's router: `_authorize_thread` is now a closure inside `build_api_router`, and
  `router` is a factory. Core already covers thread deletion against a real database.
- **`test_postgres_integration` keeps everything except one assertion.** The
  `_authorize_thread` recency check cannot be called from outside core any more.

  > **Corrected in review.** The comment left in its place said core asserts recency
  > "in `test_server_routes_postgres.py`", and it did not: the assertion was removed
  > from the application before its replacement existed, on the strength of a claim
  > nobody had checked. `test_authorizing_a_message_touches_chat_recency` now exists
  > there, driving a real `/{agent_id}/stream` request against a real database, and it
  > was verified by deleting `chat.updated_at = utc_now()` and watching it fail. A
  > "moved to core" note in a diff is worth nothing until the destination is named and
  > run.
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

`test_agent_backends` · `test_agent_input_handler` · `test_ask_user` ·
`test_chat_storage` · `test_client_setup` · `test_code_chat_inputs` ·
`test_llm_models` · `test_loop_guard` · `test_math_rendering` ·
`test_runtime_model_middleware` · `test_server_utils` · `test_streaming_handlers` ·
`test_specialist_outcome` · `test_artifact_message_middleware` ·
`test_sandbox_artifacts` · `test_sandbox_backend` · `test_sandbox_approvals` ·
`test_sandbox_executor` · `test_sandbox_middleware` ·
`test_sandbox_pipeline_integration` · `test_sandbox_worker` ·
`test_sandbox_workspace`

### Stays — 21

`test_agent_prompts` · `test_agent_resources` · `test_api_endpoints_files` ·
`test_bootstrap` · `test_chat_interface` · `test_config_paths` · `test_context7_tools` ·
`test_juena_agent_runtime` · `test_main` · `test_postgres_integration` ·
`test_rag_index` · `test_repo_config` · `test_repo_manager` ·
`test_repo_search_tools` · `test_research` · `test_saml_auth` · `test_sidebar` ·
`test_specialists` · `test_starters` · `test_supervisor_routing` · `test_tavily_tools`

### Splits — 3

| Module | Core half | App half |
|---|---|---|
| `test_agent_client` | `BaseAgentClient` transport, SSE parsing, core routes | `get_current_user` (`/auth/me`), `list_research` (`/research`) |
| `test_findings_lifecycle` | `test_registration_wraps_every_specialist` already exists in core's `test_findings_and_delegation.py`; delete the duplicate app copy | background-job merge, conflict and delivery lifecycle |
| `test_ui_components` | message, token and artifact rendering | logo and header |

`test_agent_client` moved from the "moves whole" column once the client itself split
(00, decision 10). The four former sandbox-related splits now move whole because both
their generic contracts and optional implementation are core-owned. The baseline audit
also found one already-copied generic test inside `test_findings_lifecycle`, so that file
now splits rather than retaining a duplicate. **22 move, 21 stay, 3 split.**
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
working copy. Check this once here and once again after the final `uv sync`.

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

### Lock and build the first consumer

Only after the cutover suite and running-system checks pass:

1. verify `git -C ../juena-core status --short` is empty and record
   `git -C ../juena-core rev-parse HEAD`;
2. commit juena-chatbot's regenerated `uv.lock`, then prove `uv sync --frozen`;
3. change the Compose build to parent context (`context: ..`,
   `dockerfile: juena-chatbot/Dockerfile`) and make every Dockerfile `COPY` source
   relative to that context, including `juena-core/`;
4. add `Dockerfile.dockerignore` beside the Dockerfile. Because the context is the parent,
   the repository `.dockerignore` is not consulted. Exclude sibling `.git/`, `.venv/`,
   caches, databases, models and unrelated repositories, while explicitly retaining only
   `juena-chatbot/` and `juena-core/` inputs needed by the build;
5. run `docker compose build` with no Git/core credentials, then record the core SHA,
   resolved dependency set and resulting image digest in the application's build record.

The Dockerfile performs the copy. Do not add a launcher command that vendors core before
the build: that copy can be skipped or stale and is invisible where build failures are
debugged.

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
7. **No prompt file changed.** `AGENT.md`, `SUPERVISOR.md` and every tool docstring are
   byte-identical:

   ```bash
   git diff --stat -- '*.md' 'src/juena/**/AGENT.md' 'src/juena/**/SUPERVISOR.md'
   ```

   The model's contract is not part of this refactor. A diff there means something
   crossed the boundary that should not have.
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
| **Executed** | steps 1 and 2 complete. Step 1: clean baselines at chatbot `ee9248d` (473 node ids) and core `d086c01` (385 node ids), a 745-identity union with 113 expected overlaps, branch `juena-core-cutover`. Step 2: chatbot `b5cd33a`+`21210ac` against core `78fc3dd`+`347d5a5` — 44 modules deleted, integration suite green at its baseline 16, prompts byte-identical, `chats.agent_id` backfilled over 209 live rows, and three defects fixed in core. **Step 4 is blocked on step 6's build context** (finding 8); step 3 is next |
| **Decided** | the test split (22 / 21 / 3); `Config` stays in the app; generic sandbox Python moves to optional core while deployment assets stay; the two-baseline identity diff is the instrument; prompts must not change; `JuenaAgentClient` subclasses core; `agent_id` is backfilled to `'juena'` |
| **Open** | nothing — this plan answers questions rather than asking them |
| **Revised** | 2026-09-16 after the step-1 review — collector commands now preserve collection failures and do not dirty the plan tree; both repository baselines are recorded; reconciliation compares the 745-identity pre-cutover union and rejects duplicates; the test split is corrected to 22 / 21 / 3; stale local-only and dirty-tree statements are corrected. Earlier review and 01/CP7 amendments remain in force |
