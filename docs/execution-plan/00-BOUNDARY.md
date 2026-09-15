# Plan 00 — The boundary

> **Goal:** decide, module by module, what `juena-core` is. **No code.** This document
> is the thing plan 01 executes and plan 02 checks against.
>
> **Depends on:** nothing. **Unblocks:** 01, 02, 03.

## Before you start

You need read access to
`/Users/az-ihsan/Documents/kerjaan-ihsan/post-doc/JueNA_knowledge_base/juena-chatbot`.
Nothing is written in this plan. The output is a reviewed decision table — this file,
amended if review disagrees with it.

Read `README.md` in this directory first, particularly *What every plan holds to*.

## Why this exists

`juena-chatbot` is one repository containing two things: an application about neutron
research software, and the infrastructure any LangGraph chatbot of this shape needs.
Vitess AI Agent v2 wants the second without the first.

The whole risk of this project is drawing that line in the wrong place. Drawn too
generously, core acquires Podman, SAML and a repository index, and a colleague who
installs it to build a third agent gets all of them. Drawn too meanly, v2
re-implements streaming and gets it subtly different, and the two apps drift.

So the line is drawn once, here, deliberately — and then plan 02 tests it by making
juena-chatbot live behind it.

---

## The three rules everything follows from

**1. `juena_core` must never import `juena` or `vitess_ai`.**
The dependency runs one way. This is the mistake that is expensive to undo — once two
applications share a core that reaches back into one of them, neither can move. Made
executable in 01/CP0, and run from both applications' test commands.

**2. The base install is the server and the agent kit.**
Podman, SAML, Chroma, pgvector, Streamlit and `fastmcp` are each somebody's optional
extra or somebody's application.

**3. Core owns the vocabulary and the wiring; the app owns the domain.**
Core knows what a specialist report is and what order a middleware stack goes in. It
does not know what a neutron guide is, and it does not know what a repository is.

---

## The disposition

Paths are relative to `src/juena/` on the left, `src/juena_core/` on the right.

### Moves whole

These have no application-specific content.

| From | To | Note |
|---|---|---|
| `schema/server.py` | `schema/server.py` | All 138 lines read. Nothing names JüNA; nothing names a domain. **Moves, but not unchanged:** `CreateChatInput` gains a required `agent_id` in 01/CP1; persistence and authorization enforce it in 01/CP3 — see decision 13 |
| `schema/llm_models.py` | `schema/llm_models.py` | `Provider`, `BlabladorModelName`, `OpenAIModelName`. Arguably app policy — *which* models are offered — but both apps offer the same two providers against the same institute endpoint. One copy |
| `schema/agents.py` | `schema/agents.py` | `SpecialistReport`, `ResultArtifactEvidence`, `AskUserSchema`. The verified-report contract |
| `schema/upload_limits.py` | `schema/upload_limits.py` | Keeps its "deliberately dependency-free" property. One change, below |
| `agents/ask_user.py` | `agents/ask_user.py` | Needs `CLARIFICATION_KIND`, which moves — see the `schema/sandbox.py` split |
| `agents/loop_guard.py` | `agents/loop_guard.py` | **Do not rename `GUARD_FLAG`** — see *Two literals* below |
| `agents/findings.py` | `agents/findings.py` | The `/findings/` contract. Its docstring names four callers, two of which stay in the app; update the docstring |
| `agents/delegation.py` | `agents/delegation.py` | `SpecialistDelegate`, `with_delegation_boundary`, `crossing_files`. Verbatim |
| `agents/backends.py` | `agents/backends.py` | `JUENA_MEMORY_SYSTEM_PROMPT` → `MEMORY_SYSTEM_PROMPT`, and becomes an argument to `build_supervisor_middleware` with the current text as its default. `MemoryMiddleware`, not the backend, consumes it. It is not JüNA-specific prose — it is a prompt-injection guard |
| `agents/specialist_runtime.py` | `agents/specialist_runtime.py` | Execution stays a generic splice point; the optional implementation is in `juena_core.sandbox` — see decision 18 |
| `agents/specialist_outcome.py` | `agents/specialist_outcome.py` | Reads generic `execution_events`; both MCP and the optional sandbox may write them |
| `clients/client.py` | **split** — see decision 10 | It calls `/auth/me` (`:148`) and `/research` (`:512`), which core does not own |
| `core/llms_providers.py` | `llms_providers.py` | Already reads configuration through the lazy `get_config()` seam in `core/paths.py`, which tests already patch. Half the work is done |
| `core/log.py` | `log.py` | With the import-time `Config` import removed — see 01/CP1 |
| `server/errors.py`, `server/utils.py` | same | |
| `server/agent/registry.py` | `server/agent/registry.py` | Keeps `register_agent_factory(set_as_default=)`, but the shared registry starts with `DEFAULT_AGENT = None`, not the application literal `"juena"`. An application must register its default before serving |
| `server/agent/input_handler.py` | same | Including `raise ValueError("A trusted authenticated user_id is required")` — the identity requirement is already enforced here and stays |
| `server/agent/runtime_model_middleware.py` | same | `RuntimeModelContext` carries `provider`, `model`, `thread_id`, `user_id`. This is half the identity seam |
| `server/streaming/` | same | All three modules. `StreamPolicy` lets an application opt into `sandbox_status` without a sandbox import |
| `server/chat/` | same | All six modules. **Do not rename `DISPLAY_TEXT_KEY`** — see below |
| `server/database/connection.py`, `checkpointer.py`, `store.py` | same | |
| `server/api/endpoints.py` | `server/api/endpoints.py` | Amended by CP4: application resume, workspace and stream behavior are parameters, so the shared route contract moves whole |

### Moves as an optional feature

