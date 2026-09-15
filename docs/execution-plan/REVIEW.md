# Review of the Vitess AI Agent execution plans

> **Resolution, added 2026-09-15 (not part of the original review).**
> **Status: accepted and incorporated.** Every correction in sections A–G and
> *Smaller corrections* has been verified against the code and applied to the plans.
> The open decisions are settled: **D1** local single-user Compose only · **D4**
> structured MCP metadata plus files on the shared volume · **D5** PNG file artifact
> canonical · **D6** no `simulator_legacy` · **D2, D3, D8, D9** accepted as proposed ·
> **D7** still open.
>
> Two points were narrowed on verification. **(B)** `MultiServerMCPClient` 0.2.2 indeed
> has no `close()`/`aclose()` — but juena-chatbot's `shutdown_agents`
> (`registry.py:164-177`) already probes for either and continues when absent, so the
> running code is correct and its Context7 close is a silent no-op; `__aexit__` does
> exist. **(Binary uploads)** the UTF-8 decode is at `server/chat/inputs.py:104`, on the
> *chat attachment* path; VITESS module uploads go through `server/file_storage.py` and
> never decode, so `.h5`/`.nxs` belong there with their own policy.
>
> One defect the review found but understated: the generated script declares `#!/bin/sh`
> (`supervisor_tools.py:352`) and is executed as `['/bin/bash', …]` (`:377`).
>
> **This document is kept as written, as the record of the review.** Where it and the
> plans now differ, the plans are current.

**Status:** discussion draft — *superseded by the resolution above*
**Reviewed:** 2026-09-15
**Vitess baseline:** branch `feature/migrate-to-juena`, commit `aba134b`
**Deployment assumption:** one user, one personal computer, Docker Compose, and no
public or larger-server deployment yet

This document records a study of:

- [README.md](README.md)
- [00-BOUNDARY.md](00-BOUNDARY.md)
- [01-EXTRACT-JUENA-CORE.md](01-EXTRACT-JUENA-CORE.md)
- [02-CHATBOT-CUTOVER.md](02-CHATBOT-CUTOVER.md)
- [03-VITESS-V2.md](03-VITESS-V2.md)

It is a review, not a replacement execution plan. Its purpose is to support
back-and-forth discussion before implementation changes begin.

---

## Executive verdict

The overall direction makes sense:

1. extract a reusable `juena-core` package,
2. cut the existing JüNA chatbot over to it and prove that the extraction did not
   cause regressions,
3. rebuild Vitess v2 as a separate application using the shared core.

That sequence is the strongest part of the proposal. In particular, Plan 02 should
remain mandatory: the existing chatbot is the first real consumer and therefore the
best test of whether the proposed package boundary is genuine.

The plans are not yet safe to execute exactly as written. The main blockers are not
the overall architecture. They are contradictions at several interfaces:

- the proposed core boundary moves application-specific client and API code;
- MCP startup failure and later recovery are described inconsistently;
- a host MCP process cannot see Docker's named project volume;
- the execution-evidence and artifact bridge between MCP and the API is not defined;
- the database model does not distinguish conversations for the two proposed agents;
- command execution still treats schema validation as shell safety;
- the simulator tests do not actually prove delegation order.

For a personal-PC deployment, the design can be made substantially smaller. We can
defer production identity, multi-user authorization, quotas, distributed deployment,
and externally secured MCP. We should not defer the interface and correctness issues
above: they can still produce wrong simulations, lost files, mixed conversations, or
commands that cannot run.

**Recommendation:** amend Plan 00 first, simplify Plan 03 around a local Compose
topology, and then keep the existing `00 -> 01 -> 02 -> 03` sequence.

---

## Scope used for this review

The immediate product target should be stated as:

> A local, single-user Docker Compose application that runs Vitess AI Agent and
> reuses `juena-core`.

This review assumes:

- the browser and Docker run on the same personal computer;
- only one human uses the application at a time;
- the UI/API port binds to loopback rather than the public network;
- Postgres persistence is still useful across container restarts;
- the app and MCP execution service share the same project files;
- VITESS commands execute inside Docker, not in an unmanaged host process;
- JüNA chatbot keeps its existing authentication behavior;
- production deployment is a future phase, not a hidden requirement of this one.

