# Re-developing Vitess AI Agent — execution plans

Four plans that turn an agreed architecture into an order of work — 00, 01, 02, 03.
Each is written to be **picked up cold**, so each states its own preconditions, its
checkpoints, and a command that passes or fails. Read this file first; after that a
plan can be handed to someone who has read nothing else.

> **Revision 6, 2026-09-15.** The final consistency pass incorporates the four gate
> corrections and removes the stale instructions they superseded: built-in LangChain MCP
> on FastMCP 4, model-safe façade schemas, honest local-path provenance, one-image execution
> isolation, and versioned execution plans. **D7 is settled** — see the decisions table.
> Where this directory and [REVIEW.md](REVIEW.md) disagree, this directory is current.
>
> Revision 5 adopts a **dependency policy** — recent stable LangChain-family releases,
> validated together as one set in the new **01/CP0b**, bounded in `pyproject.toml`,
> locked in `uv.lock` — and **migrates MCP off the retired `langchain-mcp-adapters`**
> onto LangChain 1.4's built-in `langchain.mcp`.
>
> Three of revision 2's own corrections were themselves wrong and are fixed here: the
> flag count (104, not 105), the historical MCP context-manager contract, and treating
> these authoritative execution plans as disposable local notes. `docs/execution-plan/`
> is deliberately versionable even though other local material under `docs/` stays
> ignored.

---

## The target

> **A local, single-user Docker Compose application** that runs Vitess AI Agent on a
> personal computer and reuses `juena-core`.

Everything in these plans is sized for that. Specifically:

- the browser and Docker run on the same machine; only one person uses it at a time;
- the UI and API bind to `127.0.0.1`, never the office network;
- Postgres persistence still matters, because conversations should survive
  `docker compose restart`;
- the app and the VITESS execution service **share the same files**, so they are two
  services in one Compose project, not a container and a host process;
- juena-chatbot keeps its existing SAML authentication, untouched;
- production deployment is a later phase, not a hidden requirement of this one.

**Deferred, not forgotten.** SAML/OIDC for Vitess · multi-user authorization and
per-user quotas · remote MCP authentication and TLS · public ingress · horizontally
scaled workers · managed object storage · high availability and backup automation ·
publishing `juena-core` to a package index.

These are recorded as **non-goals** so that local implementation does not accidentally
grow production machinery. **They must be reopened before binding the service beyond
loopback, or before a second person is given access.**

What is *not* deferred, because it produces wrong science or lost work even with one
user: fail-closed command generation, path containment, `agent_id` on threads, the
cross-process evidence contract, and real delegation-order tests.

> **These plans are authoritative source material and must be versioned before execution.**
> The repository may continue to ignore other local material under `docs/`, but
> `.gitignore` explicitly re-includes `docs/execution-plan/`. See *Before you can start*
> below.

---

## The goal

Rebuild **Vitess AI Agent** as a separate, deployable application that consumes
juena-chatbot's infrastructure as a shared package — rather than folding VITESS into
the chatbot, or forking twelve thousand lines of it.

Both projects are part of **JüNA** (Jülich Neutron AI Agents) and were written by the
same author about a year apart. The Vitess agent came first. It carries real domain
value that nothing else has:

- **104 hand-transcribed VITESS parameter fields**, each carrying its command-line
  flag — readin 13, guide 15, writeout 31, monitor1d 20, monitor2d 25. (A repo-wide
  `grep -c '"flag"'` returns 105; the extra hit is `get_field_flag`'s own
  `.get("flag", "")` in `base.py`, which is the reader, not a field. An earlier draft
  said "ninety per module", which was wrong by about five times.)
- the command-builder that turns those into a neutron-simulation pipeline,
- and two working agents.

Its *infrastructure* is the older generation, and it has aged badly:

- The agent registry is a **process-global singleton** — one compiled agent per
  agent id, shared by everyone, checkpointed in memory. All users share one
  conversation state, and `restart_agent` wipes it for everyone. The system is
  effectively single-user.
