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
passed, its tree clean, and its core commit SHA recorded. There is no tag or remote in
this local-only phase.

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

> **The tree is not clean right now.** `env.example` and `juena` carry the juena-rag
> cutover work. **Do not revert it** — commit or finish it first. A baseline taken over
> uncommitted changes is not a baseline, because step 3 cannot tell a test you added last
> week from one this refactor lost.

```bash
cd juena-chatbot
git status --short          # must be clean
./juena test-all

# and the thing counts cannot give you -- see step 3 for `normalise`:
normalise() { grep '::' | sed 's|^.*/||' | sort; }
uv run --extra dev pytest --collect-only -q tests/ | normalise > /tmp/baseline-nodeids.txt
wc -l /tmp/baseline-nodeids.txt
```

**Record the collected node ids, not just the totals.** A pass count is a single number,
and one test removed plus one test added leaves it unchanged. The node id list makes a
swap visible as a diff. Keep `/tmp/baseline-nodeids.txt` somewhere durable — step 3
compares against it.

If the tree is not clean, stop and find out why before touching anything.

---

## Step 2 — delete and re-point, module by module

For each module core now owns: delete it from `src/juena/` and replace every import of
it with the `juena_core` equivalent.

Do this **in plan 01's checkpoint order** — configuration → agent kit → persistence →
server → client and UI — running `./juena test` after each group. The suite will go red
in predictable ways, and each red is one search-and-replace.

Add the dependency first:

```toml
dependencies = ["juena-core[ui,mcp]"]

[tool.uv.sources]
juena-core = { path = "../juena-core" }
```

**The lock pins the dependency set; it does not pin core's source** — a path dependency installs whatever is in the sibling directory, and cannot be hash-checked. Core's revision is pinned by discipline instead: a clean core tree, and its commit SHA recorded in the build record (D7, 01/CP6). juena-chatbot's
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

**Do not move `Config` into core.** Its `validate_required()` knows about SAML, the
sandbox and production HTTPS, none of which is core's business. This is the decision
from 00: *an application extends core configuration by not extending it.*

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

---

## Step 3 — split the tests, then reconcile

**A test that exercises a core module moves to juena-core. A test that exercises the
wiring stays here.**

The 46 modules, mapped by what they import:

### Moves to juena-core — 12

`test_agent_backends` · `test_agent_input_handler` · `test_ask_user` ·
`test_chat_storage` · `test_client_setup` · `test_code_chat_inputs` ·
`test_llm_models` · `test_loop_guard` · `test_math_rendering` ·
`test_runtime_model_middleware` · `test_server_utils` · `test_streaming_handlers`

### Stays — 28

`test_agent_prompts` · `test_agent_resources` · `test_api_endpoints_files` ·
`test_bootstrap` · `test_chat_interface` · `test_config_paths` · `test_context7_tools` ·
`test_findings_lifecycle` · `test_juena_agent_runtime` · `test_main` ·
`test_postgres_integration` · `test_rag_index` · `test_repo_config` ·
`test_repo_manager` · `test_repo_search_tools` · `test_research` · `test_saml_auth` ·
`test_sandbox_approvals` · `test_sandbox_executor` · `test_sandbox_middleware` ·
`test_sandbox_pipeline_integration` · `test_sandbox_worker` · `test_sandbox_workspace` ·
`test_sidebar` · `test_specialists` · `test_starters` · `test_supervisor_routing` ·
`test_tavily_tools`

### Splits — 6

| Module | Core half | App half |
|---|---|---|
| `test_agent_client` | `BaseAgentClient` transport, SSE parsing, core routes | `get_current_user` (`/auth/me`), `list_research` (`/research`) |
| `test_specialist_outcome` | report composition, `execution_events` parsing | the sandbox-written evidence |
| `test_artifact_message_middleware` | artifact attachment | sandbox artifact production |
| `test_sandbox_artifacts` | `ArtifactStore` budgets, PNG validation, audit | Podman workspace paths |
| `test_sandbox_backend` | backend protocol conformance | Podman execution |
| `test_ui_components` | message, token and artifact rendering | logo and header |

`test_agent_client` moved from the "moves whole" column once the client itself split
(00, decision 10). **12 move, 28 stay, 6 split.**

**`test_postgres_integration.py` does not split.** It imports from
`juena.server.{api,auth,chat,database}`, `juena.research`, `juena.sandbox` and
`juena.agents.findings` all at once — which is exactly what makes it worth keeping
whole. It is the only test that exercises the wiring against a real database.

### The reconciliation, which is the instrument

Collect node ids from both repositories, normalise the paths, and **diff against the
baseline** — do not compare totals:

Node ids look like `tests/test_loop_guard.py::test_blocks_repeat`. A test that moves
repositories keeps its name and changes its path, so **compare on the part after
`::`** — otherwise every moved test reads as one removal plus one addition and the diff
is useless.

```bash
# strip pytest's trailing summary lines, keep only real node ids, drop the file path
normalise() { grep '::' | sed 's|^.*/||' | sort; }

( cd juena-core    && uv run pytest --collect-only -q tests/ ) | normalise > /tmp/after-core.txt
( cd juena-chatbot && uv run --extra dev pytest --collect-only -q tests/ ) | normalise > /tmp/after-app.txt
cat /tmp/after-core.txt /tmp/after-app.txt | sort > /tmp/after-nodeids.txt

diff /tmp/baseline-nodeids.txt /tmp/after-nodeids.txt
```

`grep '::'` drops the `N tests collected in 1.23s` footer, which would otherwise appear
as a spurious difference every run. Apply the **same** `normalise` when recording the
baseline in step 1.

Every line in that diff is explained in writing, as one of: **moved** (same test, new
file path), **added** (deliberately, named), or **removed** (deliberately, with the
reason). Nothing else is acceptable.

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

---

## What could go wrong

| Risk | Guard |
|---|---|
| **A test disappears in the split and pytest reports green.** The likeliest failure | the node-id diff in step 3 — a count comparison would miss a removal paired with an addition |
| The suite tests in-repo modules, not the installed core | `juena_core.__file__` resolves into the venv |
| `agent_id` backfill forgotten; `create_all` cannot add a not-null column to a live table | step 2's `ALTER`, run once, after a dump |
| `AUTH_DEV_BYPASS=true` hides a broken SAML path | step 5 |
| **Two SQLAlchemy `Base` objects.** If the app defines its own `DeclarativeBase` instead of importing core's, `create_all` builds core's tables from one metadata and the app's from another, and the `user_id` foreign keys fail at create time with an unresolved-table error | the `set(Base.metadata.tables)` test from 01/CP4 |
| A renamed literal (`juena_repeated_tool_call`, `juena_display_text`) breaks existing threads invisibly | step 4's reopen-an-old-thread check |
| Middleware order changes during the re-point | the class-name-order test from 01/CP2 |
| The chatbot is built from an uncommitted or unrecorded core revision | require a clean core tree and record its commit SHA plus the resulting image digest (01/CP6) |

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
| **Decided** | the test split (12 / 28 / 6); `Config` stays in the app; the node-id diff is the instrument; prompts must not change; `JuenaAgentClient` subclasses core; `agent_id` is backfilled to `'juena'` |
| **Open** | nothing — this plan answers questions rather than asking them |
| **Revised** | 2026-09-15 after [REVIEW.md](REVIEW.md) — node ids replace pass counts, installed-core check added, client subclass and `agent_id` backfill added |