If any of these assumptions changes, the deferred items below must be reopened.

---

## What the plans get right

### 1. The migration order

`juena-core -> JüNA cutover -> Vitess v2` is a sound dependency order. It prevents
Vitess v2 and the extraction from being debugged simultaneously, and makes the
existing JüNA test suite evidence for the new package boundary.

### 2. Domain code stays outside core

VITESS schemas, command generation, neutron-simulation workflow, Chroma retrieval,
and application prompts belong to Vitess. JüNA repository search and research jobs
belong to JüNA. Core should provide contracts and reusable infrastructure without
knowing either domain.

### 3. Preserve live persistence contracts

Keeping current database column names and checkpoint literals avoids an unnecessary
data migration during an already large architectural migration.

### 4. Remove process-global agent state

The existing global registry, in-memory checkpointer, environment-variable thread
transport, and restart behavior are poor ownership boundaries. Moving conversation
state to Postgres and passing runtime context explicitly is the right correction,
even for one local user.

### 5. Fail closed when generating a simulation

The plan correctly identifies the most serious current defect: missing or unknown
modules are silently omitted while `generate_cli_command` still reports success.
Rejecting an incomplete pipeline is essential scientific correctness work.

### 6. Keep FastMCP as the execution boundary

Keeping VITESS execution outside the agent/API process is reasonable. It separates
LLM orchestration from native command execution and gives the execution service a
clear health boundary.

### 7. Avoid a general plugin or hook system

The two applications do not yet justify a broad extension framework. Small explicit
interfaces are easier to test and change.

---

## Local deployment decisions

The following changes make the plans fit the stated personal-PC goal.

| Topic | Decision for the local phase | Later production phase |
|---|---|---|
| User identity | One fixed `local_principal` with a stable UUID | SAML/OIDC and real user records |
| Network exposure | Publish UI/API only on `127.0.0.1` | TLS, ingress, host policy, public threat model |
| MCP | Internal Compose service, not a host process | Authentication and remote service policy if needed |
| Database | One Postgres Compose service | Backups, HA, managed database, migrations at scale |
| Authorization | No multi-user policy, but keep correct thread/agent keys | Per-user ownership checks and quotas |
| Files | One shared Compose volume at the same container path | Object storage or managed shared filesystem |
| Operations | `docker compose up` starts the full stack | Deployment automation and observability |
| Cleanup | Simple explicit/local cleanup | Durable scheduled cleanup and retention policy |

The fixed principal is acceptable only while the service is local and bound to
loopback. It should be injected through the same identity dependency that a future
real provider would implement. It should not be implemented by sprinkling a magic
UUID through endpoint code.

---

## Recommended local topology

```text
Browser on personal PC
        |
        | http://127.0.0.1:<port>
        v
Vitess app container -------- Postgres container
        |
        | internal Compose network
        v
Vitess MCP container
        |
        v
shared /data/projects volume
```

Recommended properties:

- Only the app/UI port is published, and it is bound to `127.0.0.1`.
- The MCP port is exposed only on the internal Compose network.
- The app and MCP services mount the same named volume at exactly
  `/data/projects`.
- Both services use the same application image, or at least images with the same
  file layout and compatible VITESS runtime. Using one image with different service
  commands is the simpler starting point.
- Postgres is declared in the same Compose project.
- `docker compose up` starts all three services. The proposed host-oriented
  `./vitess mcp-up` lifecycle is removed from the local plan.
- MCP readiness uses a dedicated HTTP `/health` endpoint. It should not infer health
  by sending `curl` to `/mcp`.

This topology resolves a concrete mismatch in the current plan: a host MCP process
cannot directly see the app container's named Docker volume or its container-only
absolute paths.

---

## Corrections required before implementation

### A. Correct the `juena-core` boundary

Plan 00 currently says that `clients/client.py` moves as a whole because it calls
core-owned endpoints. The current JüNA client also calls application-specific
endpoints such as `/auth/me` and `/research`. Moving it whole would make core own
JüNA-specific behavior.

The API endpoint module has the same problem. It imports application sandbox,
approval, artifact, and schema behavior. It cannot move as one generic unit merely
because parts of its streaming transport are reusable.