- No authentication, no database, nothing survives a restart.
- Configuration has drifted from reality: Compose still publishes ports 9001–9004 for
  MCP servers that were deleted, and the README still documents three Python packages
  that no longer exist.

juena-chatbot solved all of this. This work moves the good parts of Vitess onto it.

---

## The plans

| | Plan | What lands | Depends on | Delegable as |
|---|---|---|---|---|
| 00 | [The boundary](00-BOUNDARY.md) | The module-by-module decision table for `juena-core`. No code. | — | one design review |
| 01 | [Extract juena-core](01-EXTRACT-JUENA-CORE.md) | A `juena_core` package that imports and has its own tests | 00 | nine tasks (**CP0a**, **CP0b**, then CP0–CP6) |
| 02 | [Chatbot cutover](02-CHATBOT-CUTOVER.md) | juena-chatbot consumes juena-core, with no regression, **proven** | 01 | six tasks (steps 1–6) |
| 03 | [Vitess v2](03-VITESS-V2.md) | A second application on the same core | 02 | eight tasks (CP0–CP6, plus CP3a) |

### Why this order, and why 02 is not optional

**01 and 03 build. 02 measures.** An extraction validated only against the code you
extracted it from is an extraction validated against itself. Cutting juena-chatbot
over *before* v2 exists means the boundary is tested against a system that already
works, with a known-good test suite as the instrument, and with no second consumer
to confuse the evidence.

This is the same sequencing the juena-rag migration used
(`juena-rag/docs/execution-plan/`), and it worked there for the same reason. That
directory is the style these documents copy: numbered checkpoints, a "what actually
landed" note written after each one, and a decisions table so a later session does
not silently re-open a settled question.

**Do not do 02 and 03 in the same branch.**

---

## Decisions these plans assume

Settled in review before planning. Recorded here so a later session does not re-open
them.

| Decision | Choice |
|---|---|
| Deployable shape | Separate repo. `vitess-ai-agent` v2 stays its own product; its agents are **not** added to juena-chatbot |
| Shared layer | Extract `juena-core` from juena-chatbot into its own repository. Both apps consume it; neither forks it |
| Sequencing | Extract core **first**, cut juena-chatbot over, *then* build v2 |
| Agents carried over | `simulator` (guided single simulation) and `advanced_mode` (batch parameter sweep) |
| Infrastructure inherited | Server + streaming + UI shell; Postgres persistence and checkpointing; specialist delegation and verified reports |
| Infrastructure **not** inherited | SAML authentication, the Podman sandbox, background research jobs |
| VITESS execution | Stays **FastMCP**. VITESS does not move into juena's sandbox |
| VITESS documentation search | Stays **vitess-rag** (Chroma). Core must not depend on juena-rag |
| Identity, this phase | One fixed **local principal** with a stable UUID, injected through the same dependency a real provider would implement |
| MCP deployment | An **internal Compose service**, not a host process — it must share files with the app |
| Execution results | **Structured metadata returned by MCP + files on the shared volume**; the API process turns those into `execution_events` and artifacts |
| Plots | **PNG file artifact** is canonical. Interactive Plotly is a later, separately declared contract |
| Simulator rollback | **None.** No `simulator_legacy` — finish the golden path instead |
| **D7 — core provenance** | `juena-core` is a **sibling directory consumed as a uv path source**. `uv.lock` pins the third-party dependency set; a clean core tree, recorded core commit SHA and image digest identify the core bytes. No remote, tag or build credentials while the target is one local machine |
| **D7 — v2 repository** | A **new repository with fresh history**. The old `Vitess-AI-Agent` stays intact as a reference |
| **D7 — Docker** | The image **COPYs core in from the build context**. No private fetch, no secret mount, nothing to rotate |

### Settled from review

Four questions the review left open, now answered:

