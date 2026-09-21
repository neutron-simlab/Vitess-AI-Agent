# Maintainability review: Vitess AI Agent v2

Date: 2026-09-17  
Review type: documentation-only, current v2 implementation compared with Vitess AI
Agent v1, `juena-core`, `juena-chatbot`, and execution plans 00–03.

## Decision summary

V2 is substantially simpler than v1 without discarding the complexity that makes a
VITESS run trustworthy. The v1 `agents` package was about 8,015 source lines and had an
internal import cycle; v2's is about 2,632 lines and the whole v2 package has no cycle.
V2 replaces a hand-built routing graph, mutable process state, model-authored execution
inputs, shell text, and duplicated converters with explicit agents, typed state,
argument vectors, one execution gateway, and server-verified evidence.

Most of the large v2 functions are cohesive trust boundaries and should stay intact.
In particular, the five explicit specialists, authored prompts, two interaction modes,
schema validation, three independent order observations, private run identifiers,
MCP-only execution, and artifact verification are not over-engineering.

The accepted simplifications are targeted:

1. use the framework's native `ToolRuntime` injection instead of six obsolete
   `Annotated[..., InjectedToolArg, SkipJsonSchema]` wrappers;
2. inject the bounded embedding client into `vitess-rag` instead of constructing,
   replacing, and closing a throwaway client;
3. delete six unreferenced v1-era schema response classes and five script demos;
4. remove the unused direct `plotly` dependency;
5. define the two agent IDs once; and
6. replace source references to external checkpoint documents with local invariant
   explanations.

No accepted item shortens a VITESS prompt or changes guided/sweep semantics.

## Snapshot and review controls

### Start snapshot

Captured at `2026-09-17T22:36:11+02:00` before analysis or writes.

| Repository | Branch | Commit | Working tree |
|---|---|---|---|
| Vitess v2 | `feature/vitess-rag-tools` | `688b2b141b2e0a7be8f27804725402bd194f038e` | clean; this includes the current retrieval work |
| `juena-core` | `juena-core-cutover-runtime` | `41371869d67e54a6849e4059b14e21e264d13053` | dirty only in the pre-existing `.gitignore` change |
| Vitess v1 | `feature/migrate-to-juena` | `2715f1e7b0ed0ac78090d4f00e00d4cc85c9731f` | clean; read-only comparison |
| `juena-chatbot` | `juena-core-cutover-runtime` | `27e5016d20db153edb107bb0e3f1b6a6fe4aa75c` | clean; read-only compatibility evidence |