There is also an impossible schema split: the plan leaves `ApprovalResumeInput` in
the application while moving `ResumeInput`, even though the latter is a union that
contains the former.

Recommended amendment:

- move transport primitives, generic request/response models, and the generic agent
  client into core;
- leave JüNA auth, research, sandbox, and approval methods in a JüNA client extension;
- build endpoint routers in the application from core helpers rather than moving the
  existing endpoint module wholesale;
- either keep the complete resume union application-side, or give core a generic
  resume envelope whose application payload is supplied explicitly;
- add an import-boundary test in both directions.

This is the main issue to settle in Plan 00. If it is postponed, Plan 01 will discover
the true boundary through import errors and will no longer be an executable plan.

### B. Define MCP startup and recovery consistently

Plan 01 describes an MCP discovery helper that returns `None` after a discovery
failure. Plan 03 also says that tools stay bound when MCP is down at startup and
become usable after the service recovers. Both cannot be true if a failed discovery
means the tools were never registered.

The installed `langchain-mcp-adapters==0.2.2` client is also not the long-lived
resource described in the plan. `MultiServerMCPClient` does not expose `close()` or
`aclose()` in that version; `get_tools()` creates sessions for tool discovery/calls.
The plan should not copy a shutdown contract that the dependency does not provide.

Recommended local contract:

1. MCP-backed tools are registered deterministically when the agent is built.
2. A startup health probe reports availability but does not permanently remove the
   tools.
3. Each invocation can reconnect through the adapter after MCP recovers.
4. Failure is returned as a typed execution-unavailable error, not an empty tool list
   or successful empty result.
5. Compose health checks call the MCP server's explicit `/health` route.

References:

- [LangChain MCP documentation](https://docs.langchain.com/oss/python/langchain/mcp)
- [FastMCP HTTP health checks](https://gofastmcp.com/v2/deployment/http)

### C. Make the shared file contract explicit

The app accepts uploads and renders artifacts; the MCP service consumes inputs and
produces outputs. Therefore both processes need the same files under the same
absolute root.

Plan 03 currently compares MCP with JüNA's host `juena-rag` process. The analogy does
not hold: retrieval can communicate only through HTTP, while VITESS execution must
also share uploaded and generated files.

Required contract:

- one configured root, initially `/data/projects`;
- the same volume mounted at that path in app and MCP containers;
- paths resolved beneath a server-controlled directory;
- `thread_id`, `run_id`, and filenames validated as identifiers, never accepted as
  arbitrary paths;
- no dependence on a host path that exists only outside Docker.

Even for one user, path containment matters because the model generates tool inputs
and the container may have mounted data, credentials, and network access.

### D. Define the execution-evidence and artifact bridge

The plans say `SpecialistOutcomeMiddleware` will read an `execution_events` state
channel, but Plan 03 does not define the component that creates and updates that
channel for Vitess. At the same time, the old MCP `tool_wrapper.py` is dropped.

The current JüNA `ArtifactStore` also uses in-process pending queues. An MCP process
cannot enqueue an item into an API process's memory. A shared Docker volume does not
make Python memory shared.

Recommended local contract:

1. MCP writes simulation files beneath the shared run directory.
2. MCP returns structured execution metadata: command/module status, exit code,
   timestamps, stdout/stderr summary, and produced file descriptors.
3. The agent/API process translates that returned metadata into
   `execution_events` and registers artifacts for the UI.
4. Durable state needed after restart is stored in Postgres or reconstructed from a
   run manifest on the shared volume; it is not held only in a pending queue.
5. Plot output gets one declared representation. If the UI expects file/PNG
   artifacts, the existing Plotly-JSON tools need an adapter or an explicitly
   separate interactive-plot contract.

This contract should be decided in Plan 00 and tested in Plan 03 before middleware is
connected.

### E. Distinguish the two agents in persisted conversations

Plan 03 proposes top-level `vitess` and `advanced_mode` agents. The inherited JüNA
`Chat` model currently has no `agent_id`. A thread must not silently resume under a
different graph because the user switched agent modes.

For the local phase, multi-user authorization may be deferred, but agent/thread
identity may not. At minimum:

- store `agent_id` with a chat/thread;
- include it in creation, lookup, and resume validation;
- make the UI's selected mode agree with the stored agent;
- pass `thread_id`, `run_id`, project root, and principal through authoritative
  runtime context;
- do not ask the model to supply ownership identifiers;
- do not use process environment variables as per-request transport.

The current advanced-mode `FilesystemBackend` also exposes the whole configured
project root. It should receive a run- or thread-scoped directory instead.

### F. Separate schema validation from command safety

Pydantic can verify types and permitted fields. It does not make interpolated shell
text safe. The current implementation generates a Bash script and runs it with
`/bin/bash`; model-influenced string values and paths can therefore change shell
meaning.

Preferred correction:

- represent each VITESS module invocation as an argument vector;
- launch processes with Python-managed `subprocess` calls without `shell=True`;
- connect pipelines explicitly and perform post-processing in Python;
- keep a rendered command/script only as a display or debugging artifact.

If a Bash boundary is temporarily unavoidable, every dynamic token must be quoted,
paths must be contained under the project root, and tests must cover spaces,
semicolons, command substitutions, leading dashes, and `../` traversal. This should
be treated as an interim constraint, not as proof equivalent to argument-vector
execution.

### G. Test real simulator delegation order

`plan_simulation()` returning an ordered catalog and a `run_simulation` completeness
precondition prove only that the required module set is present. They do not prove
that the supervisor actually delegated guide before monitor, or that the resulting
command preserved the planned order.

Add a runtime-shaped golden test that records specialist/tool events and asserts:

1. the plan order,
2. the observed delegation order,
3. the command module order,
4. fail-closed behavior when any required module is absent or duplicated.

The proposed `simulator_legacy` escape hatch is not free. It retains the old globals,
in-memory state, registry, and MCP behavior. Prefer completing the new golden path
before cutover. If a legacy fallback is genuinely needed, isolate it, time-limit it,
and do not let it define the v2 persistence contract.

---

## Smaller corrections to the verification plan

These are not architectural blockers, but they will otherwise create misleading
green or red tests.

### Schema flag accounting

The proposed test that every top-level field has a CLI flag would incorrectly reject
container fields such as `WriteoutParameters.output_flags` and `filter_limits`.
Their nested leaf models carry the actual flags. The test should recurse to leaf
fields and distinguish configuration containers from CLI arguments.

The current schemas contain about 104 flag declarations across the module models;
the phrase "roughly ninety fields per module" should not become a hard numerical
acceptance criterion.

### Catalog executability

The catalog contains an upload-only `instrument` entry with no VITESS executable.
The test should require executability only for simulation-module entries, not every
catalog row.

### Binary uploads

Do not add `.h5` or `.nxs` to a validator that strictly UTF-8-decodes uploaded files.
Binary neutron data needs a separate size/signature/content policy.

### Test reconciliation

Comparing only pytest pass counts can hide one removed test and one newly added test.
Record and compare collected node IDs, then explain intentional additions, removals,
and moves.

### Import boundaries

Use a Python AST/import inspection test rather than `grep` for package-boundary
enforcement. It is more portable and understands imports split across lines.

### Optional dependency testing

An assertion that optional UI modules are not imported is meaningful only from a
clean environment using the built wheel without those extras. A developer virtual
environment may already contain Streamlit and mask packaging errors.

### Packaging and CI

- If a Hatch-built package uses direct Git dependencies, explicitly configure
  `allow-direct-references`.
- If `vitess-rag` remains a submodule, CI checkout must initialize submodules
  recursively.
- Pin shared-core compatibility through a lockfile and a bounded dependency range;
  avoid testing two repositories against arbitrary moving branch heads.

---

## Proposed amendments by plan

### Plan 00 — boundary

Amend before any extraction work:

- split the client and API modules at application-specific routes;
- resolve the `ResumeInput` union ownership;
- define the fixed local identity provider seam;
- define `agent_id` ownership for persisted threads;
- define MCP discovery/recovery behavior;
- define execution evidence and artifact transport;
- define the shared project-path contract;
- mark production identity and multi-user policy as deferred.

**Exit condition:** every module in the move/stay table can be imported without an
application dependency crossing into core, and each cross-process interaction has a
declared producer, consumer, and persistence owner.

### Plan 01 — extract `juena-core`

Keep the checkpoint structure, with these adjustments:

- extract generic primitives rather than copying whole mixed-ownership files;
- test the built wheel in a clean environment;
- test AST-level forbidden imports;
- use the actual MCP adapter lifecycle contract;
- keep artifact registration interfaces process-neutral;
- make filesystem roots explicit settings rather than repository discovery.

### Plan 02 — JüNA chatbot cutover

Keep this plan mandatory. Strengthen its proof:

- compare collected test identities, not only totals;
- run existing auth, streaming, artifact, approval, and research behavior through the
  cut-over application;
- verify the built core package is the code actually imported;
- preserve current JüNA authentication and sandbox behavior;
- do not add Vitess-specific compromises to make JüNA pass.

### Plan 03 — Vitess v2

Rewrite its deployment portions for local Compose:

- app, MCP, and Postgres are Compose services;
- app and MCP share `/data/projects`;
- only app/UI binds to loopback;
- fixed local principal replaces dev-login/SAML for this phase;
- remove host `mcp-up`, PID files, and the host/container path analogy;
- add `agent_id` to thread persistence;
- implement the structured MCP result -> execution event -> artifact path;
- execute argument vectors rather than model-influenced shell scripts;
- verify actual delegation and command order with a golden simulation.

---

## Suggested execution gates

The following gates keep the work incremental without introducing a larger platform.

| Gate | Evidence required before moving on |
|---|---|
| 0. Boundary agreed | Revised ownership table and explicit local assumptions |
| 1. Core package built | Clean-wheel import tests and forbidden-import tests pass |
| 2. JüNA cut over | Existing behaviors pass using the installed core package |
| 3. Vitess domain core | Schemas, catalog, and fail-closed command model pass unit tests |
| 4. Local stack | Compose starts app, MCP, and Postgres; health states are truthful |
| 5. File/evidence path | Upload -> MCP execution -> event -> artifact survives process boundaries |
| 6. Agent workflows | Both agent modes persist separately and use runtime-scoped paths |
| 7. Golden simulation | A real minimal VITESS run preserves planned module order and outputs |

Plan 03 should not be considered complete merely because the UI starts. Its defining
proof is a real local simulation whose planned modules, executed modules, exit state,
files, and UI-visible evidence agree.

---

## Deferred, not forgotten

The following are reasonable to postpone while the product remains local-only:

- SAML/OIDC for Vitess;
- multi-user authorization and per-user quotas;
- remote MCP authentication and TLS;
- public ingress and production hardening;
- horizontally scaled API/MCP workers;
- managed artifact/object storage;
- durable distributed cleanup workers;
- high availability, backup automation, and production observability;
- publishing `juena-core` to a public/private package index.

These should be recorded as non-goals in the plans so that local implementation does
not accidentally grow production machinery. They must be reopened before binding the
service beyond loopback or allowing another user to access it.

---

## Decisions for discussion

These are the remaining choices worth discussing before editing the execution plans.

| ID | Question | Recommended starting answer | Status |
|---|---|---|---|
| D1 | Is local single-user Compose the only target for this phase? | Yes | Proposed |
| D2 | Should app, MCP, and Postgres start together? | Yes, one Compose project | Proposed |
| D3 | Should MCP be published to the host? | No, internal network only | Proposed |
| D4 | How are outputs returned? | Structured MCP metadata plus files on shared volume | Needs agreement |
| D5 | What plot representation is canonical? | File artifact first; optional interactive data separately | Needs agreement |
| D6 | Keep `simulator_legacy` in v2? | No unless the new golden path proves blocked | Needs agreement |
| D7 | How do both apps consume local `juena-core` reproducibly? | Pinned source revision plus lockfile | Needs agreement |
| D8 | Should app and MCP use one image? | Yes initially, with different commands | Proposed |
| D9 | What identifies a conversation? | Fixed local principal + `agent_id` + `thread_id` | Proposed |

---

## Bottom line

The plans have a good architectural spine and become realistic for a personal PC
once production requirements are removed from the critical path. The migration
sequence should stay. The boundary and cross-process contracts need correction before
implementation begins.

The first discussion should focus on D4, D5, D6, and D7. After those are settled,
Plan 00 can be amended and the rest of the plans can be made mechanically consistent
with it.