- **D4 — how outputs return.** MCP writes files beneath the shared run directory and
  *returns structured metadata* (per-module status, exit code, timestamps, stdout/stderr
  summary, produced-file descriptors). The API process translates that into
  `execution_events` and registers artifacts. This is the contract, because an
  in-process queue cannot cross a container boundary.
- **D5 — canonical plot representation.** PNG file artifact, delivered through the
  authenticated artifact endpoint exactly as juena's sandbox plots are. The existing
  Plotly-JSON tools get an adapter.
- **D6 — `simulator_legacy`.** Dropped. It would drag back the process globals, the
  in-memory checkpointer and the old MCP behaviour, and a rollback target that defines a
  second persistence contract is not a rollback.
- **D1–D3, D8, D9 — local topology.** Accepted as proposed: one Compose project, MCP
  internal-only, one image with different commands, fixed local principal plus
  `agent_id` plus `thread_id` identifying a conversation.
- **D7 — package provenance.** Settled: sibling path source, committed lock, new v2
  repository, core COPYed into the image. See the decisions table above.

---

## Execution state (2026-09-15, through 01/CP4)

The repositories and plans now exist. One precondition remains intentionally unresolved:
the chatbot worktree is dirty and **must not be blindly reverted**. CP1 proceeded only
after verifying that every copied source file itself matched commit `e4a5eb3`; its unit
and integration counts are recorded as a dirty-checkout observation in plan 01. Plan 02
still requires a clean baseline before the application cutover.

| Repo | State | What it blocks |
|---|---|---|
| `Vitess-AI-Agent` | execution plans versioned on `feature/migrate-to-juena` | receives a plan-record commit after each completed core checkpoint |
| `juena-chatbot` | `e4a5eb3`; modified `env.example` and `juena`, plus untracked `.claude/` | **plan 02's clean-tree baseline**; these user changes remain untouched |
| `juena-core` | repository exists; CP0a through CP4 complete — the server factory, both routers and the interrupt-kind registry now run against a real Postgres | CP5, the client and UI shell, is next |

D7 is no longer among the open prerequisites: core is a sibling consumed as a path
source, v2 is a new repository, and the image COPYs core in — so there is no remote to
create, no tag to cut and no credential to configure before CP0.

Two consequences constrain the design rather than follow from it.

**Identity without SAML.** v2 inherits Postgres but not SAML, and persistence needs a
user id regardless — thread ownership and per-user memory are keyed on it. So core
defines the identity *seam* (who is asking, and may they touch this conversation) and
each application supplies the answer. juena-chatbot keeps its real SAML service provider,
untouched. **v2 runs on a fixed `local_principal`**: one configured, stable UUID, injected
through the same dependency a real provider would implement, refusing to construct the app
when the API is published, and upserting its own `users` row at startup so the first
`Chat` insert has a foreign key to point at. Adding SAML to v2 later is then a different
callable passed to `create_app`, not a rewrite of the routes.

**No retrieval in core.** juena-chatbot searches juena-rag over HTTP; v2 searches an
embedded Chroma index. Neither belongs in the shared layer, and there is nothing to
abstract: `grep -rn "from juena.indexing" src/` returns five hits, all in
`agents/juena_agent.py` and `tools/repo_search.py`, both of which stay in the
application. Core treats "a thing that can search" as something the app hands in.

---

## Findings that change the work

Verified first-hand against the code, not assumed. Each one changes a plan.

**1. Importing any `juena` module today loads `.env` and can raise.**
`src/juena/core/config.py:394` is `global_config = Config.initialize()`, at module
scope, and `initialize()` calls `validate_required()`, which raises when a provider
key is missing. `src/juena/core/log.py:11` imports `Config` at module level, and
`get_logger` is imported by nearly every module in the package. Copy that structure
into a shared package and `import juena_core` fails on a laptop with no `.env`. This
is the single biggest structural obstacle to extraction, and it is the whole content
of **01/CP1**.