These modules move into `juena_core.sandbox` under the `[sandbox]` extra. They are not
imported by `juena_core` and their SQLAlchemy model is registered only when an
application explicitly enables the feature.

`approvals.py` · `backend.py` · `constants.py` · `evidence.py` · `executor.py` ·
`jobs.py` · `middleware.py` · `models.py` · `policy.py` · `runtime.py` · `worker.py` ·
`workspace.py`

### Two literals that must not be renamed

Both are stored in live data. Renaming either makes existing conversations behave
differently, silently.

- `GUARD_FLAG = "juena_repeated_tool_call"` in `agents/loop_guard.py` — a checkpointed
  value. Rename it and every existing thread's loop-guard state becomes invisible.
- `DISPLAY_TEXT_KEY = "juena_display_text"` in `server/chat/input_constants.py` —
  stored on real messages.

Change the comments to say why the name looks wrong. Keep the strings.

### Stays in juena-chatbot

`agents/juena_agent.py` · `agents/specialists/**` · `indexing/**` · `tools/**` ·
`sandbox/software.py` · `sandbox/repository-requirements.txt` · `research/**` ·
`server/auth/endpoints.py` (minus the dev provider) · `server/research/endpoints.py` ·
`app/sidebar.py` · `app/starters.py` · `app/streamlit_app.py` · the sandbox image,
Compose/systemd/launcher wiring and production policy · `./juena`

---

## The hard cases, decided

Eighteen decisions. Each names the alternative that was rejected, so the reasoning
survives.

### 1. `core/config.py` — how an application extends core configuration

**Decision: core defines a frozen `CoreSettings` dataclass that reads nothing, plus
`configure(settings)` and `settings()`. The application keeps its `Config` class
exactly as it is and calls `configure()` once at startup.**

The real coupling was measured rather than guessed. Only 19 modules read
`global_config`, and of the modules that move, the attributes needed are:

| Core module | Needs |
|---|---|
| `llms_providers.py` | `OPENAI_API_KEY`, `BLABLADOR_API_KEY`, `BLABLADOR_BASE_URL`, `MAX_TOKENS`, `TIMEOUT_SECONDS`, `MAX_RETRIES`, `DEFAULT_PROVIDER`, `DEFAULT_MODEL`, `OPENAI_AVAILABLE_MODELS`, `BLABLADOR_AVAILABLE_MODELS`, `OPENAI_DEFAULT_MODEL`, `BLABLADOR_DEFAULT_MODEL` |
| `server/agent/registry.py` | `DEFAULT_PROVIDER`, `DEFAULT_MODEL` |
| `server/api/endpoints.py`, `server/chat/repository.py` | `STREAM_TOOL_PAYLOADS` |
| `server/database/connection.py` | `DATABASE_URL`, `DATABASE_POOL_MAX_SIZE` |
| `server/identity.py` | `SESSION_TTL_HOURS`, `SESSION_COOKIE_SECURE` |
| `agents/specialist_runtime.py` | `FALLBACK_PROVIDER`, and `SANDBOX_EXECUTION_TIMEOUT_SECONDS` renamed `EXECUTE_TIMEOUT_SECONDS` |
| `artifacts.py` | `ARTIFACT_ROOT`, `AUDIT_FILE` |
| `log.py` | `LOG_LEVEL`, `LOG_DIR` |

That is 23 fields, plus `BIND_HOST` and `API_PUBLISHED` added by decision 17 below.
The list is derivable with
`grep -rn "global_config\.\|get_config()" src/juena/`, filtered to the modules that
move. It is small enough to be one dataclass, and too large to thread as keyword
arguments through `build_chat_model` → `resilience_middleware` → `ArtifactStore` →
`AgentInputHandler`.

**Rejected: the juena-rag approach.** That package states "nothing in the package reads
the environment or a `.env` file" and passes plain keyword arguments. That is right for
a library with four entry points and wrong for a package whose whole job is to be a
server.

**The compromise:** core reads settings, but only through one accessor that raises
until the application calls `configure()`:

```python
settings()   # RuntimeError("juena_core.configure() has not been called")
```

This is the exact shape `get_checkpointer()`, `get_pool()` and `get_artifact_store()`
already use in this codebase. No new idea, no settings framework, and the failure mode
is a loud error at startup rather than a silent default.

Everything application-specific — `JUENA_RAG_URL`, `REPO_CACHE_DIR`, `CONTEXT7_*`,
`TAVILY_API_KEY`, every `SANDBOX_*` and every `SAML_*` — stays on the application's own
`Config`.

**So an application extends core configuration by *not* extending it.** It keeps its
own class and hands core a `CoreSettings`. No subclassing, no registry, no merge.

**Related, and easy to miss:** `core/paths.py::repo_root()` walks up from `__file__`
looking for a `pyproject.toml`. From inside an installed package that finds the wrong
directory or nothing at all. **Core takes `LOG_DIR`, `ARTIFACT_ROOT` and every other
root from `CoreSettings`, never by walking up.** The application still computes them
however it likes.

### 2. `schema/server.py` — is anything in it application-specific?

**Decision: no. It moves whole.**

All 138 lines were read. The only import is `Provider`, which also moves. `ChatMessage`
is the shared transcript type on both ends of the wire — the UI parses server-sent
events back into it — so it must live with the streaming code that emits it.

### 3. `agents/juena_agent.py` — where the line falls

