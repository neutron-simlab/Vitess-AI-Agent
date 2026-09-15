# Plan 03 — Vitess AI Agent v2

> **Goal:** a second application on `juena-core`, carrying two agents — `vitess` (the
> guided simulator) and `advanced_mode` (the batch parameter sweep) — a FastMCP server
> for VITESS execution, and Chroma retrieval through the existing `vitess-rag`
> submodule.
>
> **Depends on:** 02, complete and its verification passed.

## Before you start

Read `README.md` and `00-BOUNDARY.md`. Plan 02 must be finished — not merely started —
because its whole purpose is to prove the boundary before a second application depends
on it.

**A fresh repository**, `vitess-ai-agent`, package `src/vitess_ai/`, starting from an
empty tree.

> **Do not branch from `feature/openwebui` or `feature/migrate-to-juena`.** Files are
> copied in deliberately, one checkpoint at a time. The debris is left behind by *not
> copying it*, which costs nothing because none of it is tracked: `git ls-files`
> returns nothing for `[Template] Praktikum 1.ipynb`, nothing for
> `src/vitess_ai/skills/` (only `__pycache__` — there is not even an `__init__.py`),
> and nothing for `.env`. (Finding 7.)

### `pyproject.toml`

```toml
requires-python = ">=3.11, <4.0"
dependencies = [
  "juena-core[ui,mcp]",        # path source below; see 01/CP6 on what the lock does not pin
  "fastmcp>=4,<5",              # current stable major used by langchain.mcp; CP0b locks the validated release
  "matplotlib", "numpy", "plotly",
  "vitess-rag",            # path dependency, the submodule
]
[tool.uv.sources]
juena-core = { path = "../juena-core" }   # D7: sibling, no remote
vitess-rag = { path = "rag/vitess-rag" }
```

**`deepagents`, `langchain` and `langgraph` are not listed** — core bounds them, and two
sets of bounds drift. This repository's committed `uv.lock` fixes the validated third-party
set. The sibling core source is identified separately by a clean tree, recorded commit SHA
and resulting image digest; see 01's dependency policy and CP6.

`>=3.11` matches core's floor and **also fixes a CI lie**:
`.github/workflows/deploy.yml:29` pins Python 3.11 while the old `pyproject.toml`
requires `>=3.13`, which means CI has never run what ships. Fixing it by making the pin
correct is better than by changing the pin.

Verify rather than assert:

```bash
uv sync --python 3.11 && uv run pytest
```

If something genuinely needs 3.13, raise the floor **and** the CI pin together, and say
in writing what needed it.

The `vitess-rag` submodule is a hard prerequisite — it is a path dependency, so both
`uv sync` and the Docker build fail without it:

```bash
git submodule update --init --recursive
```

---

## Checkpoint 0 — the schema, ported verbatim

**Decision: the six schema files are copied into `src/vitess_ai/schema/` unchanged.
They do not go into core.** They import only pydantic and each other — every import was
checked. They are VITESS physics, and core has no opinion about `VtGdeShape`.

Copy: `base.py`, `readin_module.py`, `guide_module.py`, `writeout_module.py`,
`monitor1d_module.py`, `monitor2d_module.py`.

Leave behind:

- `monitor_module.py` — twelve lines of back-compatibility re-export.
- `supervisor.py` — `SupervisorStage`, `SupervisorConfig`, `ExecutionPlan`,
  `create_routing_decision_model`. All belong to the router being replaced in CP4.
- `server.py` and `llm_models.py` — core owns both.

> **Two `SupervisorStage` enumerations exist and they disagree** (Finding 8).
> `schema/supervisor.py:9` has `WELCOME / MODULE_EXECUTION / COMPLETION / ERROR`;
> `schema/server.py:170` has `WELCOME / CONFIGURATION / EXECUTION / COMPLETION /
> ERROR`. These are two different state machines wearing one name. Port neither.

### Two additions, and they are why this is its own checkpoint

**1. `schema/__init__.py` is 0 bytes today.** Give it an explicit `__all__` naming the
five parameter models and `get_field_flag`. Everything currently imports by full path
because there is nothing else to import.

**2. The test that does not exist.** Every parameter field carries its VITESS
command-line flag in its own definition:

```python
GuideEntrWidth: Annotated[float, Field(
    default=3.0,
    description="-w [cm] Width of the guide entrance",
    json_schema_extra={"flag": "-w"},
)]
```

and `get_field_flag` returns `""` for a field that has none — so **a field without a
flag is silently dropped from the generated command**. There are 104 flag declarations
and no test that they are complete, which makes this the defect class most likely to be
present already.

> **The test must recurse, and it must not require a flag of every field.**
> `WriteoutParameters.output_flags` (`writeout_module.py:194`) and `.filter_limits`
> (`:219`) are **container fields** — they hold `VtOutputFlags` and `VtFilterLimits`,
> whose *leaves* carry the real flags. Neither container has a flag, correctly. A flat
> test over top-level fields would reject both and would be deleted within a day.

So: walk the model tree, and for each field decide which of two kinds it is —

- **a container** (its annotation is a `BaseModel` subclass) → recurse into it, require
  no flag of the container itself;
- **a leaf** (anything else) → require a non-empty `json_schema_extra["flag"]`.

Assert the **total leaf count per model** as well, so that adding a field without a flag
fails loudly rather than being skipped by a bug in the walker:

| Model | Flag declarations |
|---|---|
| `ReadInParameters` | 13 |
| `GuideParameters` | 15 |
| `WriteoutParameters` (incl. both nested models) | 31 |
| `Monitor1DParameters` | 20 |
| `Monitor2DParameters` | 25 |
| **total** | **104** |

Counted with `grep -c '"flag"'` per schema file. **A repo-wide grep returns 105** — the
extra hit is `get_field_flag`'s own `.get("flag", "")` in `base.py`, which is the reader,
not a field. An earlier draft of this plan reported 105, which is the sort of off-by-one
that makes a regression baseline fail on day one for no reason.

Treat these as a regression baseline, not a specification — if a number changes because a
real parameter was added, update it and say so.

**Done when:**

```bash
uv run pytest tests/test_schema_flags.py -q
uv run python -c "import vitess_ai.schema; print(len(vitess_ai.schema.__all__))"
```

The flag test passes for all five models — **or it fails, naming the fields**, which is
a finding worth having on day one rather than after a wrong simulation.

### What actually landed

*(Fill in after the work, including any fields the flag test caught.)*

---

## Checkpoint 1 — `generate_cli_command`, out of `mcp/`

**This is the heart of the system, and today it is in the wrong file and it is wrong.**

It lives inside `mcp/supervisor_tools.py` as an *undecorated* helper (it is not an MCP
tool at all), which means it cannot be tested without importing `fastmcp`, it is reached
two different ways with no single owner, and it reads
`global_config.VITESS_PROJECT_PATH` from module scope.

**Decision: it moves to `src/vitess_ai/cli/command.py` as a pure function.** No
`fastmcp` import, no configuration read — `project_path` becomes an argument. The MCP
server imports it. `advanced_mode` imports it. Tests import it. One implementation, one
owner.

### Three behaviour changes, all corrections

**1. A skipped module is an error, not a warning.**

Today, around lines 150–172, a module that is missing from `module_results`, carries no
`cli_parameters`, or is absent from the executable map is written to the log and then
`continue`d — and the function returns `success: True` with a **shorter pipeline**.

Worse, this field:

```python
"modules_included": [m for m in execution_order],
```

reports every module that was *requested*, including the ones that were dropped.

So: a user asks for a guide in the beamline, the guide silently vanishes from the
pipeline, and the tool reports success **with the guide listed as included**. The
simulation is physically wrong and looks right. This is the most important defect in
either repository.

After: `success: False`, naming the module. And `modules_included` reports what was
actually emitted.