**2. `generate_cli_command` silently ships wrong physics.**
In `src/vitess_ai/mcp/supervisor_tools.py`, around lines 150–172: a module that is
missing from `module_results`, carries no `cli_parameters`, or is absent from the
executable map is written to the log and then `continue`d. The function returns
`success: True` with a **shorter pipeline** — and this field:

```python
"modules_included": [m for m in execution_order],
```

reports every module that was *requested*, including the ones that were dropped. A
user asks for a guide in the beamline, the guide silently vanishes from the pipeline,
and the tool reports success with the guide listed as included. The simulation is
physically wrong and looks right.

`tests/unit/test_mcp_tools/test_supervisor_tools.py:140`
(`test_missing_modules_handling`) asserts `result["success"] is True`, with the
comment "Should still generate command for available modules" — so the test locks the
behaviour in. **This is the most important defect in either repository.** Corrected in
**03/CP1**.

**3. MCP is not new to juena-chatbot.** It currently depends on the now-retired
`langchain-mcp-adapters>=0.1.9` and runs an MCP *client* in production
(`src/juena/tools/context7.py`). That is useful current-state evidence, not a target
lifecycle to copy. Plan 01 migrates Context7 into the contained `juena_core.mcp` layer;
v2 uses that same layer with LangChain 1.4's `MCPAdapter`. The installed lifecycle is
measured in **01/CP0b** and implemented in **01/CP5** and **03/CP3**.

**4. `advanced_mode` does not actually use MCP.**
`src/vitess_ai/agents/advanced_mode/tools.py:209` and `:488` do
`from vitess_ai.mcp import supervisor_tools`, then call
`supervisor_tools.inspect_thread_folders.fn(...)` — reaching *inside* the FastMCP
decorator to the undecorated function, in the same process. Only `simulator` uses a
real `MultiServerMCPClient`. "VITESS execution stays FastMCP" is true of one agent out
of two today. Resolved in **03/CP1** and **03/CP3**.

**5. The inherited machinery touches the not-inherited sandbox in exactly two
places.** `src/juena/agents/specialist_outcome.py` imports
`juena.sandbox.artifacts.get_artifact_store` and `juena.sandbox.runtime._context_value`.
That is the entire coupling between the verified-report machinery (inherited) and
Podman (not inherited). Two imports. Handled in **00** and **01/CP2**.

**6. `repo_root()` breaks once core is an installed package.**
`src/juena/core/paths.py` walks up from `__file__` until it finds a `pyproject.toml`.
From inside `site-packages/juena_core/…` that finds either the wrong root or nothing.
Every data path, the `.env` location and the SAML configuration directory hang off it.
**Core takes its roots from settings, never by walking up.** Handled in **01/CP1**.

**7. The debris in Vitess-AI-Agent is untracked, so it costs nothing to leave
behind.** `git ls-files` returns nothing for `[Template] Praktikum 1.ipynb` (103 KB of
unrelated coursework; `*.ipynb` is gitignored), nothing for `src/vitess_ai/skills/`
(only `__pycache__` — there is not even an `__init__.py`), and nothing for `.env`.
`git status --short` is clean. v2 starts clean by **not copying** them, which is
`rm`-free. Relevant to **03/CP0**.

**8. Two `SupervisorStage` enumerations disagree with each other.**
`src/vitess_ai/schema/supervisor.py:9` has `WELCOME / MODULE_EXECUTION / COMPLETION /
ERROR`; `src/vitess_ai/schema/server.py:170` has `WELCOME / CONFIGURATION / EXECUTION
/ COMPLETION / ERROR`. This is not a copy-paste duplicate — they are two different
state machines wearing one name. Neither is ported. See **03/CP0**.

### Found by review, verified