The supervisor *function* is application-specific: it names two specialists, calls
`build_search_index()`, and loads Context7 and Tavily. The *middleware stack order* is
not — it is core machinery, and the comments in the file already say so ("No
`TodoListMiddleware`: a todo list adds no evidence and is the tool models most readily
loop on").

**Decision: core gets `build_supervisor_middleware(...)`, returning the canonical
stack, with exactly one named insertion point.**

Reading the real stack, the application-specific entries are precisely two —
`ArtifactMessageMiddleware` (sandbox) and `ResearchDeliveryMiddleware` (research) — and
both sit between `PatchToolCallsMiddleware()` and `RuntimeModelMiddleware()`. So:

```python
build_supervisor_middleware(
    *, backend, summarizer_model, fallback_models, subagents,
    task_description=SPECIALIST_TASK_DESCRIPTION,
    extra=(),            # spliced after PatchToolCallsMiddleware,
                         # before RuntimeModelMiddleware
    memory_system_prompt=MEMORY_SYSTEM_PROMPT,
    model_call_limit=..., tool_call_limit=...,
) -> list
```

One seam, named, with the reason in the docstring. **This is not a hook system:**
`extra` is a list, spliced at one documented index, and everything else is fixed.

`SUPERVISOR_TASK_DESCRIPTION` moves to core as `SPECIALIST_TASK_DESCRIPTION` — it
describes `<specialist_report>` and `<verified_by_server>`, which are core concepts —
and stays overridable.

**The instrument that makes this safe, and it does not exist today:** a core test that
asserts the returned list's class names *in order*. A reorder then fails a test instead
of silently changing model behaviour. This is the main thing the refactor buys.

`build_specialist_middleware`, `build_specialist_backend`, `resilience_middleware`,
`build_fallback_models` and `load_markdown` move unchanged — they are already functions
with no application content.

### 4. `indexing/` — the seam

**Decision: there is no seam to build.**

`build_search_index()` is called from `create_juena_agent`, which is application code
that stays in the application. `survey_repositories`, `RepoManager` and
`RagVectorIndex` are imported by exactly two modules, both application-specific.
`grep -rn "from juena.indexing" src/` returns five hits, all in `agents/juena_agent.py`
and `tools/repo_search.py`. **Nothing that moves to core touches `indexing`.**

What core owes v2 is not a retrieval abstraction but a *shape to copy*: the survey
pattern in `indexing/bootstrap.py:61-91` — check every source once at factory time,
keep the tools bound when one is broken, and report the outage per request rather than
deleting a capability for the life of the cached graph. v2's Chroma retrieval and v2's
MCP connection both want exactly that, and it is about thirty lines. **Copy it; do not
abstract it.**

The rule this creates: **`juena-core` must not depend on `juena-rag`.** Enforced by the
same check as the import-direction rule.

### 5. `sandbox/` — original boundary, superseded by decision 18

**Decision: `sandbox/` stays in juena-chatbot. Three things come out of it first.**

> **Superseded after CP6 by decision 18.** The reasoning here explains why VITESS must
> not acquire sandbox runtime or deployment behavior, but it does not require the
> reusable implementation to remain duplicated inside juena-chatbot. The generic
> implementation now moves as an optional, independently configured core feature.

It is about 3,000 lines of Podman, a host worker with a systemd unit, a `sandbox_jobs`
table with two partial unique indexes, and a `FOR UPDATE SKIP LOCKED` queue. v2 wants
none of it. But three pieces inside are not about Podman:

| Lift | To | Why |
|---|---|---|
| `sandbox/artifacts.py` (443 lines) | `juena_core/artifacts.py` | `ArtifactStore` is a per-user file store with per-turn budgets, PNG validation and an audit log. That is *delivery*, not sandboxing — and **v2 needs it for monitor1D/2D plots.** Its only sandbox import is six constants from `sandbox/constants.py`, which come with it |
| `sandbox/runtime.py::_context_value` (5 lines) | `juena_core/runtime_context.py` | Reads `user_id`/`thread_id` off a runtime whose context may be a dict or a dataclass. Used by three modules, two of which move |
| the generic half of `schema/sandbox.py` | `juena_core/schema/interrupts.py` | Split, below |

`SandboxExecutionEvidence` becomes **`ExecutionEvidence`** in core. Its execution facts
remain unchanged (`attempted`, `succeeded`, `status`, `exit_code`), and it gains the
`graph_run_id` required by decision 16 to scope checkpointed history. Nothing in it is
Podman-shaped.

`SpecialistOutcomeMiddleware` then reads a generic state channel, `execution_events`.
juena-chatbot's sandbox backend writes it; v2's MCP tool wrapper writes it when
`run_simulation` returns a success flag and an exit code.

**No protocol class, no injected reader, no registry — one channel name, two writers.**
That is the whole seam between the verified-report machinery and execution, and it is
why Finding 5 (two imports) matters.

The `schema/sandbox.py` split:

| Stays in sandbox | Moves to core |
|---|---|
| `EXECUTE_APPROVAL_KIND`, `ApprovalResumeInput` | `CLARIFICATION_KIND`, `ClarificationResumeInput`, `_ResumeBase`, `ArtifactRef`, `ExecutionEvidence` |

> **Corrected after review.** An earlier draft moved the `ResumeInput` *union* into core
> while leaving `ApprovalResumeInput` in the application. That is impossible — the union
> is `Annotated[ApprovalResumeInput | ClarificationResumeInput, Field(discriminator="kind")]`,
> so moving it drags the approval model across with it.
>
> **Decision: core defines the base and the clarification arm; the application composes
> its own union.** Core exports `_ResumeBase` (as `ResumeBase`) and
> `ClarificationResumeInput`. Each application declares its own discriminated union from
> the arms it actually has:
>
> ```python
> # juena-chatbot
> ResumeInput = Annotated[ApprovalResumeInput | ClarificationResumeInput,
>                         Field(discriminator="kind")]
> # vitess v2 — no sandbox approval, so one arm
> ResumeInput = ClarificationResumeInput
> ```
>
> Core's resume endpoint helper takes the union as a parameter rather than importing it.
> This is also more honest: v2 has no execute-approval interrupt at all, so a union
> offering one would describe a pause that can never happen.

`server/streaming/processor.py` currently branches on
`interrupt_kind(...) == EXECUTE_APPROVAL_KIND` (line 43). In core that becomes a small
dictionary the application extends at startup:
`register_interrupt_event(kind, builder)`. Core emits `clarification_required` for the
kind it knows; juena-chatbot registers its approval kind in `service.py`. One
dictionary, one call.

> **Amended by 01/CP4: `register_interrupt_kind(kind, *, event, resume)`,** in a new
> `server/interrupts.py`. Still one dictionary and one call per application, but each
> kind registers **two** builders. An event builder alone lets core show a card it cannot
> resume: the user answers, `/resume` finds no way to turn the reply into a `Command`,
> and the run stays paused with nothing naming the cause. The two halves have one owner
> and one lifetime.
>
> The event builder also **is** the classifier — it returns `None` for an interrupt that
> is not its kind — so `interrupt_kind()` needs no separate registration and a kind
> cannot be recognised but unrenderable.
>
> The registry cannot live in `service.py` as sketched: `processor.py` needs it, and
> `service.py` imports the routers that import `processor`. `service.py` re-exports it,
> so the documented call site is unchanged.

### 6. `research/` — stays, but name what will reopen it

**Decision: stays in juena-chatbot. Do not extract it now.**

It is not on the inherited list; it owns a database table, a per-user concurrency limit
taken under a row lock, an orphan sweep in the application lifespan, and a conflict
namespace under `/findings/_conflicts/`. Extracting it would put a table and a runner
loop in core that v2 never writes to.

**But name the thing that will reopen it.** `advanced_mode` runs batch parameter
sweeps. A sweep is long by definition, and today it runs inside a tool call tied to the
HTTP connection — which is precisely the problem `research/` exists to solve. The first
time a user closes the browser mid-sweep and loses forty minutes of simulation,
`juena-core[research]` becomes the right answer. Recorded in *Still open*; not built
now.

What core *does* keep from the pattern, because both applications need it:
`findings.py`, and the `unattended` flag on `build_specialist_middleware` — which
removes `ask_user` and the execution backend **together**. Dropping one without the
other is how you end up running commands unapproved.

### 7. `app/` Streamlit — how much is a reusable shell

The dependency surface was measured. `app/*.py` imports exactly six `juena` modules:
`clients.client`, `core.config`, `core.llms_providers`, `schema.llm_models`,
`schema.server`, `schema.upload_limits`. All six are core, so the library side needs no
work.

For the UI modules themselves the split is by *how much the two applications' pages
actually differ*, and they differ a lot. juena's `sidebar.py` is 342 lines of chat list
plus model picker. Vitess's is **596 lines of per-module file upload** driven by
`upload_schema_sidebar` from the module catalog. That is not a variant of the same page.

It shrinks in 03/CP2 and 03/CP6 — the three `path_only` rows are deleted, because they
upload nothing and duplicate an output filename the schemas already declare — but a
per-module **manifest** is domain UI either way, and stays v2's.

**Decision: move only what is mechanically identical. No hooks.**

| Module | Disposition |
|---|---|
| `app/math_rendering.py` (354) | → `juena_core/ui/math_rendering.py`. Pure text transformation |
| `app/chat_storage.py` (101) | → `juena_core/ui/chat_storage.py`. A thin client over `/chats`, which core owns; its UI `Chat` gains the persisted `agent_id` |
| `app/client_setup.py` (25) | → `juena_core/ui/client_setup.py`, except `JUENA_AGENT_ID = "juena"` stays in the application and core requires `agent_id` explicitly |
| `app/chat_interface.py` (755) | **split.** `process_stream_chunk`, `is_status_chunk`, `is_approval_chunk`, `is_interrupt_chunk`, `is_artifact_chunk`, `apply_status_chunk`, `_stream_and_display_chunks`, `stream_and_display_response`, `stream_and_display_resume`, `_render_approval_card`, `_render_question_card`, `render_pending_interrupt` → `juena_core/ui/streaming.py`. **The server-sent-event contract is core's; the page is the app's.** `render_chat_interface()` and `render_starter_topics()` stay |
| `app/ui_components.py` (423) | **split.** `sanitize_assistant_content`, `render_content`, `render_message`, `render_streaming_token`, `render_artifacts`, `finalize_streaming_message`, `render_attachment_chips`, `should_collapse_tool_payload` → core. `logo_data_uri`, `render_header_with_logo` → app |
| `app/sidebar.py`, `app/starters.py`, `app/streamlit_app.py` | stay |

About 900 of 2,183 lines shared, with **zero hook system**. *What would change this:* if
v2's sidebar converges on juena's, promote it later. Promoting a module is cheap;
removing a hook system after two applications depend on it is not.

Core ships this behind a `[ui]` optional extra, so a headless deployment installs no
Streamlit.

**Two application literals do not cross this boundary.** The source registry's initial
`DEFAULT_AGENT = "juena"` becomes `None` in core and is set only by an application's
explicit `register_agent_factory(..., set_as_default=True)` call. Likewise,
`client_setup.py` does not provide `JUENA_AGENT_ID` or default its `agent_id` argument.
Those defaults belong to each application's thin wiring module. Starting without a
registered default is an error, not an implicit choice of JüNA.

**One change to `upload_limits.py`:** it keeps its "deliberately dependency-free"
property and its comment about the UI being a courtesy and the server being the
boundary, but the validator's extension policy becomes injectable. Core retains an
immutable `DEFAULT_TEXT_READABLE_FILE_TYPES` tuple for the shared UI and derives
`DEFAULT_SUFFIXES` from it; v2 supplies its own suffix set containing `.dat`, `.inf`,
`.nxs` and `.h5` rather than mutating core's defaults:

```python
validate_attachments(attachments, *, allowed_suffixes=DEFAULT_SUFFIXES,
                     max_bytes=..., max_files=...)
```

### 8. The `./juena` launcher

**Decision: copied, not shared or templated.**

It is `bash` with `set -euo pipefail` and no dependency mechanism. Sourcing a shared
library out of a sibling repository would make `./vitess help` fail when juena-core is
not checked out beside it — and "the sibling repository may be missing" is a case
`./juena` already handles deliberately for juena-rag (`cmd_up` does not fail when the
sibling is absent). The help generator is six lines of `grep | sed | awk`. There is
nothing to share but the *conventions*, and conventions travel by copying.

`./vitess` is `./juena` with:

- **kept unchanged:** the symlink-walking `SCRIPT_PATH` resolution and `cd "$REPO_ROOT"`
  (so the script works from anywhere and can be symlinked onto `PATH`); the
  dev/production Compose split, where the dev overlay must be merged explicitly and can
  therefore never leak into production; `ensure_test_database` (drop and recreate
  `<db>_test`, with its one-run-at-a-time warning); the `## ` comment convention that
  generates the help text, so a new command is documented by defining it;
  `cmd_install`, `cmd_clean`, `cmd_test`, `cmd_test_integration`, `cmd_test_all`,
  `cmd_health`, `cmd_prod_config`, `cmd_prod_up`.
- **deleted:** `rag-up` / `rag-down` / `rag-logs` (v2's Chroma runs in-process),
  `bootstrap`, `sp-metadata`, every `sandbox-*`, and **the whole host-process
  mechanism** — no pid files, no `.sandbox/` runtime directory, no `wait_for_*` loops.
- **not added:** `mcp-up` / `mcp-down` / `mcp-logs`.

> **Corrected after review.** An earlier draft added `mcp-up` by copying the `rag-up`
> body, on the reasoning that juena-rag is also a service beside the app. **That was
> wrong**, and decision 11 explains why: juena-rag talks HTTP only, while the MCP server
> must *share files* with the app. A host process cannot see the app container's named
> volume.
>
> So the MCP server is an ordinary Compose service, and `docker compose up` starts it
> along with the app and Postgres. `./vitess up`, `./vitess down`, `./vitess logs` and
> `./vitess ps` already cover its whole lifecycle — which is simpler than what the draft
> proposed, not more complex.

### 9. `server/auth/` — the identity seam

**Decision: four parts.**

**Part 1 — the principal.** Core defines, in `juena_core/server/identity.py`:

```python
@dataclass(frozen=True, slots=True)
class Principal:
    id: UUID
    subject: str          # opaque; a SAML NameID in juena-chatbot,
                          # a fixed development id in v2
    issuer: str           # opaque; the identity provider's entity id
    email: str | None
    display_name: str | None
```

This is `AuthenticatedUser` with `saml_subject` renamed. Core's code touches only
`.id`, and `.id` is what reaches `RuntimeModelContext.user_id` and every `user_id`
foreign key.

**Part 2 — the dependency.** Core's routers become factory functions —
`build_chat_router(principal)`, `build_api_router(principal)` — and
`juena_core.server.create_app(*, principal, extra_routers=(), extra_lifespans=())`
assembles them. juena-chatbot's `service.py` then shrinks to roughly twenty lines: it
imports its agent module for the registration side effect, imports its own SQLAlchemy
models for *their* side effect, and calls `create_app(...)`.

Converting about twenty route decorators to live inside factory functions is the noisy
part. **If it proves too noisy,** the cheaper fallback is FastAPI's own
`app.dependency_overrides[core_principal] = app_principal` — one line per application,
a public and stable FastAPI feature, keyed on the callable object so both sides must
import the same one. Prefer the factory: it makes the dependency visible in the
signature rather than in a dictionary mutation at startup.

**Part 3 — the local principal, which is v2's whole identity story for this phase.**

v2 is local and single-user, so it needs exactly one user. Core ships
`juena_core.server.identity.local_principal(...)` — a dependency returning a `Principal`
built from a **stable, configured UUID**, so the `users` row, the thread ownership and
the memory namespace are all real and all consistent across restarts.

Three constraints that make this safe rather than sloppy — see decision 17 for the
topology they assume:

- **It is injected through the same dependency a real provider would implement.** No
  magic UUID sprinkled through endpoint code. Swapping in SAML later is a different
  callable passed to `create_app`, not a rewrite of the routes.
- **Its guard runs at startup, not per request.** `create_app` refuses to construct when
  `local_principal` is paired with a published API. A *dependency* cannot do this — it
  runs on a request, so it would fail the first call rather than refuse to boot. Same
  intent as juena-chatbot's refusal to run `AUTH_DEV_BYPASS` outside development
  (`core/config.py:196-200`): an identity provider that authenticates nobody must never
  face a network.
- **It upserts its `users` row at startup.** `Chat.user_id` is a foreign key to
  `users.id`. A principal that only claims a UUID produces a foreign-key violation on the
  first conversation — a real provider creates the row as a side effect of logging in,
  and this one has no login to hang it on.

juena-chatbot keeps its SAML service provider and its own `AUTH_DEV_BYPASS` unchanged;
neither moves. When v2 eventually wants an institute login, `juena.server.auth.saml` is
the code to **copy**, not to share — service-provider metadata, certificates and
`xmlsec1` are deployment-shaped.

**Part 4 — the database, and why nothing is renamed on disk.** There is no Alembic;
`database_lifespan` calls `Base.metadata.create_all`. **`create_all` never renames a
column**, so renaming `users.saml_subject` would silently leave the old column sitting
beside a new empty one.

**Decision: rename the Python attributes, keep the column names.** SQLAlchemy does this
with a positional name:

```python
subject: Mapped[str] = mapped_column("saml_subject", Text, nullable=False)
```

Zero migration, honest naming, and juena-chatbot's live rows keep working. v2 starts
empty and does not care either way.

**Table ownership.** Core's `juena_core/server/database/models.py` holds `Base`,
`utc_now`, `User`, `AuthSession` and `Chat`. juena-chatbot's own models module holds
`SamlLoginRequest`, `SandboxJob` and `ResearchJob`, importing `Base` from core.

**This creates a second side-effect-import trap, identical in shape to the agent
registry one:** a model class that is never imported is never created by `create_all`,
and the failure is a missing table at first write rather than an error at startup. The
mitigation is the same as the existing one — import it in `service.py` with a
`# noqa: F401` and a comment saying why — **plus** a test that asserts
`set(Base.metadata.tables)` equals the expected set.

### 10. Splitting the client and the API router

**Decision: extract the generic half; the application keeps and composes the rest.**

The earlier draft moved `clients/client.py` and `server/api/endpoints.py` whole, on the
grounds that they speak to core-owned endpoints. They do not speak *only* to those.

**`AgentClient`** calls `/auth/me` at line 148 and `/research` at line 512. Neither route
exists in core. Moving the class whole would make core own JüNA's authentication and
background-research surface, and v2 would inherit two methods that 404.

So:

- **Core gets `BaseAgentClient`** — transport, the server-sent-event parsing
  (`_parse_sse_data`), and the methods for routes core owns: `health`, `list_chats`,
  `create_chat`, `get_chat`, `update_chat`, `stream`, `resume_stream`, `get_artifact`,
  `get_pending_interrupt`, `delete_thread`.
- **juena-chatbot subclasses it** with `get_current_user()` and `list_research()`.
- **v2 subclasses it** with whatever VITESS adds, and with nothing it does not have.

**`server/api/endpoints.py`** has the same shape of problem — it imports sandbox,
approval and artifact behaviour. ~~**It does not move.** Core exports the pieces the
routes are built from (the stream generator, `_authorize_thread`, the resume dispatcher,
the artifact responder) and each application assembles its own router from them.~~ The
route *paths* stay identical, so the clients and the UI do not change.

> **Superseded by 01/CP4 — it does move, as `build_api_router(principal, …)`.** Two of
> the three imports that justified keeping it out stopped existing: artifacts became
> core's in 01/CP2, and the approval became an application-registered interrupt kind in
> 01/CP4. The third — materialising a thread's files where a process can open them — is a
> seam **both** applications need, because VITESS binaries read real files from disk
> exactly as a sandbox mount does, so it became the `ThreadWorkspace` parameter.
>
> Two copies of this router would mean two copies of the SSE event ordering, the
> ownership check, the artifact drain and the thread-event emission, which must not
> drift. And this decision's own concern — "a `BaseAgentClient` method with no matching
> route is a 404 nobody notices" — gets *worse* when core defines the client but not the
> routes: there is then no single place where the two can be compared. 01/CP4's
> acceptance check is that comparison.
>
> What the application still supplies: its identity dependency, its resume union, its
> `ThreadWorkspace`, its `StreamPolicy`, and the note closing a staged-input manifest.
> The client half of this decision is unchanged — core gets `BaseAgentClient`, not
> `AgentClient`.

**The test that keeps this honest** runs in both directions: core must not import an
application (01/CP0), **and** an application's router must expose the route set core's
client expects. A `BaseAgentClient` method with no matching route is a 404 nobody
notices until a user hits it.

### 11. The shared project-path contract

**Decision: one configured root, mounted at the same absolute path in both containers.**

This is the correction with the widest blast radius. The earlier draft ran the FastMCP
server as a host process, by analogy with `juena rag-up`. **The analogy does not hold.**
juena-rag communicates only over HTTP — a search request in, results out. VITESS
execution must *also share files*: the app accepts uploads and renders artifacts, while
the MCP service reads those uploads and writes simulation outputs. A host process cannot
see the app container's named Docker volume, and container-absolute paths like
`/data/projects/...` mean nothing outside the container.

The contract:

- **One root**, `/data/projects`, configured in one place.
- **The same named volume mounted at exactly that path** in both the app service and the
  MCP service.
- **Paths are resolved beneath a server-controlled directory**, never taken as given.
- **`thread_id`, `run_id` and filenames are validated as identifiers** — not as paths.
  A `run_id` is a UUID or it is rejected; it is never joined into a path unchecked.
- **No dependence on a host path that exists only outside Docker.**

Path containment matters even with one user, because the *model* generates tool inputs
and the container has mounted data and network access. `../` in a `run_id` is not a
multi-user problem.

### 12. Execution evidence and artifact transport

**Decision: MCP returns structured metadata; the API process turns it into
`execution_events` and artifacts.**

Two facts force this, both verified:

- `SpecialistOutcomeMiddleware` is to read an `execution_events` state channel — but the
  earlier draft never said what *writes* it for v2, while also dropping the old
  `tool_wrapper.py` that might have.
- `ArtifactStore` keeps `_pending_message` and `_pending_events` as ordinary Python
  dictionaries (`sandbox/artifacts.py:157-158`), drained by `drain_events()` at `:387`.
  **An MCP container cannot enqueue into the API process's memory.** A shared volume
  shares files, not objects.

The contract, in order:

1. **MCP writes simulation files** beneath the shared run directory (decision 11).
2. **MCP returns structured execution metadata** from the tool call — per-module name and
   status, exit code, start and end timestamps, a bounded stdout/stderr summary, and a
   descriptor for each produced file (path relative to the run root, kind, byte size).
3. **The API process translates that** into `execution_events` entries validated against
   `ExecutionEvidence`, and registers each produced file with `ArtifactStore`.
4. **Durable state lives in Postgres or is reconstructed from the shared volume**, never
   only in a pending queue.
5. **Plots have one canonical representation: a PNG file artifact**, delivered through
   the authenticated artifact endpoint exactly as juena's sandbox plots are. The existing
   Plotly-JSON tools get an adapter that renders and registers a PNG. Interactive Plotly
   is a separate, later, explicitly declared contract — not a second meaning for the same
   tool.

Step 3 is the only place a model-written value becomes evidence, and it validates rather
than trusts. That is what keeps `<verified_by_server>` worth its name across a process
boundary.

### 13. `agent_id` on a persisted conversation

**Decision: `Chat` gains an `agent_id` column, and it participates in lookup and resume.**

`server/database/models.py:101-112` carries `thread_id`, `user_id`, `title`, `summary`,
`created_at` and `updated_at` — and nothing recording which agent owns the conversation.
juena-chatbot has exactly one agent, so it never mattered. **v2 has two**, and core's
`/{agent_id}/stream` will happily resume any thread under any graph.

Without the column, switching mode in the UI can resume a `vitess` conversation inside
`advanced_mode` — same `thread_id`, different graph, a checkpoint whose state channels do
not match the state the graph expects.

So: store `agent_id` when a chat is created; include it in lookup and in resume
validation; make the UI's selected mode agree with the stored value rather than override
it. This is not authorization, which is deferred — it is identity, which is not.

`Chat` is a core model, so the column lands in core (01/CP3). juena-chatbot backfills it
with its single agent id; there is no Alembic, so the backfill is one `UPDATE` run once,
recorded in 02.

### 14. The typed module-result channel — an application concern

**Decision: v2 defines its own `module_results` state channel and its own delegation
boundary. Core gains nothing.**

The gap: `agents/delegation.py:47-58` carries exactly `messages` and `files` across the
boundary, in both directions. A specialist hands back a `SpecialistReport`, whose fields
are `status`, `finding`, `evidence`, `actions`, `limitations` — **prose written for a
supervisor to read**. Plan 03 drops both existing `ModuleResult` definitions.

So once a guide specialist has validated a `GuideParameters`, there is no typed route for
that object to reach the command builder. The only remaining route is the model retyping
the values into `run_simulation`'s arguments — which is precisely the model-authored path
03/CP1 exists to close. Closing it there and reopening it here would be pointless.

The shape:

```python
# vitess_ai/schema/module_result.py  — application, not core
class ModuleConfigurationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    module: str
    validated_at: datetime
    parameters: dict[str, Any]     # dumped from the module's own Pydantic model
    schema_version: str
```

- **The validation tool writes it**, returning `Command(update={"module_results": {...}})`
  — the same mechanism `tools/research.py` already uses to write state atomically with a
  tool result. The *tool* writes it, not the model, which is what makes it authoritative.
- **`module_results` is a state channel with a merge reducer** keyed by module name, so a
  re-validated module replaces its own entry and touches no other.
- **v2's delegation boundary is `with_delegation_boundary` plus one field.** Inbound stays
  `crossing_files`-shaped. Outbound returns `messages`, `findings_delta`, **and only the
  `module_results` entries this specialist validated** — a delta, not the whole channel,
  for the same reason `findings_delta` exists: a subagent must not rewrite results it
  merely inherited.
- **`run_simulation` reads it through `ToolRuntime`**, never from arguments. The model
  says *run the simulation*; it does not say *with these numbers*.

**Why this is not in core.** Core knows what a specialist report is because every
application has one. It does not know what a VITESS module is, and a generic
"structured results" channel would be a name with no meaning — the thing that makes this
work is that the payload is a `GuideParameters`, validated by the model that owns it.

### 15. Root-level execution evidence

**Decision: core gets a root execution middleware; v2 installs it in the supervisor
stack.**

`SpecialistOutcomeMiddleware` is installed at `specialist_runtime.py:249`, inside
`build_specialist_middleware`. **It runs inside specialists only.** The supervisor stack
in `juena_agent.py` does not contain it, and does not need to — in juena-chatbot every
command runs inside a specialist.

v2 is different: `run_simulation` is called by the **root supervisor**. So an earlier
draft's promise that the answer would carry a `<verified_by_server>` block was simply
untrue — nothing would have composed one.

What core provides:

- **`ExecutionEvidenceMiddleware`** — reads the `execution_events` channel and appends the
  server-authored block to the **root** response. It is the same composition logic
  `SpecialistOutcomeMiddleware` uses; factor the shared half out rather than writing it
  twice.
- **`ArtifactMessageMiddleware` moves into core** alongside it. It is already generic — it
  attaches artifact references to the outgoing message — and the boundary's earlier draft
  left it inside juena's sandbox package only because that is where it happened to live.

`execution_events` needs its schema declared with it: a `PrivateStateAttr` (so it never
crosses a delegation boundary as ordinary state) with a **list reducer**, because several
modules in one pipeline each append.

v2 splices both into `build_supervisor_middleware(extra=...)`. juena-chatbot keeps passing
`ArtifactMessageMiddleware` the same way it does today, so nothing changes for it.

### 16. `graph_run_id` and `simulation_run_id` are different things

**Decision: rename, and never reuse core's.**

`server/agent/input_handler.py:52` does `run_id = run_id or uuid4()` **per graph
invocation** and passes it as `RunnableConfig(run_id=...)`. One user turn, one id.

`advanced_mode` runs a parameter sweep — many simulations inside one turn. So core's
`run_id` cannot name an output directory, and an earlier draft that wrote outputs to
`outputs/<run_id>/` would have put every run of a sweep in one folder.

- **`graph_run_id`** — core's, one per invocation, unchanged.
- **`simulation_run_id`** — generated by trusted application or MCP code, one per VITESS
  execution. It names `outputs/<simulation_run_id>/`.

Core reads the first through the public `runtime.execution_info.run_id` API. A real CP2
graph run confirmed that `Runtime.config` intentionally omits top-level `run_id`; reaching
there would make every root evidence block disappear even though the caller supplied a
`RunnableConfig(run_id=...)`.

Neither is ever supplied by the model. The API injects `thread_id`; the façade reads it
through the public `request.runtime.execution_info.thread_id` API. Typed values such as
the principal remain in `request.runtime.context`. Ownership values are
**absent from the application facade's model-visible `args_schema`**. The raw MCP tools
are never bound to the model; 03/CP3a defines and tests that boundary.

### 17. Where the service binds, and what the local principal actually guards

**Decision: publish only Streamlit. The API binds loopback inside the container.**

An earlier draft said `local_principal` refuses a non-loopback `BIND_HOST`. That was
under-specified in two ways: `BIND_HOST` was not among the `CoreSettings` fields listed in
decision 1, and **a FastAPI dependency runs per request, not at startup** — so the "guard"
would have failed the first request rather than refusing to boot.

The topology, stated once:

- **Streamlit binds `0.0.0.0` inside the container** (it must, to be reachable through
  Docker's port mapping) and **Compose publishes it as `127.0.0.1:<port>:8501`**.
- **The API binds `127.0.0.1` inside the container** and is **not published at all**.
  Streamlit reaches it over container loopback; nothing outside can.
- **MCP and Postgres are not published**, only on the internal network.

So the network restriction lives in the Compose file, where it can be read, and
`CoreSettings` gains `BIND_HOST` and `API_PUBLISHED: bool` for the two things code must
still assert.

**The guard is a startup check, not a dependency.** `create_app` verifies at construction
that `local_principal` is not paired with a published API, and raises. Test it two ways:
`docker compose config` shows both host mappings bound to `127.0.0.1`, and a negative
check confirms the API and MCP ports are unreachable from the host.

**One thing the fixed principal must do that a real provider does for free:** upsert its
`users` row at startup. `Chat.user_id` is a foreign key to `users.id`; a principal that
only *claims* a UUID produces a foreign-key violation on the first conversation.

### 18. Sandbox implementation — optional core feature, application-owned deployment

**Decision: the reusable execution machinery moves to `juena_core.sandbox`, behind a
`[sandbox]` extra and a separate `SandboxRuntimeSettings`. VITESS neither installs nor
configures it.**

The original decision 5 correctly rejected making Podman part of every core consumer,
but it conflated package ownership with activation. Optional packaging gives
juena-chatbot one implementation to consume later without changing VITESS at all:

- importing `juena_core` does not import the Podman client;
- the `sandbox_jobs` model joins core metadata only after
  `configure_sandbox(... enabled=True)` and therefore is absent from VITESS;
- no sandbox field is added to `CoreSettings`; applications that opt in construct the
  separate immutable settings object from their own environment policy;
- the API and host worker share only Postgres and the workspace root. Only the worker
  receives the rootless Podman socket;
- table/index names, HMAC workspace identities, advisory-lock identifiers, Podman
  labels and managed-container names stay unchanged so the chatbot cutover is compatible
  with existing rows and cleanup behavior.

Core owns the generic queue, workspace confinement, Podman executor, worker, Deep Agents
backend, execution middleware/evidence, approval/resume contract and server wiring
helpers. juena-chatbot still owns `sandbox/software.py`, its repository-software
manifest, sandbox image, systemd/Compose/launcher integration, environment parsing and
production validation. Those assets state which scientific software is installed and
how this deployment is operated; a library cannot choose either honestly.

The security invariant is operational as well as structural: generated commands require
the paired human-in-the-loop policy, containers have no network, a read-only root,
dropped capabilities, resource limits and tenant-confined mounts, and the application
container never receives the Podman socket. A later deployment must validate rootless
Podman and its chosen OCI runtime on its actual Linux host; unit tests cannot certify
that host boundary.

---

## Verification

This plan produces no code, so it is verified by review rather than by a command.
It is done when:

1. Someone other than the author has read the disposition table and the eighteen
   decisions and disagreed with none of them, or the disagreements are written into this
   file. *(Done once — see [REVIEW.md](REVIEW.md); its findings are incorporated.)*
2. Every module in `src/juena/` appears exactly once — in *Moves whole*, in *Moves as an
   optional feature*, in *Stays*, or in one of the eighteen decisions. The check:
   `find src/juena -name '*.py' | wc -l` against the count of entries here.
3. The two literals that must not be renamed are understood by whoever executes 01/CP2
   and 01/CP4.
4. **Every cross-process interaction has a declared producer, consumer and persistence
   owner.** There are four: uploads (app writes, MCP reads, volume owns), VITESS execution
   results (MCP produces, app consumes, Postgres owns), artifacts (MCP produces files,
   app registers, volume plus `ArtifactStore` own), and optional sandbox jobs (API
   produces, host worker consumes, Postgres plus the workspace root own). If a fifth appears during
   implementation, it comes back here before it is built.

## Status

| | |
|---|---|
| **Depends on** | nothing |
| **Unblocks** | 01, 02, 03 |
| **Decided** | the disposition table; eighteen decisions; the three rules; the local single-user target; sandbox execution is opt-in core while its deployment remains application-owned |
| **Open** | whether v2's sidebar ever converges on juena's (would promote `sidebar.py` into `juena_core.ui`); whether a run manifest on the volume is needed alongside the returned metadata (decision 12) |
| **Revised** | 2026-09-15 after [REVIEW.md](REVIEW.md), then amended by 01/CP7 — decisions 10–13 added, the `ResumeInput` union corrected, identity narrowed to a local principal, and optional sandbox ownership settled in decision 18 |