**2. The thread-id-by-regex fallback goes.** Lines 100–127 scrape a UUID out of file
paths with `re.search` and log *"This may be an old thread_id from a previous session"*.
The caller always has the thread id — core's `AgentInputHandler` raises rather than
proceed without one. Delete the fallback; require the argument.

**3. The bare `except Exception` that returns `success: False` with `str(e)` goes.** Let
the caller's tool wrapper handle it, the way juena's `@tool` closures do.

### And the change that matters most: stop generating shell text

**Pydantic validates types and permitted fields. It does not make interpolated shell
text safe.** These are different problems, and the current code relies on the first for
the second.

What it does today:

- `supervisor_tools.py:352` writes a script whose shebang is `#!/bin/sh`;
- `:377` then runs it as `subprocess.run(['/bin/bash', script_path], ...)`.

So the declared interpreter is not the one used — the shebang is decorative — and every
module's parameters, plus the project path, are interpolated into that text as strings.
A filename, a path, or a string-typed parameter that a model chose can change what the
shell parses.

**Decision: build an argument vector per module and let Python connect the pipeline.**

- Each module invocation becomes a `list[str]`: `[executable, "--Z1", "--U1.0e-25", …,
  "-w3.0", …]`. No quoting rules, because nothing is ever parsed as shell.
- The pipeline is connected explicitly with `subprocess.Popen` and `stdout=` wiring, or
  run module-by-module through intermediate files. **No `shell=True`, no `/bin/bash`, no
  generated script.**
- The post-processing — removing `result.txt`, concatenating the log files, cleaning up —
  is done in Python with `pathlib` and `glob`, which is what those four lines were
  emulating anyway.
- **A rendered command string is still produced, and it is still shown to the user** —
  as a display and debugging artifact. It is what the UI prints and what a physicist
  checks. It is simply never the thing that executes.

### The inputs are shell-shaped too, and that is the harder half

Emitting a vector does not help while everything feeding it is a shell string. Three
sources, all verified:

**1. Executables carry a shell variable.** `catalog.py:51-119` stores `$V/read_in`,
`$V/guide_parallel`, `$V/writeout`, `$V/monitor1D`, `$V/monitor2D`. `$V` expands in a
shell and expands to **nothing** in an `execve`.

> **Store the basename** — `read_in`, `guide_parallel` — and resolve it at execution time
> against a single trusted `VITESS_MODULES_PATH` from settings. Resolve, then assert the
> result is inside that directory and is executable. A catalog value is not a path, and
> it should not look like one.

**2. The converters return one concatenated string.** `guide_params_to_cli`
(`tools/guide.py:36`) ends:

```python
return " ".join([f"{flag}{param}" for flag, param in cli_params])
```

Flag and value are glued (`-w3.0`), then space-joined. **That string cannot be safely
split back into arguments** — a shape filename containing a space is indistinguishable
from two arguments, and there is no quoting to recover.

> **Change the converters to return `list[str]`**, or skip them and build arguments
> directly from the validated Pydantic object using `get_field_flag`. The five
> `*_params_to_cli` functions are the only callers, and they are small.

**3. The log prefix is a shell variable.** The ordering parameter `--L${L}0{i}` — and the
post-processing that globs `${L}??` and deletes `${L}*` — depend on `$L` being set by the
surrounding shell. There is no surrounding shell any more.

> **Generate a concrete log prefix per simulation**, derived from `simulation_run_id`,
> validated as an identifier, and passed as a literal. The glob-and-delete becomes
> `pathlib` operations scoped to that run's own directory — which also removes a
> `rm -f ${L}*` whose blast radius depended on a variable nobody set deliberately.

### Success is every process exiting zero

A pipeline reports success only if **every** module exited zero. A middle module failing
while a later one still writes an output file must not read as a successful run — that is
the same fail-closed principle as the dropped-module correction above, applied to
execution rather than generation.

Tests: an early module failing, a **middle** module failing, and a timeout — the last
asserting that the surviving child processes are terminated rather than left running.

**If a shell boundary turns out to be genuinely unavoidable** (a VITESS module that only
works when invoked through one), treat it as an interim constraint and say so in
writing: every dynamic token quoted with `shlex.quote`, every path resolved and asserted
to be under the project root, and tests covering spaces, semicolons, `$(…)`, leading
dashes, and `../`. That is a weaker guarantee than an argument vector, not an equivalent
one.

This matters with a single local user because the *model* supplies the values, and the
container has the project volume, the Blablador key, and a network.

### What tests it

**A golden test over the argument vectors.** A fixed `module_results` covering all five
modules, a fixed project path and a fixed `simulation_run_id`, asserting the **exact list
of lists** — every flag, every value, the resolved absolute executable, and the `--N{i}`
ordering parameter with its **concrete** log prefix. Lists compare cleanly and a diff
points at the element that changed, which a 400-character command string does not.

**Assert no element contains `$`.** A single test over the whole vector catches `$V` and
`${L}` surviving anywhere — the two places this checkpoint is most likely to be done
halfway.

Then a second, smaller golden test on the **rendered display string**, so the thing shown
to the user stays stable — marked clearly as display-only.

Plus one test per failure mode, and the injection cases as unit tests over the vector
builder: a filename containing a space, a `;`, a `$(…)`, a leading `-`, and a `../`.
Each must appear as **one argument element**, or be rejected as an invalid identifier —
never split, never resolved outside the project root.

> **`tests/unit/test_mcp_tools/test_supervisor_tools.py::test_missing_modules_handling`
> and `::test_empty_module_results` are ported with their assertions inverted.** They
> currently assert the bug — the first one asserts `result["success"] is True` with the
> comment "Should still generate command for available modules."

**Done when:**

```bash
uv run pytest tests/test_cli_command.py -q
uv run python -c "import vitess_ai.cli.command"     # works with no fastmcp installed
```

### What actually landed

*(Fill in after the work.)*

---

## Checkpoint 2 — the catalog, as data

There is an apparent conflict here, and resolving it correctly matters.

juena-chatbot's rule is explicit: *"There is no specialist registry, capability
framework, filesystem discovery, or import discovery. Adding a specialist requires a
package, a builder import, and one explicit entry."* Vitess's `modules/catalog.py` is
exactly the registry that rule forbids.

**They are at different layers.** juena's rule is about **agents**. `catalog.py` is
about **VITESS physics modules**, and its rows carry `cli_executable`,
`upload_schema_sidebar`, `validation_tool_patterns` and `order` — data that the command
generator, the file store, the configuration endpoint and the sidebar all read. That is
a data table, and it earns its keep: without it, each of those four callers grows its
own copy. **Two such copies already exist** — `FALLBACK_MODULE_EXECUTABLES` in
`mcp/supervisor_tools.py:49` and `FALLBACK_MODULE_TYPES` in `server/file_storage.py:22`.

**The one field that crosses layers is `agent_class`.** Because of it, `catalog.py`
imports `base_agent`, which imports LangChain — so the FastMCP server, which only wants
a five-entry `{module: executable}` mapping, drags in the whole agent framework. *That*
is why the fallback tables exist.

### Decision

- **`catalog.py` becomes pure data**: `name`, `display_name`, `description`, `order`,
  `cli_executable`, `upload_schema_sidebar`. It imports pydantic and nothing else.
  `agent_class`, `tool_factory` and `validation_tool_patterns` are removed.
- **The five module specialists are built by five explicit builders** —
  `build_readin_specialist()`, `build_guide_specialist()`, and so on — imported and
  listed **one line each** in `compile_module_specialists()`. juena's rule, unchanged.
- Each builder reads its own catalog row by name for the executable and the upload
  schema. A missing row raises.
- **Both fallback tables are deleted.** A catalog that cannot be loaded is a broken
  install, not a condition to degrade through.