**9. `Chat` has no `agent_id`.** `server/database/models.py:101-112` carries
`thread_id`, `user_id`, `title`, `summary`, `created_at`, `updated_at` — and nothing
saying which agent owns the conversation. juena-chatbot has one agent so it never
mattered; v2 has two. Without it, switching mode in the UI can silently resume a thread
under a different graph. Added in **01/CP3**, enforced in **03/CP4**.

**10. `ArtifactStore` is in-process and cannot cross a container boundary.**
`sandbox/artifacts.py:157-158` holds `_pending_message` and `_pending_events` as plain
dictionaries, drained by `drain_events()` at `:387`. An MCP *container* cannot enqueue
into the API process's memory, and a shared Docker volume does not make Python memory
shared. This is why D4 had to be answered before any middleware is wired. See
**00** and **03/CP3a**.

**11. The generated script declares one shell and is run with another.**
`mcp/supervisor_tools.py:352` writes the file with a `#!/bin/sh` shebang; `:377` then
executes it as `['/bin/bash', script_path]`. The shebang is decorative and wrong. On
top of that, model-influenced parameter values and paths are interpolated into shell
text, so schema validation — which checks types and permitted fields — is being relied
on for something it cannot provide. Corrected in **03/CP1**.

### Found by the gate review, verified — these were blocking

**14. There is no typed path from a validated module to the command builder.**
`agents/delegation.py:47-58` passes exactly two things across the boundary, in and out:
`messages` and `files`. A specialist returns a `SpecialistReport`, whose fields are
`status`, `finding`, `evidence`, `actions`, `limitations` — **prose**. Plan 03 drops both
existing `ModuleResult` definitions.

So after a guide specialist validates `GuideParameters`, **nothing carries that object
anywhere**. The only remaining route to `run_simulation` would be the model retyping the
values into tool arguments — which is exactly the model-authored path CP1 exists to
close. Resolved in **00, decision 14** and **03/CP4**.

**15. The argument-vector plan still carried shell-era data.**
Correcting `generate_cli_command` to emit argument vectors does not help while its
*inputs* are shell strings:

- `catalog.py:51-119` stores executables as `$V/read_in`, `$V/guide_parallel`, … — `$V`
  is a shell variable and expands to nothing in an `execve`;
- `guide_params_to_cli` (`tools/guide.py:36`) returns
  `" ".join(f"{flag}{param}")` — one concatenated string, with flag and value glued
  (`-w3.0`). **Splitting that back apart safely is not possible**: a filename containing
  a space is indistinguishable from two arguments;
- the golden vector I wrote still expected `--L${L}01`, another unexpanded shell
  variable.

Resolved in **03/CP1** and **03/CP2**.

**16. The MCP client is not an async context manager, and discovery requires a live
server.** *(Historical — superseded by finding 19: `MCPAdapter` **is** one.)* Read the installed source, rather than probing with `hasattr`:
`MultiServerMCPClient.__aenter__` and `__aexit__` both
`raise NotImplementedError(ASYNC_CONTEXT_MANAGER_ERROR)` — *"Context manager support has
been removed."* Only `client.session(...)` is a context manager.

And `get_tools()` must reach the server to discover tool schemas. So revision 2's
"register the tools anyway when MCP is down" is **not implementable** without hand-writing
four static proxy tools and their schemas. Resolved in **03/CP3**.

**17. `SpecialistOutcomeMiddleware` runs inside specialists only.** It is installed at
`specialist_runtime.py:249`, inside `build_specialist_middleware` — not in the supervisor
stack. v2 executes simulations at the **root supervisor**, so nothing would compose a
`<verified_by_server>` block there. CP3a described a wrapper that appends
`execution_events` and then assumed a final block would appear. It would not. Resolved in
**00, decision 15** and **03/CP3a**.

**18. `run_id` already means something else.** `server/agent/input_handler.py:52` does
`run_id = run_id or uuid4()` per **graph invocation**, and passes it as
`RunnableConfig(run_id=...)`. One turn, one id. But `advanced_mode` runs *many*
simulations in a single turn, so that id cannot name an output directory. Two identifiers
wearing one name. Resolved in **00, decision 16**.