The v2 tracked-worktree and staged-diff SHA-256 values were both the empty-input
digest, `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
This captures the retrieval implementation in commit `688b2b1`; no earlier test count
or dirty-tree review was reused as its baseline.

### End snapshot

Filled after the completed review and verification:

| Repository | Branch | Commit | Working tree |
|---|---|---|---|
| Vitess v2 | `feature/vitess-rag-tools` | `dabd14839324a55bb275903806bf0b70fe98ede3` | tracked tree clean; this requested review directory is untracked |
| `juena-core` | `juena-core-cutover-runtime` | `41371869d67e54a6849e4059b14e21e264d13053` | tracked tree clean; `DOCS/` is visible as untracked |
| Vitess v1 | `feature/migrate-to-juena` | `420ccb0e5f339dfbf96f48713300fe18b3d150d1` | clean |
| `juena-chatbot` | `juena-core-cutover-runtime` | `27e5016d20db153edb107bb0e3f1b6a6fe4aa75c` | clean |

End v2 tracked-worktree diff SHA-256:
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.  
End core tracked-worktree diff SHA-256:
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.

Only this requested review directory was created in v2. No production code, tests,
prompts, workflows, lock file, submodule, or comparison repository was modified.

The snapshot guard detected concurrent changes during the review. V2 advanced from
`688b2b1` to `dabd148`: `.gitignore` stopped ignoring `DOCS/`, the retrieval failure
message and test became deployment-actionable, and
`DOCS/retrieval-in-both-supervisors.md` was versioned. V1 advanced from `2715f1e` to
`420ccb0` with a plan-03 documentation update. Core's uncommitted `.gitignore` edit
disappeared without a core commit change. The changed retrieval code and tests were
reinspected, the static scan was refreshed, and both affected suites were rerun before
this review was finalised.

## Verification actually performed

| Check | Result | Scope and limitation |
|---|---|---|
| Vitess v2 complete suite | **438 passed**, 4 warnings, 24.75 s | Final `dabd148` code snapshot |
| Vitess v1 reference suite | **186 passed**, 2 warnings, 1.52 s | Final clean v1 checkout at `420ccb0` |
| Core non-PostgreSQL suite | **473 passed, 5 skipped**, 2 warnings, 6.45 s | Four PostgreSQL-dependent files excluded |
| Core import-direction gate | **passed**: `import direction ok` | `bash scripts/check-imports.sh` |
| PostgreSQL-dependent core tests | **not run** | No service was present in `docker compose -f tests/compose.postgres.yml ps` |

Two of v2's warnings are actionable Pydantic serialization warnings in
`test_real_agent_writes_verified_block_and_attaches_artifact`; they motivate
`V2-001`. The others are the LangChain MCP beta warning and Starlette's deprecated
`anyio_backend_name` warning.

No browser conversation, live model call, successful retrieval-key query, real SAML
ACS/session round trip, or new live VITESS execution was performed in this review.
Historical live runs recorded in plan 03 are useful provenance, not current reruns.

## Plans 00–03 reconciled with the code

- **Plans 00 and 01:** v2 consumes the extracted core boundary rather than copying
  server, persistence, streaming, UI, or middleware infrastructure. Its domain schema,
  retrieval and simulator remain outside core, as intended.
- **Plan 02:** the chatbot cutover's API and import work landed, but its browser
  rendering and real IFFLogin → `/auth/acs` session round trip remain explicitly open.
  Plan 03 proceeded in the repository despite that acceptance sequencing; this review
  records the gate instead of treating “depends on 02” as proof that it passed.
- **Plan 03:** checkpoints 0–6 and subsequent retrieval corrections are present. The
  status table still ends at the earlier 397-test CP6 record, while the later narrative
  and current tree are at 438. The current commit and rerun suite are authoritative.
- An older architecture review said there was no guard preventing subprocess use
  outside the MCP server. That is stale: current
  `test_no_module_outside_the_mcp_server_runs_a_subprocess` checks the boundary. No
  duplicate recommendation is carried forward.

V2 source and app code contain 34 matching lines that cite `03/CP*` or other plan
labels. The plans live in the v1 repository, so `V2-006` converts those references into
standalone explanations.

## V1-to-v2 capability matrix

| Capability | V1 reference | Current v2 | Preserve / decision |
|---|---|---|---|
| Parameter schemas | Five Pydantic models; 104 recursively counted parameter fields | The same 104 field names and CLI flags; 85 top-level fields; `ReadInParameters.Weight` additionally enforces bounds | **Preserve all 104 and every flag.** The bound is an intentional validation correction |
| Command construction | Multiple converters and shell-shaped command strings; some fields could be silently omitted | One `parameters_to_arguments()` converter and pure argv construction; NUL/missing flags fail closed; MCP runs the process | **Keep** argv and one converter |
| Uploads | Global/file-store behaviour and duplicated/path-only UI slots | Three catalog-owned input slots, per-thread staging, extension/count/size checks, HDF5 signature verification; no output filename in the sidebar | **Keep** one catalog manifest and conversational output names |
| Retrieval | Partial first-generation documentation tools | Four stable tools for both supervisors; three for specialists; per-call degradation; lazy Chroma/ONNX imports | **Keep** tool surface and degradation; simplify client construction with `V2-002` |
| Plotting | Interactive Plotly output | MCP reads all supported monitor layouts and returns canonical PNG artifacts | **Keep** PNG delivery; remove unused direct Plotly dependency (`V2-004`) |
| Guided simulation | Hand-built graph/routing and process-local state | `create_agent`, five explicit specialists, planned/delegated/executed order checks, confirmation before validation, typed private state | **Keep** semantics and explicit specialists |
| Parameter sweep | Model supplied run specs/matrix data; names could become directory identifiers | Tools own variants and `SimulationPlanEntry`; maximum 32; server UUID per run; sequential execution through the same gateway | **Keep** plan/state separation and limit |
| MCP execution | Several drifting process/server paths | Four allowlisted internal MCP tools, one shared volume, one typed `VitessGateway`; application source cannot invoke subprocess | **Keep** MCP-only execution |
| Persistence and identity | `InMemorySaver`, mutable globals, restart/reset behaviour | Core PostgreSQL persistence, fixed local principal, owned threads, trusted runtime user/thread/run IDs | **Keep**; no in-memory fallback |
| Evidence and artifacts | Model-facing success could outrun process evidence | Typed MCP outcomes, path revalidation, artifact registration, execution events, server-authored verified block | **Keep** all verification layers |
| Prompts | Python prompt variants with duplicated default/custom sections | One authored Markdown prompt per supervisor/specialist, plus rendered schema and tool-specific policy | **Never shorten authored VITESS guidance** |

### The 104-field inventory

An import-isolated schema comparison found exact v1/v2 leaf-name and flag equality:

| Schema | Recursively counted fields |
|---|---:|
| `GuideParameters` | 15 |
| `Monitor1DParameters` | 20 |
| `Monitor2DParameters` | 25 |
| `ReadInParameters` | 13 |
| `WriteoutParameters` | 31 |
| **Total** | **104** |

All 85 top-level field names and flags also match. This inventory, recursive flag tests,
converter tests, defaults tests, and actual order tests are the preservation evidence;
aggregate prompt word counts are not. The current rendered authored prompt corpus is
about 13,797 words across the two supervisors and five specialists. V1's aggregate is
not a valid reduction target because it contains duplicated Python variants.

## End-to-end workflow trace

### Guided simulation

1. `plan_simulation` reads `modules.catalog.execution_order()` and writes
   `planned_execution_order` plus a plan event. The model cannot supply the list.
2. The supervisor delegates one module at a time through the module boundary.
3. The specialist uses its full authored `AGENT.md`, appended live schema, optional
   staged-file view, and documentation tools. It presents the complete configuration
   and obtains `ask_user` confirmation.
4. `validate_<module>_parameters` validates the Pydantic model, staged input ownership,
   output filename shape, physical/domain constraints, and CLI expressibility. Only
   this tool writes a `ModuleConfigurationResult` to private state.
5. Delegation records the observed module order. `run_simulation` requires planned,
   delegated, and configured order to agree and rejects stale schema fingerprints.
6. Trusted runtime context supplies user, thread and graph-run identities; application
   code creates a separate `simulation_run_id`. None is model input.
7. `InternalSimulationRequest` reaches the sole `VitessGateway`, which calls only the
   allowlisted MCP façade. The MCP server validates again and constructs argv without a
   shell.
8. Returned paths are revalidated beneath the conversation/run root, registered in the
   artifact store, attached to execution events, and rendered through the root evidence
   and artifact middlewares.

### Parameter sweep

1. The advanced supervisor delegates to the same five specialists compiled in
   unattended mode. The full guided prompt is preserved byte-for-byte before the sweep
   notices; `ask_user` is absent.
2. Each variants tool validates every candidate through the same
   `validate_module_parameters` path and writes `module_variants` to private state.
3. `write_simulation_matrix` computes the Cartesian/paired size before expansion,
   enforces the shared 32-run limit, generates one trusted UUID per run, writes a list
   of `SimulationPlanEntry`, and renders a downloadable matrix *from* that plan. The
   matrix is never read back as executable input.
4. `run_batch_from_matrix` takes no model arguments. It revalidates the stored plan,
   module set, schema fingerprint, and limit, then executes entries sequentially.
5. Each entry becomes an `InternalSimulationRequest` and passes through the same MCP
   gateway, path checks, artifact registration, evidence channel, and run-reference
   model as the guided path. A partial failure returns a tool error rather than a false
   successful batch.

These steps are essential complexity. Combining plan, request, result, evidence and
artifact models into one “simulation” object would erase which layer is trusted.

## Structural and dependency evidence

An AST scan found 64 v2 Python modules, 129 internal import edges, and **zero cycles**.
V1 has 77 modules, 194 internal edges, and one cycle across simulator tools, modules,
catalog and file storage. V2 imports 27 `juena_core` modules (47 imported names), which
confirms that core is a used platform rather than a nominal dependency.

Approximate source lines by area are `agents` 2,632, `schema` 1,571, `mcp` 1,168,
top-level `tools.py` 696, `server` 511, `retrieval` 503, `run.py` 456, `cli` 403,
`plots` 339, `modules` 279, and `state.py` 128. The concurrent commit changed only
retrieval failure wording and tests, not the import graph.

| Large symbol | Approx. span / branches | Decision |
|---|---:|---|
| `tools.build_vitess_tools` | 250 / 18 | **Keep.** One façade over one gateway; trusted args, results, file verification and tool schemas must remain visibly adjacent |
| `advanced_mode.tools.build_batch_tools` | 243 / 21 | **Keep.** Planning and executing the private sweep channel are one lifecycle |
| `module_specialist.build_variants_tool` | 133 / 9 | **Keep.** It is the sole variants-state writer and shares validation with guided mode |
| nested guided `run_simulation` | 126 / 11 | **Keep.** Branches are fail-closed gates and evidence outcomes, not unrelated features |
| matrix renderer / writer | 119 / 13 | **Keep.** The rendered file must visibly derive from the trusted plan |
| CLI command | 110 / 8 | **Keep.** Explicit CLI orchestration is easier to audit than a command framework |
| MCP execute path | 104 / 17 | **Keep.** Process lifecycle, containment and result evidence belong together |

## Highlighted code audit

| Target | Finding | Decision |
|---|---|---|
| `schema/simulation_plan.py` | `SimulationPlanEntry` separates human `run_name`, trusted UUID, and per-module validated results; frozen/forbid model with name controls | **Keep.** It is a security and persistence boundary, not a duplicate request model |
| `agents/specialists/module_specialist.py` | Shared assembly removed five drifting converters while packages remain explicit; file/physical validation and private state write meet at one tool boundary | **Keep structure.** Only simplify runtime annotation (`V2-001`) and historical prose (`V2-006`) |
| `agents/advanced_mode/tools.py` | Matrix is output, not input; plan state and execution are separate; size checked before product; shared artifact helpers already remove safe duplication | **Keep structure.** Do not abstract guided and batch return shapes into a generic runner |
| `cli/arguments.py` | One converter covers measured scalar/list/nested shapes and fails on missing flags | **Keep.** A handler registry would hide three simple shapes and make flags less auditable |
| `agents/advanced_mode/__init__.py` | Two-symbol explicit export, no generic discovery | **Keep**, re-export the central ID after `V2-005` |
| `schema/__init__.py` | Explicitly exports the five parameter models and flag helper | **Keep.** Do not export v1-era response residue; delete it with `V2-003` |
| `retrieval/runtime.py` | Lazy dependency boundary is good; client replacement reaches into `vitess-rag` internals and creates a throwaway transport | **Change only construction** with `V2-002` |

## Representations, factories, globals and tests

### Representations to keep separate

- `ModuleConfigurationResult` is validated specialist output with a schema fingerprint.
- `SimulationPlanEntry` is persisted private sweep intent.
- `InternalSimulationRequest` is the closed application-to-gateway execution request.
- MCP public request/result schemas are the process boundary.
- `SimulationRunReference` is the minimal conversation handle for later plotting.
- planned, delegated and executed order lists are independent observations; their
  equality is the regression oracle, not three competing sources of truth.

The catalog owns module order/upload capability, schema fields own CLI flags/defaults,
and the server upload manifest is derived from the catalog. No second parameter or
upload table should be introduced.

### Process state

Core's agent registry and v2's one-entry RAG tool cache are deliberate process-lifetime
state. The retrieval cache documents that indexing requires an application restart,
and tests clear it. `Config` is application startup policy. None is a v1-style mutable
per-conversation store. Do not replace these with a new container solely to avoid the
word “global”.

### Factory/tool construction

Factories are long because they close over the actual gateway, project root, parameter
model and tool names. This prevents model-visible arguments from carrying trusted
objects. Extracting a generic tool factory would distribute the security review across
callbacks. The one accidental part is the repeated obsolete runtime annotation, handled
by `V2-001`.

### Tests that inspect implementation

Source/AST tests for “catalog imports only data dependencies,” “no subprocess outside
`mcp/`,” prompt/tool agreement, and no duplicate UI filename defaults protect explicit
architecture boundaries and should remain. Two Streamlit wiring tests assert exact
source fragments for `on_change=start_new_thread` and the rerun after
`adopt_thread_agent`. They are brittle, but currently cover call-site wiring that pure
function tests cannot. Replace them only when a real Streamlit/browser component test
exists; deleting them now weakens coverage.

## Accepted recommendations

### V2-001 — use native `ToolRuntime` injection in explicit argument schemas

- **Priority / phase:** P0 correctness prerequisite; first change.
- **Evidence and symbols:** `_FacadeArguments`, `_SweepArguments`, `_BatchArguments`,
  `_ValidationArguments`, `_StagedFilesArguments`, and `_VariantsArguments` declare
  `runtime` as `Annotated[ToolRuntime, InjectedToolArg, SkipJsonSchema()]`. With pinned
  LangChain 1.4.0 / langchain-core 1.6.3, `ToolRuntime` is natively injected and excluded
  from model schemas. A warning-as-error run of
  `test_real_agent_writes_verified_block_and_attaches_artifact` fails while serialising
  the current wrapper with
  `PydanticSerializationUnexpectedValue(... field_name='context' ...)`. A minimal
  explicit Pydantic `args_schema` using plain `runtime: ToolRuntime[Any, Any]` excludes
  `runtime` from JSON schema without a wrapper.
- **Why accidental:** the annotations repeat an older framework contract and now fight
  the framework's own injection marker. They add imports and metadata while producing a
  real serialization warning.
- **Selected target interface:** in all six models use exactly:

  ```python
  runtime: ToolRuntime[Any, Any]
  ```

  Keep `ConfigDict(extra="forbid", arbitrary_types_allowed=True)`.
- **Move/consolidate/delete:** remove every `InjectedToolArg` and `SkipJsonSchema`
  import made unused by this change; do not add a local runtime alias.
- **Consumer migration:** all tools retain their existing Python signatures and names.
  No prompt, state, MCP, or external API changes.
- **Protected invariants:** runtime is absent from every model-visible schema; runtime
  still arrives from the framework; trusted user/thread/run identity remains
  inaccessible to model input; extra args remain forbidden.
- **Regression tests:** parameterise all six argument models/tools and assert runtime is
  absent from `model_json_schema()`; run the focused real-agent evidence test with the
  Pydantic warning promoted to an error; run the full 438-test suite.

### V2-002 — inject the bounded embedding client at construction

- **Priority / phase:** P1 internal/submodule simplification; after `V2-001`.
- **Evidence and symbols:** `retrieval.runtime.build_embedding_function()` constructs a
  `BlabladorEmbeddingFunction`, saves `.client`, overwrites it with
  `build_embedding_client()`, and closes the original. The retained submodule's
  constructor always builds an OpenAI client, so every v2 construction creates a
  transport that is immediately discarded. V2 is coupled to the writable `.client`
  attribute and has a regression test for closing the unnecessary object.
- **Why accidental:** timeout/retry policy belongs to the supplied client, but lack of a
  constructor seam forces mutation of an implementation detail.
- **Selected target interface:** in `rag/vitess-rag`:

  ```python
  def __init__(
      self,
      model_name: str | None = None,
      api_key: str | None = None,
      base_url: str | None = None,
      *,
      client: OpenAI | None = None,
  ) -> None: ...
  ```

  Use the supplied client directly. Only require API key/base URL and construct
  `OpenAI(...)` when `client is None`. `build_from_config()` keeps current environment
  behaviour.
- **Move/consolidate/delete:** v2 passes
  `client=build_embedding_client()` to the constructor; delete replacement,
  `original_client`, and immediate `close()` logic.
- **Consumer migration:** update the embedded package and v2 in one commit. No core or
  chatbot change.
- **Protected invariants:** lazy `vitess_rag`/Chroma imports; bounded query timeout and
  retry count; Chroma embedding protocol/name/config; graceful per-call degradation;
  indexing defaults remain usable.
- **Regression tests:** submodule test that an injected fake is used and `OpenAI` is not
  constructed; existing missing-config/default-construction tests; v2 test that the
  exact bounded client is passed; retrieval suite and full v2 suite.

### V2-003 — delete unreferenced v1-era schema response models and demos

- **Priority / phase:** P2 low-risk internal simplification; independent after
  `V2-001`.
- **Evidence and symbols:** `FillingStage` and the five `InitialResponse*` classes have
  no reference outside their definitions. The five schema modules also contain
  `if __name__ == "__main__"` JSON-print demos. None is exported by `schema.__init__`,
  used by tools, or tested as an interface.
- **Why accidental:** these are remains of v1's structured conversational response;
  current specialists use `SpecialistReport` plus private validated state. Leaving the
  types suggests a second response protocol.
- **Selected target design:** the schema package contains executable parameter models,
  their enums/nested types, flags, validators, and current execution-state models only.
- **Move/consolidate/delete:** delete exactly `FillingStage`,
  `InitialResponseGuide`, `InitialResponseReadIn`, `InitialResponseMonitor1D`,
  `InitialResponseMonitor2D`, `InitialResponseWriteout`, and the five script-only demo
  blocks; remove imports made unused by those deletions.
- **Consumer migration:** none; verify with repository-wide symbol search before the
  change.
- **Protected invariants:** all 104 fields, 85 top-level names/flags, defaults, enums,
  nested output/filter models, validators, and schema exports remain byte-for-byte or
  semantically unchanged.
- **Regression tests:** schema flag inventory, defaults/prompt agreement, module
  configuration tests, and full suite.

### V2-004 — remove unused direct Plotly dependency

- **Priority / phase:** P2 low-risk dependency cleanup; can land with `V2-003`.
- **Evidence and symbols:** `plotly` appears in `pyproject.toml` but nowhere in v2
  source, app, or tests. Current plotting uses the PNG renderer and Matplotlib.
- **Why accidental:** it is inherited from v1's interactive plot path and enlarges the
  declared direct surface.
- **Selected target design:** delete only the direct `"plotly"` requirement and
  regenerate `uv.lock`. If another package retains it transitively, do not add an
  exclusion or workaround.
- **Consumer migration:** none.
- **Protected invariants:** monitor readers, PNG renderer, MCP plot tools, MIME type,
  artifact registration and browser rendering are unchanged.
- **Regression tests:** `uv sync --frozen` after lock regeneration, monitor plot suite,
  MCP plot test, artifact/evidence tests, full suite.

### V2-005 — define agent IDs once without registration side effects

- **Priority / phase:** P2 low-risk representation cleanup; before source-comment
  cleanup.
- **Evidence and symbols:** `"vitess"` and `"advanced_mode"` are repeated in the two
  agent modules, `app.sidebar.AGENTS`, `app.starters`, `app.ui_components`, and the
  default for `vitess_supervisor_middleware`. A drift would make a UI thread target an
  unregistered graph.
- **Why accidental:** these strings denote server identity, not UI copy. The labels and
  descriptions are UI-owned, but the IDs are one shared fact.
- **Selected target interface:** define and export in the already-lightweight
  `vitess_ai.agents` package:

  ```python
  VITESS_AGENT_ID = "vitess"
  ADVANCED_MODE_AGENT_ID = "advanced_mode"
  ```

  Importing `vitess_ai.agents` must not register or build an agent.
- **Move/consolidate/delete:** remove the two definitions from agent implementation
  modules; import the constants in agent registration, advanced-mode re-export,
  middleware default, sidebar, starters, and UI caption selection. Keep `AGENTS` as the
  UI label/description mapping keyed by the constants.
- **Consumer migration:** app and package move together; no external string or route
  changes.
- **Protected invariants:** registered IDs, stream URLs, persisted `agent_id`, starter
  filtering and mode-switch behaviour stay exactly `vitess` / `advanced_mode`; package
  import remains side-effect-free.
- **Regression tests:** fresh-process import of `vitess_ai.agents` leaves core registry
  empty; existing agent registration, UI starter, mode-switch and resume tests; full
  suite.

### V2-006 — make runtime-source rationale independent of plan 03

- **Priority / phase:** P3 cleanup; last, so comment-only diffs do not obscure code
  changes.
- **Evidence and symbols:** 34 source/app lines match `03/CP*` or other execution-plan
  references. The plans are in the sibling v1 repository and are absent from an
  installed v2 package.
- **Why accidental:** chronological references make correct local code look dependent
  on a document a maintainer may not have. Some module docstrings spend more text on
  migration history than on the current contract.
- **Selected target design:** docstrings explain the current invariant and name the
  local symbol/state/tool that enforces it. Historical comparisons belong in this
  review or a versioned architecture history document, not in runtime modules.
- **Move/consolidate/delete:** edit comments/docstrings only. Preserve all rationale
  needed to understand trusted state, order, evidence, file ownership and fail-closed
  execution. Do **not** edit any `AGENT.md` or retrieval policy prompt.
- **Consumer migration:** none.
- **Protected invariants:** no executable code, model prompt, tool description,
  workflow, or public API changes.
- **Regression tests:** compile/import smoke test, rendered-prompt equality, tool-surface
  tests, and full suite; diff review confirms comment/docstring-only edits.

### CROSS-001 — reduce `CoreSettings` to values core consumes

This coordinated item is specified fully in the core review. For v2, remove only the
arguments `OPENAI_DEFAULT_MODEL`, `BLABLADOR_DEFAULT_MODEL`,
`SESSION_COOKIE_SECURE`, and `LOG_DIR` from `Config.to_core_settings()` when core
deletes those fields. Then delete v2's now-unreferenced
`Config.OPENAI_DEFAULT_MODEL`, `Config.BLABLADOR_DEFAULT_MODEL`, and `Config.LOG_DIR`
plus their fixture/environment expectations; v2 already supplies cookie security only
as the literal core-constructor argument. Keep `DEFAULT_MODEL`, which v2 does read.
Land core, chatbot, and v2 together with no compatibility shim.

### CROSS-002 — publish the core client error formatter

This coordinated core/chatbot change has no v2 migration. V2 should continue importing
only `AgentClientError`/`BaseAgentClient`; it must not add a dependency on the helper.

## Ordered roadmap

### 1. Correctness prerequisites

1. `V2-001` — native runtime injection; require the focused warning-as-error test and
   full suite to pass without the two Pydantic serialization warnings.
2. Run the unavailable PostgreSQL integration files when a service exists. This is an
   environment gate, not a reason to weaken persistence tests.

### 2. Low-risk internal simplifications

1. `V2-002` — embedding-client constructor injection.
2. `V2-003` — delete dead schema response residue and demos.
3. `V2-004` — remove direct Plotly and regenerate the lock.
4. `V2-005` — one definition for the two agent IDs.
5. `V2-006` — localise historical source comments after functional changes.

### 3. Coordinated core/API changes

1. `CROSS-001` — remove unused core settings and migrate both applications atomically.
2. `CROSS-002` — core/chatbot client-helper rename; verify v2 remains unaffected.

### 4. Rejected or deferred ideas

| Idea | Decision and reason |
|---|---|
| Replace five specialist packages with a registry/generic specialist | **Rejected.** Five explicit module/model/prompt bindings are smaller and easier to audit; shared assembly already removes measured duplication |
| Shorten or generate `AGENT.md` prompts | **Rejected.** The authored domain guidance is required behaviour; schemas do not explain physical meaning, conversation order or failure modes |
| Merge guided and sweep supervisors | **Rejected.** Confirmation and unattended execution are different interaction lifecycles and require separate threads/checkpoints |
| Merge `SimulationPlanEntry` and `InternalSimulationRequest` | **Rejected.** One is stored plan intent; one is a closed execution-boundary request |
| Collapse planned/delegated/executed order to one list | **Rejected.** Independent observations are how order drift is detected |
| Extract generic guided/batch runner | **Rejected.** Safe sharing already exists in gateway, file registration and evidence helpers; return/state semantics differ |
| Add a fallback process runner when MCP is down | **Rejected.** It creates a second execution architecture and violates fail-closed MCP-only execution |
| Restore interactive Plotly | **Rejected.** PNG is the canonical verified artifact and already covers the browser delivery contract |
| Move retrieval into core | **Rejected.** The VITESS corpus, Chroma layout and embedding provider are application policy |
| Replace RAG cache/process registration with a DI framework | **Rejected.** The existing process lifecycle is explicit; more injection would add machinery without removing request state |
| Remove Streamlit source-shape tests now | **Deferred.** Replace only with exercised component/browser tests; pure helpers alone do not prove call-site wiring |
| Add compatibility shims for cross-package changes | **Rejected.** The sibling consumers can migrate together, leaving one contract |
| Import `research/` for background sweeps | **Deferred.** Reopen only with evidence that disconnects lose real sweeps; it is a product/lifecycle feature, not a cleanup |

## Preservation gates for the later refactor

Each accepted implementation must demonstrate, not merely assert:

- exact 104-field and CLI-flag inventory;
- argument-vector construction with no shell execution outside `mcp/`;
- unchanged authored prompt content and rendered schema/tool agreement;
- guided plan → ordered delegation → confirmation → validated private state → MCP →
  evidence/artifact path;
- sweep variants → server plan → sequential gateway execution with trusted UUIDs;
- existing three-order golden tests and 32-run limit tests;
- stable upload manifest and file-ownership checks;
- retrieval tool names and graceful per-call failure;
- no core dependency on `vitess_rag`, Chroma, or VITESS schemas; and
- full v2, core and affected consumer suites.

Browser, live-model, successful retrieval-key, PostgreSQL, real SAML, and any new live
VITESS acceptance remain open until actually exercised and recorded against the exact
snapshot.