**Done when:**

```bash
uv run python -c "import vitess_ai.modules.catalog, sys; \
  print('langchain' in sys.modules, 'deepagents' in sys.modules)"
uv run pytest tests/test_catalog.py -q
```

prints `False False`.

### Two independent properties, not one `kind`

A first draft gave each row a single `kind: Literal["simulation", "upload"]`. That is not
enough, because two *independent* questions are being asked of every row:

- **Does it run a VITESS binary?** `readin`, `guide`, `writeout`, `monitor1d`,
  `monitor2d` do. `instrument` (`catalog.py:134`, *"Upload instrument file used by
  read-in module (sInstrInfIn)"*) does not — it is upload-only and correctly has no
  executable.
- **Does it accept an uploaded file?** `readin`, `guide` and `instrument` do.
  `writeout`, `monitor1d` and `monitor2d` **do not** — see below.

They cross: `instrument` uploads without executing, and `writeout` executes without
uploading. One enum cannot express that. So each row carries:

```python
cli_executable: str | None          # a BASENAME -- "read_in", never "$V/read_in"
accepts_upload: UploadSchema | None # None means: nothing to upload
```

**The executable is a basename, not a path** (CP1). Today the catalog stores
`$V/read_in` — a shell variable that expands to nothing outside a shell. It becomes
`read_in`, resolved at execution time against `VITESS_MODULES_PATH` and asserted to be
inside it. A test asserts **no catalog value contains `/` or `$`.**

and the test asserts an executable **only where `cli_executable is not None` is expected**
— a blanket assertion would fail on `instrument` and get weakened to nothing within a day.

### The three `path_only` rows leave the catalog's upload schema entirely

`writeout`, `monitor1d` and `monitor2d` are declared as uploads
(`catalog.py:86-126`) with `mode: "path_only"`. **They upload nothing.** Each one sets an
output filename — and every one of those filenames is *already* a declared parameter with
its own CLI flag:

| Sidebar row | The field it duplicates | Schema default | Sidebar default |
|---|---|---|---|
| `writeout` | `WriteoutParameters.sOutFileName` (`-A`) | `output.dat` | **`output.out`** |
| `monitor1d` | `Monitor1DParameters.fMonitorFilename` (`-O`) | `monitor1D.dat` | `monitor1D.dat` |
| `monitor2d` | `Monitor2DParameters.fMonitorFilename` (`-O`) | `monitor2D.dat` | `monitor2D.dat` |

**The writeout row already disagrees with its own schema** — `output.out` against
`output.dat`. Two defaults for one value, in two files, with nothing to make them agree.
That divergence is the argument, not a hypothetical one.

They were in the sidebar because the sidebar was the only per-module surface that
existed, not because anything was uploaded.

**Decision: delete the three `path_only` entries.** The output filename is collected the
way every other parameter is — by the module specialist, conversationally, with the
schema default proposed. It then lives in exactly one place, is validated by the model it
belongs to, appears in the specialist's summary, and reaches the command through
`get_field_flag` like every other field.

This halves the upload UI and removes a whole UI mode (`_render_path_upload_mode`,
`app/sidebar.py:511`).

**Done when** `kind`-style assertions pass, the catalog has exactly **three**
upload-accepting rows (`readin`, `guide`, `instrument`), and a test asserts that **no
catalog row declares a default filename** — the schema owns those now, and a second copy
is the bug being removed.

### What actually landed

*(Fill in after the work.)*

---

## Checkpoint 3 — the FastMCP server and how the agent reaches it

**Decision: HTTP, from an internal Compose service. Not stdio, and not a host process.**

> **Corrected after review.** An earlier draft ran this on the host, copying
> `./juena rag-up`. **That analogy is wrong and it was the worst error in these plans.**
> juena-rag communicates *only over HTTP* — a query in, results out. The VITESS MCP
> server must also **share files** with the app: the app accepts uploads and renders
> artifacts, while the MCP service reads those uploads and writes simulation outputs.
> A host process cannot see the app container's named Docker volume, and
> `/data/projects/<thread>/…` means nothing outside the container.

**Not stdio.** A stdio target spawns a subprocess per client — so a threaded server means
several copies of a process that runs VITESS binaries into a shared project directory. And stdio makes standard output the transport: one stray
`print` inside `run_simulation` corrupts the protocol, silently.

**The local topology:**

```text
browser on your PC
      |  http://127.0.0.1:<ui-port>     (published, loopback only)
      v
 app container  ────────────────  postgres container
      |
      |  http://vitess-mcp:9005/mcp     (internal network, not published)
      v
 vitess-mcp container
      |
      v
  /data/projects                        (named volume, mounted in BOTH)
```

Properties, each load-bearing:

- **Only the Streamlit UI port is published**, bound to `127.0.0.1`. The API binds
  container loopback and is not published; the MCP port is reachable only on the Compose
  network. MCP has no authentication, so it must not face the host network, let alone the
  office one.
- **App and MCP mount the same named volume at exactly `/data/projects`.** Same path in
  both, so a path written by one is meaningful to the other (00, decision 11).
- **One image, two commands.** The MCP service needs the VITESS build; the app needs the
  Python environment; building one image and running it with different commands is simpler
  than keeping two in step, and guarantees the file layouts match.

  > **So the app container does contain the VITESS build** — one image means one
  > filesystem. The invariant is therefore not *"the app image has no VITESS"* but:
  >
  > **application code never executes VITESS directly; every execution goes through the
  > internal MCP service.**
  >
  > That is a code rule, enforced by `vitess_ai.run` being the sole MCP execution gateway
  > (CP5) and by `cli/command.py` building argument vectors without running them. An earlier revision
  > stated the invariant as a property of the image, which contradicted this decision and
  > would have been enforced by nothing.
- **Postgres is in the same Compose project**, so `docker compose up` starts all three.
- **`./vitess mcp-up` does not exist.** `up`, `down`, `logs` and `ps` already cover it.

**Health is an explicit route, not an inference.** Add `GET /health` to the FastMCP app
and use it in the Compose health check. The earlier draft's
`curl /mcp -H 'Accept: text/event-stream'` tests that *something* answers on a port —
it does not test that VITESS is present or that the project volume is writable. A real
health route can check both.

**Delete the drift while you are here:** `docker-compose.yml:62-65` and `:73-76` still
export `READIN_MCP_PATH`, `GUIDE_MCP_PATH`, `WRITEOUT_MCP_PATH`, `MONITOR_MCP_PATH` and
`FILTER_MCP_PATH` and publish ports 9001–9004 for servers that were deleted when
everything collapsed to one server. The README repeats the claim. Remove both.

### Connection, and what happens when MCP is down

The earlier draft contradicted itself here: it borrowed Context7's "return `None` on
discovery failure" while also promising that tools stay bound and recover. **Both cannot
be true** — tools that were never registered cannot come back.

They are different situations, and the difference is deliberate:

| | Context7 in juena-chatbot | VITESS MCP in v2 |
|---|---|---|
| If unavailable | the app is still useful | **there is no product** |
| On discovery failure | return `None`, do not offer the tools | **fail construction loudly** |
| Prompt says | nothing about a capability that is absent | the capability exists; it may be temporarily unreachable |

> **And revision 2's answer — "register the tools anyway" — is not implementable.**
> Discovery must reach the server to obtain tool *schemas*. There is nothing to register
> when it fails, short of hand-writing four static proxies and keeping them in step with
> the server by hand — a real option, and not worth it for a local stack.

So the contract is **make the dependency available rather than tolerate its absence**:

1. **MCP is healthy before the agent is constructed.** Compose `depends_on` with
   `condition: service_healthy` against the MCP `/health` route, and the agent factory
   probes once before building.
2. **Discovery succeeds, or construction fails loudly.** No half-built graph.
3. **A failed construction is never cached.** `get_agent` caches `(instance, graph)` for
   the process lifetime; caching a failure makes the outage outlive the outage.
4. **Later connection failures become a typed unavailable result** in the single
   `vitess_ai.run` MCP gateway, then surface through either caller. A simulation that did
   not run must never read as one that ran and produced nothing.
5. **Recovery needs no restart** — confirmed by CP0b's reconnection check.

> **This uses LangChain's built-in MCP support, not `langchain-mcp-adapters`.**
> That package is retired; LangChain 1.4.0 ships MCP in `langchain.mcp`. Discovery is
> `async with MCPAdapter(url) as adapter: await adapter.list_tools()`. VITESS has one MCP
> server, so the deployed integration passes its HTTP URL directly and preserves its four
> server tool names. A future multi-server target would use `{"mcpServers": {...}}` with
> transport inferred. The namespace is **beta** (`LangChainBetaWarning`). Every import of
> it lives in `juena_core.mcp` (01/CP5), so v2 never imports it directly.

### What the server keeps

Four tools: `run_simulation`, `inspect_thread_folders`, `generate_monitor1d_plot`,
`generate_monitor2d_plot`. `generate_cli_command` is no longer in this file at all
(CP1).

**`mcp/utils.py` is deleted.** Its `is_mcp_tool` is wrong three ways — it omits
`generate_monitor2d_plot`, it lists `generate_cli_command` which is undecorated, and it
lists `prepare_simulation` which does not exist anywhere. Core's streaming rules do not
branch on where a tool came from, so nothing needs it.

**`advanced_mode`'s `.fn()` calls go.** `agents/advanced_mode/tools.py:209` and `:488`
reach inside the FastMCP decorator to call the undecorated function in-process
(Finding 4). That works today and is a private detail — but more importantly it lets the
batch path and the interactive path drift, which is the exact failure CP1 exists to
prevent. They become calls to `vitess_ai.cli.command` and a small `vitess_ai.run`
module.

**Done when:**

```bash
./vitess up
docker compose exec vitess-app curl -fsS http://vitess-mcp:9005/health && echo healthy

docker compose exec vitess-app python - <<'PY'
import asyncio
from langchain.mcp import MCPAdapter          # langchain[mcp]; beta namespace

async def main():
    # One server: use the URL target so discovery keeps the server's four tool names.
    async with MCPAdapter("http://vitess-mcp:9005/mcp") as adapter:
        return sorted(t.name for t in await adapter.list_tools())

print(asyncio.run(main()))
PY

# and the MCP port must NOT be reachable from the host:
curl -fsS --max-time 2 http://127.0.0.1:9005/health && echo "LEAKED" && exit 1
```

The listing prints exactly the four tool names, **from inside the app container** —
which is the only place that matters — and the host cannot reach the MCP port at all.

### What actually landed

*(Fill in after the work.)*

---

## Checkpoint 3a — the file and evidence bridge

This checkpoint did not exist in the first draft, and its absence was the review's
sharpest finding: `SpecialistOutcomeMiddleware` was to read an `execution_events`
channel that **nothing was specified to write**, while the old `tool_wrapper.py` that
might have was being dropped.

**Two verified facts force the design:**

- `ArtifactStore` holds `_pending_message` and `_pending_events` as ordinary Python
  dictionaries (`juena/sandbox/artifacts.py:157-158`), drained by `drain_events()` at
  `:387`. **An MCP container cannot enqueue into the API process's memory.** A shared
  volume shares files, not objects.
- The `<verified_by_server>` block is only worth its name if the evidence is the
  server's, not the model's — so whatever crosses the boundary must be *validated on
  arrival*, never trusted.

### The contract

### First, two identifiers that are not the same identifier

`server/agent/input_handler.py:52` already has a `run_id`: `run_id = run_id or uuid4()`,
one per **graph invocation**, passed as `RunnableConfig(run_id=...)`. One user turn, one
id. But `advanced_mode` runs a sweep — many simulations in one turn — so that id cannot
name an output directory, and using it would put every run of a sweep in one folder.

- **`graph_run_id`** — core's, one per invocation. Unchanged.
- **`simulation_run_id`** — generated by trusted application or MCP code, one per VITESS
  execution. It names `outputs/<simulation_run_id>/` and it seeds the log prefix (CP1).

Neither is ever supplied by the model. The API injects `thread_id`; the façade reads it
through the public `request.runtime.execution_info.thread_id` API. The principal and
other typed application values remain in `request.runtime.context`. Ownership
identifiers are **absent from the application façade's model-visible `args_schema`**.
The raw MCP tools are never bound to the model; the façade below is the boundary that
makes this true.

**0. The state channel is declared, with a reducer.** `execution_events` is a
`PrivateStateAttr` — so it never crosses a delegation boundary as ordinary state — with a
**list reducer**, because each module in a pipeline appends its own entry. Declaring it
without a reducer means the last write wins and a five-module run reports one module.

**1. MCP writes files** beneath `/data/projects/<thread_id>/outputs/<simulation_run_id>/`.
Both are validated as identifiers — a UUID or rejected — and never joined into a path
unchecked.

**2. MCP returns structured metadata** from the tool call, via MCP's
**`structuredContent`**, not as prose in the text block. The text block is written for a
model to read; the evidence must not be recovered by parsing it. If the server cannot
populate `structuredContent`, the payload is JSON in a single content block and the
parser is strict — but prefer the typed channel.

```jsonc
{
  "simulation_run_id": "…",
  "modules": [
    {"name": "readin", "executable": "/vitess/MODULES/read_in",   // resolved, not "$V/..."
     "exit_code": 0, "started_at": "…", "ended_at": "…",
     "stdout_tail": "…", "stderr_tail": "…"}
  ],
  "files": [
    {"path": "monitor1D.dat", "kind": "monitor_data", "bytes": 20480}
  ]
}
```

`path` is **relative to the run root**, so the app resolves it under its own mount rather
than trusting an absolute path from another container. `stdout_tail`/`stderr_tail` are
bounded — a failing VITESS module can produce megabytes, and none of it should reach a
model's context.

**3. The model never calls an MCP tool directly. It calls an application façade.**

An earlier revision said trusted fields would be "omitted from the exposed tool schema"
while a middleware inserted them. **That conflates two different things.** Middleware can
rewrite a call on its way out; it cannot remove a field from the schema the MCP server
advertises, and it is that advertised schema the model sees and fills in. Leaving
`thread_id` or `module_results` visible and hoping to overwrite them is a guard that
depends on the model not being creative.

So: **the raw MCP tools are never bound to the model.** For each one, v2 defines a
LangChain façade tool whose `args_schema` contains only what the model is actually
entitled to decide. The façade:

1. **Exposes model-authorised arguments only** — for `run_simulation`, that is nothing at
   all beyond an optional `run_name`. There is no `thread_id`, no `simulation_run_id`, no
   `module_results`, no `run_specs`.
2. **Reads trusted data from the correct `ToolRuntime` channels** — `thread_id` from
   `runtime.execution_info`, the principal from the typed `runtime.context`, and
   validated `module_results` from `runtime.state`, the channel CP4 establishes.
3. **Generates `simulation_run_id`** itself.
4. **Calls the non-model `vitess_ai.run` gateway**, which invokes the underlying MCP tool
   with the full trusted argument set and is the only application module allowed to do so.
5. **Receives typed `ExecutionEvidence` from the gateway.** The gateway validates
   `message.artifact["structured_content"]` — an `MCPToolArtifact` carrying the server's
   `structuredContent` — before returning. A payload that fails validation becomes a
   *failed execution*, never a silent skip, for guided and batch callers alike.
6. **Returns `Command(update=...)`** with the tool message, the `execution_events`
   entries and the artifact state, in one atomic write — the pattern `tools/research.py`
   already uses.

Cross-cutting behaviour that is genuinely about *every model tool call* — recording
timings and uniform diagnostics — belongs in a `@wrap_tool_call` middleware instead.
Transport-error normalization lives lower, in `vitess_ai.run`, because the unattended
batch path calls that gateway without passing through model middleware:

```python
@wrap_tool_call
async def vitess_execution(request: ToolCallRequest, handler) -> ToolMessage | Command:
    ...  # request.tool_call["name"], request.tool_call["args"], request.runtime
```

**The façade is the security boundary; the middleware is the cross-cutting concern.**
Putting the trusted-field logic in the middleware, as an earlier revision did, means the
guarantee lives somewhere the schema does not reflect.

> **03/CP3a proves this**, not a code review: once the façades exist, it inspects each
> `args_schema` and asserts `thread_id`, `simulation_run_id`, `module_results` and
> `run_specs` are all absent. CP0b records this as deliberately deferred; it cannot
> inspect an interface that has not been built.

**4. The app registers artifacts** from the `files` list, resolving each relative path
under the run root and confirming it exists before registering. A file the metadata
claims but the volume does not have is a failure, not a missing download button.

**5. Plots are PNG artifacts.** `generate_monitor1d_plot` / `2d` render to PNG and return
a file descriptor like any other output; the app registers them with `ArtifactStore` and
they arrive in the chat exactly as juena's sandbox plots do. The existing Plotly-JSON
code becomes the renderer's input, not the delivered payload. Interactive Plotly is a
separate contract, later, if it is wanted.

**6. Durable state lives in Postgres or on the volume.** Nothing that must survive a
restart lives only in a pending queue.

**7. Something must actually write the final block, and today nothing would.**
`SpecialistOutcomeMiddleware` is installed at `specialist_runtime.py:249`, **inside
`build_specialist_middleware`** — it runs within specialists. In juena-chatbot every
command runs inside a specialist, so that is sufficient there. **v2 calls
`run_simulation` from the root supervisor**, where that middleware is not installed and
never runs.

So v2's supervisor stack gets two middlewares spliced through
`build_supervisor_middleware(extra=...)` (00, decision 15):

- **`ExecutionEvidenceMiddleware`** — reads `execution_events` and appends the
  server-authored `<verified_by_server>` block to the **root** response. Core provides it,
  factored out of the composition logic `SpecialistOutcomeMiddleware` already has, rather
  than written twice.
- **`ArtifactMessageMiddleware`** — attaches the artifact references registered in step 4.
  It moves into core in 01/CP2; it is already generic, and it was left in juena's sandbox
  package only because that is where it happened to live.

Without these two lines, everything else in this checkpoint still runs and the answer
still arrives — with no evidence block and no download button. That is the failure mode
worth naming, because it looks like success.

**Done when**, with the stack up:

```bash
./vitess test -k evidence
```

passes unit tests over the translation step (valid payload → events; malformed payload →
a failed execution, not a skip; a claimed-but-absent file → failure), **and** a manual
run shows a `monitor1D.dat` written by the MCP container appearing as a downloadable
artifact in the browser, with its exit code in the `<verified_by_server>` block.

### What actually landed

*(Fill in after the work.)*

---

## Checkpoint 4 — the simulator, rebuilt

**Rebuild on the juena pattern. No legacy fallback.**

The decision taken was to keep the *agent* — a guided single simulation with five module
specialists — not necessarily its implementation. Here is the case, and the case
against.

### For rebuilding

- `supervisor.py` is 1,375 lines: seven supervisor nodes, N module nodes, six routing
  functions. What those routing functions do is *pick a subagent, run it, come back,
  decide what is next* — which is `SubAgentMiddleware` plus `create_agent`. The three
  nodes that are not routing (`_prepare_simulation_node`, `_run_simulation_node`,
  `_generate_plots_node`) are three tool calls wearing graph nodes.
- It is built on `UnifiedState(MessagesState)`, a TypedDict with eighteen custom
  channels and **seven methods that use attribute access** (`self.current_module`) on a
  type whose instances are plain dictionaries. Those methods are unreachable. Porting
  means porting that, or rewriting the state — at which point the routing rewrite is
  most of what remains.
- Swapping `InMemorySaver` for the Postgres checkpointer is not a swap.
  `restart_with_new_config(clear_state=True)` replaces `self.memory` with a fresh saver,
  which is meaningless against a shared Postgres checkpointer — and is also the
  mechanism that makes `restart_agent` wipe conversation state for **every** user. Every
  path that calls it has to go.
- **The expensive, irreplaceable part is not the router.** It is `prompts/` (1,486 lines
  across six files) and `tools/` (1,357 lines), and **both port almost verbatim**.
  `tools/*.py` are already `@tool`-decorated functions over the pydantic models and
  `get_field_flag`, which is close to juena's `build_*_tools(deps)` closure convention;
  the change is wrapping them in factories so the thread id is bound rather than
  resolved from a module-level global.

### Against — and this is the real risk

The hand-rolled router encodes two things a free-form supervisor will not respect on its
own: the **execution order** (`readin → guide → writeout → monitor1d → monitor2d`) and
**resumption** after an interrupt (`current_active_module`). Losing them means a
simulator that sometimes configures the monitor before the guide.

### So the ordering goes somewhere explicit

Not graph edges, and not the prompt alone. **A tool.**

- `plan_simulation()` returns the execution order from the catalog. `SUPERVISOR.md`
  requires it be called before any module is delegated.
- `run_simulation` already rejects a `module_results` containing a validation-error
  payload. Extend it to reject a set that does not cover the planned order.

**The order becomes a checked precondition rather than a graph shape** — which is also
what makes it testable.

> **But a completeness check is not an order check**, and the earlier draft conflated
> them. Asserting that all five modules have results proves the *set*, not the
> *sequence*. A supervisor that configured the monitor first and the guide last would
> pass it.

**So the test records events and asserts three orders agree.** Run the graph against a
scripted model, capture the delegation and tool events, and assert:

1. the order `plan_simulation` returned;
2. the order specialists were actually delegated to;
3. the order modules appear in the generated argument vectors;

plus **fail-closed behaviour** when a required module is absent, and when one is
delegated twice.

Three lists, compared element by element. That is what "the simulator holds its order"
means, and nothing weaker demonstrates it.

### No rollback, deliberately

An earlier draft kept the old graph registered as `simulator_legacy`, on the grounds
that `register_agent_factory` takes any compiled graph and the option was free.

**It is not free.** It would bring back the process-global registry, `InMemorySaver`, the
`restart_with_new_config` path that wipes state, and the old MCP behaviour — and a
fallback whose persistence model differs from the real one is not a fallback, it is a
second architecture with a reassuring name. It would also become the thing that
"defines" the contract the moment anyone used it.

**If the rebuild stalls, that is a signal to fix the rebuild.** The golden order test
above is the gate; ship when it passes.

### What lands

- **`agents/vitess_agent.py`** — the supervisor, assembled with
  `juena_core.build_supervisor_middleware`, `with_delegation_boundary`,
  `get_checkpointer()`, `get_store()` and `RuntimeModelContext`. `SUPERVISOR.md` becomes
  a packaged markdown resource loaded with core's `load_markdown`; the prompts stop
  being Python string constants.
- **`agents/specialists/{readin,guide,writeout,monitor1d,monitor2d}/`** — five packages,
  each with `agent.py`, `tools.py` and `AGENT.md`, each returning a `CompiledSubAgent`
  dictionary `{"name", "description", "runnable"}` with
  `response_format=ToolStrategy(SpecialistReport)`.
- **`schema/module_result.py` and v2's own delegation boundary** — see below. Without
  them the specialists validate parameters that reach nothing.
- `compile_module_specialists()` with five explicit entries.
- One line at the bottom of the agent module:
  `register_agent_factory("vitess", create_vitess_agent, set_as_default=True)`.
- One line in `vitess_ai/server/service.py`:
  `import vitess_ai.agents.vitess_agent  # noqa: F401` — **without it every route
  404s**, because the process serving the API is not always `main.py`.

### The typed handoff, without which none of this works

`SpecialistReport` is prose — `status`, `finding`, `evidence`, `actions`, `limitations`.
And core's delegation boundary (`agents/delegation.py:47-58`) carries exactly `messages`
and `files`, both directions. So once a guide specialist has validated a
`GuideParameters`, **there is no typed route for that object to reach the command
builder**. The only remaining route would be the model retyping the numbers into
`run_simulation`'s arguments — the model-authored path CP1 exists to close.

Dropping both old `ModuleResult` definitions (CP0) is right. Leaving nothing in their
place is not. So (00, decision 14):

```python
# vitess_ai/schema/module_result.py
class ModuleConfigurationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    module: str
    validated_at: datetime
    parameters: dict[str, Any]     # dumped from the module's own Pydantic model
    schema_version: str
```

- **The validation tool writes it**, returning `Command(update={"module_results": {...}})`
  — the mechanism `tools/research.py` already uses to write state atomically with a tool
  result. **The tool writes it, not the model**, which is the whole point.
- **`module_results` is a state channel with a merge reducer** keyed by module name, so
  re-validating one module replaces its own entry and disturbs nothing else.
- **v2's delegation boundary is `with_delegation_boundary` plus one field.** Inbound
  unchanged. Outbound returns `messages`, `findings_delta`, **and only the
  `module_results` entries this specialist validated** — a delta, for the same reason
  `findings_delta` exists: a subagent must not rewrite results it merely inherited.
- **`run_simulation` reads the channel through `ToolRuntime`**, never from arguments. The
  model says *run the simulation*; it does not say *with these numbers*.

This is also what makes the completeness precondition real: `run_simulation` compares the
channel against the planned order, and **both sides are server-owned**.

### Trusted runtime channels, not environment variables

Everything the graph needs to know about *where it is* travels through the trusted
invocation, in explicit channels. `RunnableConfig.configurable` carries the checkpoint
key, exposed to tools and middleware through the public
`runtime.execution_info.thread_id` API. `RuntimeModelContext` carries the project root,
the principal and model-selection fields. It may mirror `thread_id` and `run_id` while
juena-chatbot is cut over, but new application façades read execution identity from
`runtime.execution_info`.

- **The model never supplies an ownership identifier.** A `thread_id` the model can
  choose is an ownership check the model controls. The old code read the thread id from
  a process environment variable and, failing that, scraped a UUID out of file paths
  (CP1) — both are gone.
- **`advanced_mode`'s `FilesystemBackend` gets a run- or thread-scoped directory**, not
  the whole configured project root. Today it is handed the root, which means one
  conversation can read another's files. With one user that is not a privacy problem;
  it is still a correctness one, because the model will find and cite the wrong run.
- **`agent_id` is checked on resume** (00, decision 13). `vitess` and `advanced_mode`
  both use core's `/{agent_id}/stream`, and a thread must not resume under the other
  graph.

### Dropped

`supervisor.py` · `state.py` · `base_agent.py` · `tool_wrapper.py` ·
`middleware.py`'s `DynamicModelMiddleware` (core has `RuntimeModelMiddleware`) ·
`core/registry.py` · `server/agent_registry.py` · `server/module_tracker.py` ·
`server/streaming/**` · `server/utils.py` · `server/errors.py` · `clients/client.py` ·
`core/llms_providers.py` · `core/log.py` · `mcp/utils.py`

And **`server/config_endpoints.py`** — `PUT /config/vitess` mutates process-global
VITESS paths for every user, unauthenticated, and reinitialises the file storage service
underneath anyone mid-simulation. Those paths become deployment configuration.

**Done when** one guided simulation completes end to end in the UI, with `./vitess up`:
the supervisor calls `plan_simulation`, delegates to all five module specialists **in
order**, builds the argument vectors, executes them, and the result arrives with a
`<verified_by_server>` block whose execution line was read from the MCP exit code and
**not** from anything the model wrote — with the three-order golden test passing.

### What actually landed

*(Fill in after the work — including whether the rebuild held the execution order, and
what the three-order test had to be taught before it did.)*

---

## Checkpoint 5 — advanced_mode

**The graph assembly is close to a port. The data path is not** — see *the batch path
needs its own typed state* below, which is the substance of this checkpoint.

`agents/advanced_mode/agent.py` already calls `create_deep_agent(name=, model=, tools=,
middleware=, subagents=, backend=, checkpointer=, system_prompt=)`. Whether the current
deepagents release still accepts all of those — and whether the subagent dictionary's
`middleware` key still behaves — is one of **01/CP0b**'s ten checks, answered against
the validated set rather than assumed here.

Changes:

- `DynamicModelMiddleware` → core's `RuntimeModelMiddleware`.
- `InMemorySaver` → `get_checkpointer()`, and `restart_with_new_config` goes with it.
- `_build_module_subagents()` stops reading `module.tool_factory` from the catalog
  (removed in CP2) and calls the five specialist builders instead — **the same five as
  `vitess`**, compiled again for this graph. juena already does a deliberate double
  compile and documents why; this is the same shape.
- `tools.py`'s two `from vitess_ai.mcp import supervisor_tools` blocks become imports of
  `vitess_ai.cli.command` and `vitess_ai.run` (CP3).
- `prompts.py` — 364 lines, the five-phase sweep prompt, the best-written prompt in the
  project — ports verbatim into `AGENT.md`.
- `register_agent_factory("advanced_mode", create_advanced_mode_agent)` — **no
  `set_as_default`**.

### It is not a straight port: the batch path needs its own typed state

CP4's `module_results` channel holds **one** validated configuration per module. A sweep
needs *N* per module — that is what a sweep is. And the existing batch tool takes the
whole thing from the model:

```python
@tool
async def run_batch_from_matrix(
    thread_id: str | None = None,
    filename: str = "simulation_matrix.json",
    execution_order: list[str] | None = None,
    execute: bool = True,
    run_specs: list[dict[str, Any]] | None = None,   # run_name + module_results, model-authored
) -> dict[str, Any]:
```

(`agents/advanced_mode/tools.py:458`.) So `advanced_mode` would still reach execution
through model-authored `module_results` — reopening, for the batch path, exactly what CP1
and CP4 close for the single-simulation path. **Closing it in one agent and leaving it
open in the other is worse than not closing it, because the fix looks done.**

So the batch path gets its own authoritative channel, shaped like CP4's:

```python
class SimulationPlanEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_name: str                                    # human-readable, model-chosen, NOT an id
    simulation_run_id: UUID                          # trusted, server-generated
    modules: dict[str, ModuleConfigurationResult]    # one validated config per module

# state channel: simulation_plan: list[SimulationPlanEntry]
```

- **A validation tool writes each entry**, via `Command(update=...)`, exactly as CP4 does
  for the single case. The module subagents already validate per-module parameters; the
  sweep adds only *which combinations*.
- **`write_simulation_matrix` expands the sweep** — Cartesian or paired, per the
  five-phase prompt — and emits `simulation_plan` entries. The **matrix file on disk
  becomes a rendered artifact**, like the command string in CP1: readable, checkable,
  never the thing that executes.
- **`run_batch_from_matrix` reads `simulation_plan` through `ToolRuntime`.** Its
  `run_specs` and `module_results` arguments are **deleted, not validated**.
- **`run_name` stays separate from `simulation_run_id`.** The model may name a run
  *"m=3 guide, 2 Å"*; it may not choose the identifier that becomes a directory.

### `vitess_ai.run` is the single MCP execution gateway

CP3 replaces `advanced_mode`'s `.fn()` calls with `vitess_ai.cli.command` and
`vitess_ai.run`. **`vitess_ai.run` goes through the MCP client** — it does not execute
VITESS in-process.

If it executed locally, `advanced_mode` would bypass FastMCP entirely, and with it the
health contract, the shared-volume path discipline, the `structured_content` evidence and
the façade of CP3a.

**And it would do so silently**, because the one-image decision (CP3) means the binaries
*are* present in the app container. Nothing would fail; the sweeps would simply stop being
verifiable. So the guard is a test rather than an absent file: **no module outside the MCP
server imports `subprocess`**, asserted the same way as the import-direction rule.

`vitess_ai.run` is a non-model application service over the discovered raw MCP tools. It
accepts only an internal typed request assembled from trusted state, normalizes transport
failures, validates the returned `MCPToolArtifact`, and returns typed execution evidence.
It is not registered as a LangChain tool and it never reads model-authored dictionaries.

The guided agent's model-safe façade reads `ToolRuntime`, constructs that internal request
and calls `vitess_ai.run`. `run_batch_from_matrix` also reads its own `ToolRuntime`, then
calls the same gateway for each server-authored `simulation_plan` entry. Do not invoke one
LangChain `BaseTool` programmatically from another: injected `ToolRuntime` belongs at the
ToolNode boundary. **One execution path, two trusted callers.**

### Two registered top-level agents, not one supervisor with two specialists

They differ in **interaction model**, not expertise. `vitess` is a guided conversation
that calls `ask_user`. `advanced_mode` is a long unattended sweep.

A supervisor that could delegate to `advanced_mode` would be running a forty-minute
batch inside a tool call tied to the HTTP connection — which is precisely the problem
juena's background-research subsystem exists to solve, and which v2 is deliberately not
inheriting. Two agent ids keep them on separate threads with separate checkpoints, and
core's `/stream` already takes an `agent_id`.

**Done when** a two-run parameter sweep completes with `simulation_plan` written by
tools rather than by the model, both runs land under
`{project}/{thread_id}/outputs/{simulation_run_id}/`, the summary names both by their
`run_name`, and `run_batch_from_matrix` exposes **no `module_results` argument at all**.

### What actually landed

*(Fill in after the work.)*

---

## Checkpoint 6 — retrieval, uploads, the UI and the launcher

**Retrieval.** `retrieval/` (226 lines, four modules) ports verbatim. It is imported
only by `advanced_mode` today; it stays that way and additionally becomes available to
the five module specialists as a tool. Chroma stays. `vitess-rag` stays a submodule.
**Core does not learn about it** — the same rule that keeps core away from juena-rag.

Keep the graceful degradation already there: `get_rag_tools()` returns four stub tools
answering `"RAG_UNAVAILABLE: …"` when the collection is empty or initialisation fails.

**Uploads.** `server/file_storage.py` (516 lines) and `file_endpoints.py` port. They are
genuinely different from juena's staged-input model and **must stay different**: the
VITESS binaries read **real files from disk** at
`{project}/{thread_id}/uploads/{module}/`, so uploads cannot live in graph state under
`/inputs/`. Delete `FALLBACK_MODULE_TYPES` in favour of the catalog (CP2).

### Per-module upload slots are kept, deliberately

The destination of an input file is not guessable cheaply, and **the cost of guessing
wrong is asymmetric**: a trajectory file landing in the guide slot produces a simulation
that runs, completes, and is physically wrong. That is the same class of failure CP1
exists to remove from command generation, and it should not be reintroduced at the upload
step. Asking costs seconds; a wrong slot costs a result someone might publish.

**Content classification was considered and rejected for now.** It would work much of the
time — `.inf` is unambiguous, MCPL has a magic number, and a VITESS trajectory row has a
known column structure (ID, trace flag, colour, time-of-flight, wavelength, intensity,
x/y/z, three direction cosines, spin). It is rejected because the person uploading is a
neutron scientist using their own files: they already know which file is which, so a
system that guesses and then asks for confirmation adds a step rather than removing one.
*What would reopen it:* files arriving from somebody else, or in bulk.

So a labelled slot stays. What changes is that it stops being the **only** way in, and
stops being a second source of truth.

### Three fixes, all using machinery that already exists

**1. The sidebar becomes a manifest.** Its real value is showing every slot at once —
*"has readin got everything it needs?"* is answered by looking. That is a **status**
function. It keeps an upload control per slot, and it gains a plain list of what is
currently staged, with remove and re-assign. With `path_only` gone (CP2) it covers three
slots, not six.

**2. The agent reads staged files; it does not remember them.** Today a file can be
uploaded and the model will not know unless it happens to call `inspect_thread_folders`
or `file_status` — so it can ask for a file already provided, or build a command against
one that was since replaced. Instead, each turn that touches a module **reads the file
store and states what it found**: *"Using `sample_beam.dat` for readin."* Same discipline
as `<verified_by_server>` — the store is the authority, not the transcript.

**3. `ask_user` is the second way in.** When a module needs a file and none is staged, the
specialist asks **in the chat**, where the person already is, rather than leaving them to
discover the sidebar. This needs no new mechanism: `ask_user` is already a tool, already
raises a LangGraph `interrupt()`, already renders as a card, and already resumes the
thread (00, and `juena_core.agents.ask_user`). The answer routes to the same
`file_storage` endpoint the sidebar posts to.

### The constraint that shapes this

An in-chat upload **cannot** go through juena's composer-attachment path. That path
decodes with `raw.decode("utf-8-sig")` (`juena/server/chat/inputs.py:104`) and puts the
result in graph state; VITESS trajectory files can be `VT_BINARY` and large. The in-chat
route must post to `file_storage` with an explicit module, exactly as the sidebar does.

Which is worth noticing honestly: **the composer would have to ask the destination
question anyway.** That is the strongest argument for keeping labelled slots — they
answer it for free, before it can be gotten wrong.

**Two upload paths, and they must not be confused.**

| | Chat attachment | VITESS module upload |
|---|---|---|
| Route | the message composer | the sidebar, per module |
| Lands in | graph state, `/inputs/` | **a real file** under `/data/projects/<thread>/uploads/<module>/` |
| Read by | the model, as text | the VITESS binaries |
| Validated by | `schema/upload_limits.py` | `server/file_storage.py` |

`.dat` and `.inf` are text and may join the chat-attachment allowlist. **`.h5` and `.nxs`
must not.** They are binary HDF5/NeXus, and the chat pipeline decodes attachments with
`raw.decode("utf-8-sig")` (`juena/server/chat/inputs.py:104`) — binary neutron data would
either throw or be silently mangled into the transcript.

They belong in the **file-storage** path, which never decodes: it writes bytes to disk for
the binaries to read. That path needs its own policy — a size ceiling, an extension
allowlist, and a magic-number check (`\x89HDF\r\n\x1a\n` for HDF5) — not a shared text
validator.

**UI.** `streamlit_app.py`, `sidebar.py`, `file_management.py` and `starters.py` are v2's
own. `chat_interface.py` and `ui_components.py` shrink to page layout over
`juena_core.ui.streaming` and `juena_core.ui.components`.

`sidebar.py` starts at 596 lines and should end well under that: three upload slots
instead of six, and `_render_path_upload_mode` (`:511`) deleted outright along with the
`path_only` mode it serves. **If it does not shrink, something was ported that CP2 said
to delete.**

**Launcher.** `./vitess`, per 00: `./juena` minus `rag-*`, `bootstrap`, `sp-metadata`
and `sandbox-*`, **and the whole host-process mechanism** — no pid files, no `.sandbox/`
runtime directory, no `wait_for_*` loops. The MCP server is a Compose service, so
`up`, `down`, `logs` and `ps` already cover it. Plus `check-imports`.

**Lock and image provenance.** This is the point where the second consumer actually
exists, so it owns the other half of 01/CP6's handoff contract:

- `uv.lock` is committed and `uv sync --frozen` passes against the sibling core;
- core's tree is clean and its exact commit SHA is written into the build record;
- Compose builds from the parent context, with the Dockerfile path relative to it, and
  the Dockerfile copies both `juena-core/` and this fresh repository into the image;
- `Dockerfile.dockerignore` beside the Dockerfile excludes every unrelated sibling,
  `.git/`, `.venv/`, model cache, Chroma database and generated VITESS build output while
  retaining the two source trees and `rag/vitess-rag` inputs the image needs;
- `docker compose build` requires no Git credentials, and the resulting image digest is
  recorded beside the core SHA.

Do not retrofit the legacy `Vitess-AI-Agent` checkout merely because it currently holds
these plans. The repository described by this plan is the fresh `vitess-ai-agent` named
under *Before you start*; its final paths are what the Docker allowlist must test.

**Done when** `./vitess help` lists the commands, `./vitess test-all` is green, and
`./vitess up` brings up a stack where:

- a file uploaded through the sidebar appears in `inspect_thread_folders` output — which
  proves app and MCP genuinely share the volume;
- the agent **names that file back** on the next turn without being asked, because it
  read the store rather than the transcript;
- a module with nothing staged asks for a file **in the chat**, and answering the card
  stores it against the right module;
- **no output filename appears anywhere in the sidebar** — `writeout`, `monitor1d` and
  `monitor2d` collect theirs conversationally, from the schema default;
- `WriteoutParameters.sOutFileName` is the only `output.dat` in the system. The old
  `output.out` sidebar default is gone, not reconciled.
- the build record names a clean core commit SHA and the digest of the image just tested.

### What actually landed

*(Fill in after the work.)*

---

## Verification

After every checkpoint:

```bash
cd vitess-ai-agent
./vitess test
```

At the end:

```bash
./vitess test-all
./vitess check-imports
./vitess up && ./vitess health
```

followed by six conversations:

1. **One guided single simulation**, completing all five modules **in order**, with a
   `<verified_by_server>` block whose execution line came from the MCP exit code and not
   from anything the model wrote.
2. **One two-run parameter sweep**, both runs landing under their own
   `simulation_run_id`, planned through `simulation_plan` rather than model arguments.
3. **One monitor1D plot** arriving as a **PNG artifact** in the chat — not as a file path
   in the text, and not as raw Plotly JSON.
4. **One file uploaded through the sidebar**, appearing in `inspect_thread_folders` —
   which proves app and MCP genuinely share the volume.
5. **`docker compose stop vitess-mcp` mid-conversation**, then `start`: the agent reports
   the outage per request while it is down, and **works again without restarting the
   app** once it is back.
6. **Switch agent mode on an existing thread**: a `vitess` conversation must not resume
   inside `advanced_mode`. The `agent_id` check refuses it.

**The defining proof is item 1**, and it is not "the UI started". It is a real minimal
VITESS run where the planned modules, the delegated modules, the executed modules, the
exit state, the files on the volume and the evidence shown in the browser **all agree**.

**And one check that spans all three plans:** with v2 running, `./juena up` must still
pass its own verification from 02. Two applications on one core means the second
application's needs must not have quietly changed the first one's behaviour, and the
cheapest time to find that out is the day v2 first runs.

---

## What could go wrong

| Risk | Guard |
|---|---|
| **The rebuilt simulator delegates out of order** — the monitor configured before the guide | the three-order golden test in CP4. There is no rollback, deliberately |
| Model-chosen values change what a shell parses | argument vectors, no `shell=True`, no generated script (CP1) |
| A `simulation_run_id` or filename escapes the project root | identifiers validated as identifiers; paths resolved under a server-controlled root (00, decisions 11 and 16) |
| MCP results never reach the UI because a queue cannot cross containers | the application façade in CP3a, tested on malformed and absent-file payloads |
| `execution_events` accumulates across turns and the block re-reports old runs | entries carry `graph_run_id`; the block is scoped to the current invocation (01/CP2) |
| `advanced_mode` bypasses MCP and runs VITESS in the app container | `vitess_ai.run` is the sole MCP execution gateway (CP5). The binaries **are** present — one image — so this is a code rule, and the test is that no module outside the MCP server imports `subprocess` |
| A thread resumes under the wrong graph | `agent_id`, checked on resume |
| The MCP port is reachable from the host | CP3's negative `curl` check |
| Binary `.h5` uploads hit the UTF-8 chat decoder | they go through file storage, never the chat allowlist (CP6) |
| a recent Deep Agents release changes the subagent `middleware` contract | CP0b validates the selected bounded release before extraction; CP5 consumes that recorded result |
| A parameter field has no flag and is silently dropped from the command | CP0's flag test |
| A module is dropped from the pipeline and the run reports success | CP1's corrections and its golden-file test |
| The FastMCP server is down at startup and a partial graph is cached for the process lifetime | Compose health ordering, loud construction failure, and the rule that failed construction is never cached (CP3) |
| Route 404s because the agent module was never imported | the `# noqa: F401` line in `service.py`, plus a test asserting `list_registered_agents()` |
| Two SQLAlchemy `Base` objects | import core's `Base`; test `set(Base.metadata.tables)` |

## What not to try

- **Do not put VITESS execution in juena's Podman sandbox.** It has no network and no
  VITESS build, and its entire design assumes an *untrusted, model-authored* command.
  VITESS execution is a *trusted binary invoked with validated parameters*. Different
  problem, different mechanism.
- **Do not migrate VITESS docs into juena-rag.** Settled; the import rule enforces it.
- **Do not make core depend on `vitess-rag`.** Retrieval is application-supplied.
- **Do not build a plugin system for agents.** `register_agent_factory` plus one import
  line is already the answer and is already load-bearing.
- **Do not make `catalog.py` discover agents.** Data table on one side, explicit builder
  list on the other.
- **Do not port `UnifiedState`, either `ModuleResult`, either `SupervisorStage`,
  `tool_wrapper.py`, `mcp/utils.py`, or `core/registry.py`.**
- **Do not keep `PUT /config/vitess`.**
- **Do not `.fn()` into a FastMCP tool.** Extract the shared function instead.

## Status

| | |
|---|---|
| **Depends on** | 02, verified |
| **Unblocks** | — |
| **Decided** | schemas ported verbatim and kept out of core; `generate_cli_command` becomes a pure function in `cli/command.py`, building **argument vectors** rather than shell text; catalog becomes pure data carrying `cli_executable` and `accepts_upload` independently; **MCP is an internal Compose service sharing a volume**; simulator rebuilt with **no legacy fallback**; two registered agents rather than one supervisor; **PNG artifacts canonical**; Chroma stays; fixed local principal; **per-module upload slots kept, the three `path_only` rows deleted, sidebar becomes a manifest, `ask_user` is the second way in** |
| **Open** | whether `research/` should come into core after all, once a sweep is lost to a closed browser (CP5); whether a run manifest on the volume is needed alongside the returned metadata (CP3a); whether content classification of uploads is worth adding — *reopen when files start arriving from other people, or in bulk* (CP6) |
| **Revised** | 2026-09-15 after [REVIEW.md](REVIEW.md) — Compose topology replaces the host process, CP3a added for the evidence bridge, argument vectors replace shell text, recursive flag test, `simulator_legacy` dropped, real order test, `agent_id`, binary uploads separated |
| **Revised** | 2026-09-15, upload workflow — `cli_executable` and `accepts_upload` are independent, the three `path_only` rows deleted as duplicates of existing schema fields, sidebar becomes a manifest, `ask_user` added as the in-chat route |