**19. `langchain-mcp-adapters` is retired.** LangChain 1.4.0, released 2026-09-01, ships
MCP inside the library in the `langchain.mcp` namespace, built on FastMCP, and it
**replaces** the standalone package. `MultiServerMCPClient` becomes `MCPAdapter`, which
**is** an async context manager; `get_tools()` becomes `await adapter.list_tools()`; the
config is the `{"mcpServers": {...}}` shape with the transport **inferred**; structured
results arrive as `message.artifact["structured_content"]`; and cross-cutting tool
behaviour is a `@wrap_tool_call` middleware. The namespace is **beta**
(`LangChainBetaWarning`), accepted deliberately and contained in `juena_core.mcp`.
This supersedes findings 12 and 16, and the MCP instructions in revisions 2–4.

**20. Middleware cannot remove a field from an MCP server's advertised schema.** An
earlier revision said trusted fields would be "omitted from the exposed tool schema" while
an interceptor inserted them. Interception rewrites a call; it does not change what the
model is offered. v2 therefore binds **application façade tools** to the model and never
the raw MCP tools — see 03/CP3a.

**21. `uv.lock` does not pin a path dependency's source.** It locks resolved third-party
versions; a directory dependency installs whatever is in the directory, and cannot be
hash-checked. "Pinned by the committed lock" was wrong for `../juena-core`. Replaced by a
recorded core commit SHA and image digest — see 01/CP6.

**13. Half the "upload" UI is not upload, and it duplicates a schema field that already
exists.** Of the six sidebar slots in `modules/catalog.py`, three are `mode:
"path_only"` — `writeout`, `monitor1d`, `monitor2d` (`catalog.py:86-126`). They upload
nothing. They set an **output filename**, and each of those filenames is already a
declared parameter with its own CLI flag:

| Sidebar slot | Schema field it duplicates | Schema default | Sidebar default |
|---|---|---|---|
| `writeout` | `WriteoutParameters.sOutFileName` (`-A`) | `output.dat` | **`output.out`** |
| `monitor1d` | `Monitor1DParameters.fMonitorFilename` (`-O`) | `monitor1D.dat` | `monitor1D.dat` |
| `monitor2d` | `Monitor2DParameters.fMonitorFilename` (`-O`) | `monitor2D.dat` | `monitor2D.dat` |

**The writeout row already disagrees with its own schema.** Two defaults for one value,
in two files, and nothing makes them agree. Resolved in **03/CP2** and **03/CP6**.

**12. `MultiServerMCPClient` has no `close()` or `aclose()`.** *(Historical — the
package is retired and v2 uses `langchain.mcp`; see finding 19.)* Verified against the
installed `langchain-mcp-adapters==0.2.2`: `has close: False`, `has aclose: False`,
`has __aexit__: True`. juena-chatbot's `shutdown_agents` (`registry.py:164-177`) already
handles this defensively — it looks for either method and `continue`s when neither
exists — so the running code is correct and the Context7 close is simply a silent
no-op. **There is no lifecycle contract to write**: the client is stateless, each call
opens and cleans up its own session, and `__aenter__`/`__aexit__` raise
`NotImplementedError`. Only `client.session(...)` is a context manager, and v2 does not
need a persistent session.
**03/CP3** must not copy a shutdown contract the dependency does not offer.

---

## What every plan holds to

Six standing rules. They are repeated in each plan because each plan is meant to be
read alone.

**1. `juena_core` never imports `juena` or `vitess_ai`.** The dependency runs one way.
This is the one mistake that is expensive to undo, and nothing enforces it by default,
so 01/CP0 makes it an executable check.

**2. `juena_core` never depends on `juena-rag` or `vitess-rag`.** Retrieval is supplied
by the application. Same check, same pattern.

**3. The base install is the server and the agent kit.** Podman, SAML, Chroma,
pgvector, Streamlit and `fastmcp` are each somebody's optional extra or somebody's
application. A colleague installing `juena-core` to build a third agent must not
acquire `pysaml2` or `podman`.

**4. Core owns the vocabulary and the wiring; the app owns the domain.** Core knows
what a specialist report is, and the order a middleware stack goes in. It does not
know what a neutron guide is, and it does not know what a repository is.

**5. Prefer copying a convention to sharing a mechanism.** The `./juena` launcher, the
repository-survey pattern, the SAML service provider — each is copied, not abstracted.
Promoting a module into core later is cheap; removing a hook system that two
applications depend on is not.

**6. Measure before claiming.** Every checkpoint ends in a command that passes or
fails. "The tests pass" means "it works in the shape the test built" — where a claim
matters, delete the fix, watch the test fail, and put it back.

---

## Vocabulary

Terms used throughout, defined once.

| Term | What it means here |
|---|---|
| **Agent** | A compiled LangGraph graph registered under an id. `POST /{agent_id}/stream` dispatches to it. Vitess v2 has two: `vitess` and `advanced_mode` |
| **Specialist** (subagent) | A plain dictionary `{"name", "description", "runnable"}` handed to `SubAgentMiddleware`. There is no base class and no registry — you add one by importing a builder and adding one line |
| **Middleware** | A layer wrapping the model call. The *order* of the stack is load-bearing; it is nesting order, not a list of independent plugins |
| **Checkpointer** | Where conversation state is stored between turns. juena-chatbot uses Postgres; Vitess today uses memory, which is why nothing survives a restart |
| **MCP** | Model Context Protocol — a way to expose tools over a transport. juena-chatbot is a *client* of one (Context7); Vitess runs a *server* (the VITESS binaries) |
| **Artifact** | A file produced during a turn — a plot, a data file — delivered to the browser through an authenticated endpoint rather than as a path in the text |
| **`<verified_by_server>`** | A block the application writes from real exit codes and the real file store. The model cannot influence it, and where it disagrees with the model's own report, it wins |
| **Interrupt** | A pause in the graph waiting for a human — an approval, or a clarifying question. Resumed through `POST /resume` |
| **Checkpoint (CP)** | A unit of work in these plans, ending in a command that passes or fails |

---

## Still open

Each is flagged in the plan it affects, with options rather than an invented answer.

- **Whether `research/` belongs in core after all.** `advanced_mode` runs batch
  sweeps; a sweep is long by definition, and today it runs inside a tool call tied to
  the HTTP connection — precisely the problem juena's background-research subsystem
  exists to solve. Reopening costs a `juena-core[research]` extra and moving one
  table; `findings.py` is already in core. *What would reopen it:* the first time you
  close the browser mid-sweep and lose forty minutes of simulation. (03/CP5)
- **Whether v2's Streamlit sidebar ever converges on juena's.** If it does, promote it
  into `juena_core.ui`. Promoting is cheap; a hook system is not. (00, 03/CP6)
- *(D7 is settled — see the decisions table.)*
- **Whether the `run_manifest.json` on the shared volume is needed.** D4 chose
  structured metadata returned from the tool call. A manifest written beside the outputs
  would additionally survive a crashed or timed-out MCP call. *What would reopen it:*
  the first run whose files exist but whose result never reached the API. (03/CP3a)

### Closed by review, recorded so they are not re-opened

- **Whether the MCP server runs on the host.** No — it must share files with the app,
  so it is a Compose service. The `juena-rag` analogy that suggested otherwise was
  wrong: juena-rag communicates only over HTTP.
- **Whether the rebuilt simulator needs a legacy fallback.** No. See D6.
- **Whether v2 needs SAML now.** No. A fixed local principal, injected through the
  identity dependency.
