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
  "httpx>=0.28,<1",             # imported directly by the MCP health probe
  "matplotlib", "numpy", "plotly",
  "pydantic>=2,<3",             # imported directly by the VITESS parameter and catalog models
  "starlette>=1,<2",            # imported directly by the FastMCP health response
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

Completed 2026-09-16 in a fresh sibling repository,
`Vitess-AI-Agent-v2`. The planned lowercase directory name could not coexist with the
legacy checkout on the case-insensitive macOS volume, so the suffix preserves the old
repository intact while retaining fresh Git history.

- Added the Python 3.11 package scaffold, sibling `juena-core` path source and
  `vitess-rag` submodule. The committed lock retains the validated framework set,
  including FastMCP 4.0.3 rather than the newer 4.0.4 selected by an unconstrained
  fresh resolution.
- Copied the six schema files byte-for-byte from the legacy checkout. None of
  `monitor_module.py`, `supervisor.py`, `server.py` or `llm_models.py` was ported.
- Exported the five parameter models and `get_field_flag` explicitly from
  `vitess_ai.schema`; `len(vitess_ai.schema.__all__)` is 6.
- Added a recursive leaf walker and per-model regression counts. It found all 104
  declared leaves (13, 15, 31, 20 and 25 respectively) and found no missing or empty
  flags. The two unflagged `WriteoutParameters` container fields recurse into their
  flagged nested leaves as intended.
- `uv run pytest tests/test_schema_flags.py -q`: 6 passed.

Plan 02's browser and real-IFFLogin acceptance gates remain open. CP0 was prepared at
the user's explicit direction; this record does not reclassify Plan 03 as formally
unblocked.

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

Completed 2026-09-16 in `Vitess-AI-Agent-v2` commit `8cd7b8d`.

- Added the configuration-free `vitess_ai.cli.command` module. Its required inputs
  include the project root, modules root, canonical thread UUID, canonical simulation
  UUID and executable mapping; importing it does not load FastMCP.
- `generate_cli_command` now accepts only validated `list[str]` CLI parameters and
  emits one exact argument vector per requested module. A missing result, missing or
  shell-shaped parameter list, absent executable mapping, invalid basename, missing or
  non-executable binary, path escape or empty input fails closed. Partial failures name
  the offending module and report only vectors actually emitted.
- Executable catalog values are basenames. Each binary is resolved beneath the trusted
  modules root, including symlink resolution, and must be executable. Thread and run
  identifiers are canonical UUIDs. Absolute parameter paths must remain under the
  project root; parent traversal is rejected.
- Ordering uses literal `--N1` through `--N5` values and a run-scoped concrete log
  prefix; no vector in the five-module golden contains `$`. The retained
  `cli_command` value is explicitly display-only and rendered from the vectors.
- Added an MCP-side process runner that joins vectors with `subprocess.Popen` pipes and
  `shell=False`. It records every exit code, fails if any stage fails, terminates every
  surviving child on timeout and performs result-log concatenation and cleanup with
  `pathlib`, scoped to the run directory. No script or shell text is generated.
- Injection regressions cover spaces, semicolons, `$()` and leading dashes as one
  argument each; `../` and absolute escapes are rejected. The inverted legacy
  missing-module and empty-input expectations now fail closed.
- `uv run pytest tests/test_cli_command.py -q`: 25 passed. The complete CP0+CP1 suite:
  31 passed.

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

Completed 2026-09-16 in `Vitess-AI-Agent-v2` commit `06ea450`, then hardened by
post-completion review commit `d33925e`.

```text
uv run python -c "import vitess_ai.modules.catalog, sys; ..."   False False
uv run pytest tests/test_catalog.py -q                          19 passed
complete CP0+CP1+CP2 suite                                      50 passed
```

- `vitess_ai/modules/catalog.py` imports pydantic and nothing else. `agent_class`,
  `tool_factory` and `validation_tool_patterns` are gone. Neither fallback table was
  ported: a fresh repository deletes them by not copying them, and the module
  docstring names both so the reason they existed is not rediscovered later.
- Six frozen `ModuleSpec` rows carrying `name`, `display_name`, `description`,
  `order`, `cli_executable` and `accepts_upload`, with four readers over them —
  `module_spec(name)`, `execution_order()`, `cli_executables()` and
  `upload_modules()`. `module_spec` raises a `KeyError` naming the known modules; a
  builder that asks for a row that is not there has a broken install, which is
  exactly what the old fallback tables turned into a silent degradation.
- Executables are basenames: `read_in`, `guide_parallel`, `writeout`, `monitor1D`,
  `monitor2D`. A test asserts no catalog value contains `/` or `$`, and it names the
  five rows expected to have one rather than asserting it of every row — a blanket
  assertion fails on `instrument` and gets weakened to nothing within a day.
- The three `path_only` rows are gone. Three rows accept an upload — `readin`,
  `guide`, `instrument` — and `UploadSchema` has no field that could hold a filename.

#### Two decisions the checkpoint left open

**`instrument` gets `order=2`, and the other rows shift up.** The old table gave it
the same `order` as `guide`, so the sidebar's shape was decided by a name tiebreak
rather than by anyone. It now sits next to the module it feeds — it supplies
read-in's `sInstrInfIn` (`--I`) — and the remaining rows run 3 to 6. Nothing in the
pipeline moves: `--N1`..`--N5` come from the position in the list handed to
`generate_cli_command`, not from this field, and `execution_order()` skips rows with
no executable. A test asserts the orders are unique and that `execution_order()` is
still `readin, guide, writeout, monitor1d, monitor2d`.

**Both models set `extra="forbid"`.** Pydantic ignores unknown fields by default, so
re-adding `default_filename=` to a row would have been silently dropped — and the
test asserting its absence would have passed while the author believed the opposite.
Forbidding extras makes that a construction error instead. This was found by trying
the break rather than by reading the model.

#### The deletions were checked, not assumed

`test_the_schema_still_owns_each_deleted_filename` asserts that each filename the
deleted rows carried is still declared by its parameter model with its own flag and
default: `WriteoutParameters.sOutFileName` (`-A`, `output.dat`),
`Monitor1DParameters.fMonitorFilename` (`-O`, `monitor1D.dat`) and
`Monitor2DParameters.fMonitorFilename` (`-O`, `monitor2D.dat`). Deleting the rows
moved ownership; it did not drop the values. The drift the checkpoint predicted is
confirmed in the source it was predicted from: the old sidebar said `output.out`
where the schema said `output.dat`.

`test_the_catalog_mapping_is_what_the_command_generator_wants` feeds
`cli_executables()` into the real `generate_cli_command` against real executable
files. CP1 deliberately takes its mapping as an argument and stays free of
configuration, which means nothing otherwise checks that the catalog can supply what
it wants — and that gap is how two mappings drifted apart the first time.

#### Every guarantee was broken on purpose first

| Break | Caught by |
|---|---|
| `cli_executable="$V/read_in"` | the basename test, and the generator integration |
| `writeout` regains an upload row with `default_filename` | the three-upload-rows test, and the no-filename test |
| `import langchain` at the top of the catalog | the subprocess import test |
| `instrument` given `guide`'s order | the unique-order test |

The import test runs in a subprocess. Asking `sys.modules` inside a pytest session
that has already imported half the framework would prove nothing.

#### Post-completion review

The review found no incorrect catalog row, executable, upload assignment or ordering.
It did find three gaps around the implemented contract and corrected them in `d33925e`:

- `vitess_ai` imported Pydantic directly from both its parameter schemas and this
  catalog, but relied on `juena-core` to install it transitively. `pydantic>=2,<3` is
  now a direct runtime dependency; the offline lock refresh changed only the root
  package's dependency metadata and retained the validated framework versions.
- The first test set named the five executable rows and three upload rows, but an inert
  seventh row could sit outside both filters without failing. The suite now pins the
  exact six catalog names and the exact fields of both `ModuleSpec` and `UploadSchema`,
  and explicitly proves that removed fields such as `agent_class` and
  `default_filename` are rejected.
- The subprocess test proved that importing the catalog did not load `langchain` or
  `deepagents`; it did not prove the narrower source-level claim that the catalog has no
  project or agent-framework imports. An AST-level regression now restricts the source
  imports to `__future__`, `typing` and `pydantic`, while the subprocess test remains as
  the runtime check.

The catalog docstring also changed one sentence to future tense: the five explicit
specialist builders are a CP4 deliverable and did not yet exist at CP2.

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

Completed 2026-09-16 in `Vitess-AI-Agent-v2` commit `4e21722` and reviewed in
`cd7ffe6`, against `juena-core` at `a64c978` with a clean tree.

```text
uv run pytest -q                                 121 passed   (CP0-CP2: 50)
uv sync --frozen                                 ok
docker compose build vitess-mcp                  context 1.31 MB, one image
docker compose up -d                             three services, mcp healthy
  exec vitess-app curl http://vitess-mcp:9005/health   200, both checks ok
  exec vitess-app discover_vitess_tools()              the four tool names
  curl http://127.0.0.1:9005/health                    connection refused
VITESS_MODULES_PATH=/nope                        503, naming all five executables
```

Reviewed image
`sha256:ecb7a0a6b8bb668ee03454402513cf8d1cb4c8f1d231076ff5a7fc053b6ce8b5`,
1,089,455,521 bytes, and `docker inspect` reports **the same image id for both
containers** -- which is the one-image decision, checked rather than assumed.
Both containers also carry the image label
`de.fz-juelich.vitess.source-revision=6bd0e0066c4667444368dd2492f77821ff8a5609`.

#### Post-completion review

The review found and fixed defects that the original green suite did not cover:

- The four async FastMCP handlers called blocking simulation, inspection and
  plotting functions on the event-loop thread. A long VITESS run would therefore
  stop health and every other MCP request. They now use `asyncio.to_thread`; a
  regression holds the pipeline worker and proves the event loop remains live.
- Canonical UUIDs did not make the volume boundary safe: an existing `outputs`
  symlink could redirect a plot read and PNG write outside `/data/projects`. The
  exploit was reproduced before the fix. Every thread, upload, output, run and
  file boundary is now resolved beneath its trusted root, with symlinks refused.
  Reusing a run UUID is also refused instead of mixing stale files into new
  evidence, and inspection ignores directories that are not canonical run IDs.
- Tool discovery checked only for missing names, so an unexpected fifth tool
  would have been handed to the application. Discovery is now an exact four-name
  allowlist and fails construction on either missing or unexpected tools.
- Concurrent health requests shared one probe filename; the probe is now unique
  and automatically removed. TCP ports above 65535 and non-finite timeouts are
  rejected at startup. XYZ monitor input now rejects duplicate coordinates that
  could previously hide a missing grid cell while preserving the expected row
  count.
- The original image combined a VITESS 3.7 amd64 tarball with a moving VITESS 3.8
  `develop` build on other architectures. Every architecture now compiles the
  same exact revision shown in the image label, and uv is pinned at 0.12.15 rather
  than copied from `latest`. `starlette` is declared directly because the server
  imports its request and response types directly.
- Live logs exposed FastMCP contacting PyPI at startup only to advertise updates.
  `FASTMCP_CHECK_FOR_UPDATES=off` removes that external startup dependency; the
  recreated MCP container reached healthy without the request or update banner.

The original symlink exploit created a PNG outside the project volume; the same
probe now raises `ToolError: Outputs directory must not be a symbolic link`. The
reviewed stack was recreated without dropping its named volumes, remained healthy
from `vitess-app`, discovered exactly four tools, kept port 9005 unreachable from
the host, and returned the five executable names for a deliberately broken module
root. The final full suite is 121 passed with only the already-recorded
`LangChainBetaWarning`.

#### The topology, as built

`docker-compose.yml` brings up `postgres`, `vitess-mcp` and `vitess-app` on one
network with `vitess-projects` mounted at `/data/projects` in both application
services. Only `127.0.0.1:9601` is published. `vitess-mcp` publishes no port at
all, and the negative check above confirms the host has no route to it.

**Only `vitess-mcp` carries the `build:` section.** Declaring it on both, which
is how this was first written, built the same Dockerfile twice and produced two
image ids for what the plan calls one image -- so there was nothing single to
record as the digest that was tested. `vitess-app` names the tag and waits on
`depends_on`; a plain `docker compose up -d` with no image present was run to
confirm the image is built once, before either container is created.

The Dockerfile builds VITESS revision
`6bd0e0066c4667444368dd2492f77821ff8a5609` from source in a first stage on every
architecture -- which on this arm64 laptop produced 99 native modules -- and
copies only `MODULES` into the application image. It builds from the **parent
context** for the same reason juena-chatbot does: `juena-core` is a sibling path
dependency. `Dockerfile.dockerignore` is therefore the only filter in effect,
deny-by-default, and it was checked by measurement after review: **1.31 MB
transferred** out of a parent holding roughly nine gigabytes, several unrelated
repositories with real credentials in their own `.env`, and the first-generation
`Vitess-AI-Agent` checkout.

Both containers run as an unprivileged user created in the image, which owns
`/data/projects`; Docker copies that ownership into a fresh named volume, so a
non-root container can write to it without a startup `chown`.

The drift the checkpoint named -- `READIN_MCP_PATH` and friends, ports 9001-9004,
and the README paragraph repeating the claim -- is gone by not being copied. The
legacy checkout still holds it and is deliberately not retrofitted (CP6).

#### `vitess-app` runs `sleep infinity`, on purpose

There is no application yet: CP4 builds the agent and CP6 the entrypoint. The
container is the real image on the real network with the real volume, which is
what makes the checks above mean anything -- the plan's "from inside the app
container, which is the only place that matters". The command is one line to
replace and says so in a comment naming CP6.

#### Two decisions inside the server

**Raised or returned, and the split is deliberate.** A malformed *argument* --
an identifier that is not a canonical UUID, a filename that is a path -- raises
`ToolError`. Every argument reaches these tools from trusted application code,
never from a model, so a bad one is a bug and bugs should be loud. An
*execution* -- a module that failed, a pipeline that timed out, parameters that
were refused -- returns a `SimulationResult` with `success=False` and whatever
evidence exists. A simulation that did not run must never read as one that ran
and produced nothing, and that is a shape, not a message.

**A produced file is `plot`, `log` or `data`.** 03/CP3a's sketch shows
`"kind": "monitor_data"`; this returns the three above, decided by extension and
the one known log name. Which file holds monitor data is known from the
parameters that asked for it -- `-O` names it -- so classifying by filename
would be guessing at something already known, and the guess would be wrong the
moment a user names their output something else.

#### The monitor file format is five formats, and the old reader knew none of them

`generate_monitor1d_plot` and `generate_monitor2d_plot` need to read what the
monitors write. Reading VITESS 3.8's actual output, rather than the
first-generation `plots/vitess_plot.py`, turned up three things:

1. **`Monitor2DParameters.format` (`-F`) has five writable values and defaults
   to `matrix`.** `matrix`, `matrix_compact` and `matrix_integer` write a row of
   x bin centres and then one row per y bin, carrying **intensity only**;
   `xyz` and `xyz_compact` write one row per cell, five columns, keeping the
   error and the trajectory count. A reader written for one layout fails on the
   other -- and the schema's *default* is the one the reader had not been
   written for. This was found by generating a file in each format with the real
   binary, not by reading the code.
2. **`matrix_integer` holds counts, not a rate**, over the source's measurement
   time, while VITESS writes the same `n/s` in the title either way. The reader
   returns what the file holds; a test asserts the one constant ratio between
   that layout and the rate layouts, so the difference is recorded rather than
   discovered later by someone comparing two plots.
3. **The old reader was off by one in both layouts.** In 1D it started at the
   second data row (a second copy of it started at the third), so the first bin
   of every 1D monitor -- a real measurement -- was missing from the plot. In 2D
   it took the *first row of data* as the x axis, which is the second row of a
   matrix file, and it could not read an xyz file at all.

So `plots/` is new code, not a port: `monitor_file.py` reads any of the five
layouts into bin centres and a grid, and `render.py` draws a PNG through
matplotlib's object interface with an explicit Agg canvas -- no `pyplot`, whose
global figure registry leaks between requests in a long-running server. PNG
rather than Plotly JSON because the application registers it with the artifact
store that already delivers images into the chat (03/CP3a).

**The fixtures are files VITESS wrote.** `tests/data/` holds one 1D file and one
per 2D format, produced by `monitor1D` and `monitor2D` from VITESS's own module
test inputs; `tests/data/README.md` carries the exact command. Four of the five
2D files are the same measurement written four ways, and a test asserts they
read back to the same grid -- four files that disagree would mean the reader has
one of the layouts wrong. A hand-written fixture could not have shown any of
this, because a hand-written fixture is written to match the reader.

#### A real five-module pipeline ran, which the checkpoint did not ask for

From inside `vitess-app`, over MCP, against the real binaries:

```text
readin     exit=0  /vitess/MODULES/read_in_Linux_aarch64
guide      exit=0  /vitess/MODULES/guide_parallel_Linux_aarch64
writeout   exit=0  /vitess/MODULES/writeout_Linux_aarch64
monitor1d  exit=0  /vitess/MODULES/monitor1D_Linux_aarch64
monitor2d  exit=0  /vitess/MODULES/monitor2D_Linux_aarch64
files: geometry.inf, guide_shape_out.dat, instrument.inf, monitor1D.dat,
       monitor2D.dat, output.dat, result.txt
generate_monitor1d_plot -> monitor1D.png   (a wavelength spectrum, 3-6 A, with errors)
generate_monitor2d_plot -> monitor2D.png   (the guide exit, 3 x 3 cm)
```

The input was a trajectory file from VITESS's own guide test, copied into
`/data/projects/<thread>/uploads/readin/` **through the application container**
and read by the MCP container -- so the shared volume is proved from both ends,
and `inspect_thread_folders` listed it at its real byte size before the run.
The parameters are hand-copied from two VITESS module tests, not generated from
the schema; producing them from the models is CP4's work. `executable` reports
the resolved path, which is the architecture-suffixed file behind the short
symlink -- the evidence names the file that actually ran.

One thing that cost an hour and is worth writing down: **`--Fno_file` marks the
last module of a pipeline.** On any earlier module it stops trajectories
reaching the next one, and the run then completes with every exit code zero and
every monitor empty. It is in `tests/data/README.md` too.

#### What this checkpoint does not contain

- **The façade.** The raw tools take `thread_id`, `simulation_run_id` and
  `module_results`, and a test asserts they do -- which is exactly why they are
  never bound to a model. `vitess_ai.run` and the façade tools are 03/CP3a.
- **`ExecutionEvidenceMiddleware` and the `execution_events` channel.** Also
  CP3a. The server returns the evidence; nothing yet turns it into a
  `<verified_by_server>` block.
- **`./vitess`, the entrypoint and the build record.** CP6, per its own list.
  `docker compose` is used directly until then.

#### Every guarantee was broken on purpose first

| Break | Caught by |
|---|---|
| `import langchain` at the top of the server | the subprocess import test |
| a refusal reports `success=True` | the missing-module and validation-error tests |
| the validation-error guard removed | the validation-error test |
| produced files reported as absolute paths | the relative-path test |
| a plot filename may be a path again | the traversal test |
| the 1D reader drops the first bin, as the old one did | the every-bin test |
| 1D intensity and error read from the wrong columns | the column-order test |
| a 1D row of the wrong width is skipped | the wrong-width and every-bin tests |
| the matrix reader takes its first data row as an axis | the cross-layout and beam tests |
| the xyz grid is transposed | the cross-layout test |
| an incomplete xyz file is drawn with holes | the incomplete-file test |
| the matrix layouts invent zeros for the error they omit | the no-error test |
| only the xyz layout is recognised | the cross-layout and integer-layout tests |
| health stops checking the executables | the missing-executable tests |
| the health probe accepts any status code | the unhealthy-server test |
| discovery tolerates a missing tool | the missing-tool test |

Sixteen breaks, sixteen caught. Two of them are the first-generation reader's
actual bugs, reintroduced to check that the tests would have caught them.

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

Completed and reviewed in v2 `c2fdfbd` (*bridge VITESS MCP evidence into agent
state*). The bridge is three deliberately separate pieces:

- `vitess_ai.run.VitessGateway` owns the discovered raw tools. It accepts an
  `InternalSimulationRequest` assembled by trusted application code, invokes the
  MCP tool with a generated internal tool-call id, and validates only
  `ToolMessage.artifact["structured_content"]` through a strict
  `MCPToolArtifact` and the CP3 payload models. It never parses the text block.
  Transport failures, tool errors and malformed structured payloads all become
  typed failed execution evidence rather than an exception-shaped hole in the
  ledger.
- `build_vitess_tools()` exposes four same-named application façades. Their
  closed model schemas contain only `run_name` and, for plots, `filename`;
  `thread_id`, `simulation_run_id`, `module_results` and `run_specs` are absent.
  `ToolRuntime` is declared as an injected, JSON-hidden field, so ToolNode strips
  any forged value and supplies the real runtime without weakening
  `extra="forbid"`. The execution façade reads the UUID thread id from
  `runtime.execution_info`, the user and graph invocation from typed context,
  validated module state from `runtime.state`, and generates the simulation UUID
  itself.
- `VitessBridgeState` adds a private list-reduced `simulation_runs` channel. It
  pairs a model-chosen human label with the server-generated UUID, allowing the
  plot façades to select a run without ever making an ownership identifier a
  model argument. It extends core's `SpecialistOutcomeState`, whose private
  list-reduced `execution_events` channel carries the evidence. The exported
  `vitess_supervisor_middleware()` is the CP4 splice: root
  `ExecutionEvidenceMiddleware` plus `ArtifactMessageMiddleware`.

The application does not trust the shared mount merely because both containers
can see it. Before mutating `ArtifactStore`, it resolves **every** claimed file
under its own `<project>/<thread>/outputs/<simulation-run>/` root, rejects
absolute paths, traversal, duplicate metadata, missing files, byte-count drift,
and a symlink in any ownership or file-path component. This includes a symlink
to another thread *inside the same project volume*, not just an escape outside
the volume. Only after that pass does it register the files; unsupported or
over-budget output is recorded as undelivered evidence. Plot façades require the
PNG itself to register successfully.

Two review findings changed the implementation before commit:

1. An explicit strict façade schema initially rejected LangGraph's injected
   `ToolRuntime`, making the tool return a generic invocation error before it
   reached MCP. The final schema includes an `InjectedToolArg` plus
   `SkipJsonSchema` runtime field. A real `create_agent` test proves the call,
   private evidence reducer, root evidence block and artifact attachment as one
   graph, rather than testing the four parts independently.
2. Reporting a partly failed pipeline as several generic execution attempts
   lets core's retry semantics treat earlier zero-exit modules as a successful
   retry. A successful pipeline therefore records one entry per module, while a
   failed pipeline records one failed pipeline operation with the non-zero exit
   code. The MCP payload still retains every module's exact evidence.

`tests/test_evidence_bridge.py` has 19 focused tests. It proves valid structured
content becomes five typed entries, malformed content becomes `tool_error`,
owner mismatches and path escapes fail, transport text is bounded, a
claimed-but-absent file cannot leave a successful result, all four model schemas
exclude the trusted fields, the plot uses a private run UUID, and the real graph
ends with both `<verified_by_server>` and `juena_artifacts`. Full suite:

```text
uv sync --frozen                         Audited 187 packages
uv run pytest -q                         140 passed
```

The reviewed image is
`sha256:955af1ea39a66829abb38426f663581a0f950a65a002e956a7af357eea6cf5ca`.
From `vitess-app`, against the real internal HTTP MCP service, the façade ran
`readin -> guide -> writeout -> monitor1d -> monitor2d`; all five exits were
zero. The root answer contained `<verified_by_server>` and attached
`guide_shape_out.dat`, `monitor1D.dat`, `monitor2D.dat`, `output.dat` and
`result.txt`. The plot façade then produced and registered `monitor1D.png`.
This proves the browser-facing message payload; the literal browser rendering
cannot be exercised until CP6 replaces `sleep infinity` with the API/UI
entrypoint, so that final visual check remains in CP6 rather than pulling its
entrypoint into this checkpoint.

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

Completed 2026-09-17 in `Vitess-AI-Agent-v2` commits `e49d5f0` and `f55e140`, with two changes in
`juena-core` (`08c013c`, `4cd5969`).

```text
uv run pytest -q                                221 passed   (CP0-CP3a: 140)
uv sync --frozen                                ok
juena-core suite                                474 passed (unchanged: the 2 failures
                                                and 24 errors are Postgres-only and
                                                identical before the change)
juena-chatbot ./juena test                      232 passed against the rebuilt core
docker compose build && up -d                   one image, both services, mcp healthy
```

**The rebuild held the order**, and the test did not have to be taught anything to
show it -- it had to be built to record three lists separately instead of asserting a
set. What did need teaching was the *harness*: the first version seeded
`planned_execution_order` as graph input and the run was refused, because the channel
is private and therefore absent from the graph's input schema. That is the design
working: the only way to get a plan is to call `plan_simulation`.

#### The order, as three recorded lists

`tests/test_simulation_order.py` runs the real supervisor graph -- core's real
middleware stack, the real delegation boundary, the real façade tools -- against a
scripted model, and records:

1. what `plan_simulation` returned, read back out of its own tool message;
2. which specialist each `task` call actually reached, recorded by the specialist;
3. which modules `generate_cli_command` emitted, recorded by the MCP double, which
   **runs CP1's real generator** against stub executables rather than inventing a
   result.

Then a fourth: the basename at the head of each argument vector, against
`cli_executables()`. All four compared element by element.

Four fail-closed cases sit beside it: **no plan at all** (refused, naming the missing
call), **a module never delegated** (refused, naming the module), **a module
delegated twice** (accepted -- it replaces its own entry and disturbs no other), and
**a configuration for a module that was never planned** (refused).

#### The typed hand-off, which is what the order is about

`SpecialistReport` is prose and core's delegation boundary carries `messages` and
`files`. So a validated `GuideParameters` had no route to the command builder, and
the only remaining route was the model retyping the numbers -- the path CP1 exists to
close. Three pieces close it:

- **`schema/module_result.py`** -- `ModuleConfigurationResult(module, validated_at,
  parameters, schema_version)`, exactly as planned. `schema_version` is *computed*
  from the model's field names and flags rather than hand-maintained, because a
  version number nobody remembers to raise is worse than none.
- **`module_results`, a state channel with a merge reducer** keyed by module name.
  Re-validating one module replaces its own entry; "make the guide wider" does not
  unconfigure the monitors.
- **`agents/delegation.py`** -- `ModuleSpecialistDelegate` extends core's boundary by
  one field in one direction, and returns **only its own module's entry**. Nothing
  sends `module_results` inbound, so an entry under another module's name can only be
  something the specialist invented.

**`module_results` is deliberately not a `PrivateStateAttr`, and that is
load-bearing.** `SubAgentMiddleware` strips private keys from a subagent's returned
state (`deepagents/middleware/subagents.py`, `_return_command_with_state_update`).
Marking it private -- which looked right, since `execution_events` and
`simulation_runs` both are -- leaves every module unconfigured with *no error*: the
specialists report success and `run_simulation` refuses a pipeline nobody configured.
Found by making it private and watching the golden test fail, and the state module now
says so where the channel is declared.

#### One change in juena-core, and why it could not be avoided

`build_supervisor_middleware` applies `with_delegation_boundary` itself, so passing
an already-wrapped specialist wrapped it twice -- and the outer, plain
`SpecialistDelegate` dropped the very field the subclass exists to carry. So core's
`with_delegation_boundary` now leaves a specialist that already carries a boundary
alone.

It is the right place for the fix rather than a v2 workaround: **the second wrapper
can only ever remove what the first allowed**, so wrapping twice is never correct for
any application. juena-chatbot never pre-wraps, so its behaviour is unchanged and its
232 tests confirm it. A core test pins the idempotence with a subclass that adds a
field, which is the case that would otherwise regress silently.

#### One converter, not five

The first generation had `readin_params_to_cli`, `guide_params_to_cli`,
`writeout_params_to_cli` and one per monitor, and they had **already drifted**: only
writeout rendered booleans as `1`/`0`, only the monitors skipped a field whose flag
was missing, and only read-in understood a field carrying one flag per list element.

`cli/arguments.py` is one function over the three shapes the five schemas actually
contain, measured rather than assumed: two list fields (both read-in's, both
multi-flag) and two nested models (both writeout's). The nested rule is decided by
**counting distinct flags**, not by naming the field: nine booleans that all carry
`-c` become `-c111111111`; twelve numbers with twelve flags become twelve arguments.

**A field with no flag now raises.** The monitor converters skipped it with a comment
explaining that a bare value would otherwise land in the command -- and what that
produces is a parameter the user asked for, absent from the simulation, in a run that
completes. That is CP1's defect in a different file.

**The arguments are derived at execution time, not stored.** `ModuleConfigurationResult`
holds the validated parameters and nothing else, and `run_simulation` re-validates each
one through its module's model and converts it there and then. A stored
`cli_parameters` list would be a second answer to "what does this run as", and two
answers drift.

#### What the prompts actually were

The plan said `prompts/` (1,486 lines) ports "almost verbatim". That is true of the
five module prompts and **false of `supervisor.py`**: its 213 lines are entirely about
the hand-rolled router -- `greeting_message`, `current_active_module`,
`route_to_module` -- which is the thing being removed. `SUPERVISOR.md` is therefore
new writing, about delegation, order and the `<verified_by_server>` contract.

The five module prompts were **two prompts each** -- `*_DEFAULT_PROMPT` and
`*_CUSTOM_PROMPT`, near-identical. The first pass folded them into five short
`AGENT.md` files of about 65 lines each, and that was wrong: **the detail is the
point**. These prompts are read by a model that has to know that an m-value above 6
does not exist as a product, that a range which misses the beam produces a plot
indistinguishable from a failed simulation, and that `matrix_integer` writes counts
while VITESS still labels them "n/s". A weaker model cannot infer any of that.

So the five `AGENT.md` files are ports of the originals, both paths kept in full --
the numbered steps, the complete default-configuration blocks, the parameter
categories, the presentation formats, the per-parameter validation rules. 1,249 lines
of authored prompt, where the originals were 1,273 across ten prompts, so each path
now carries roughly twice the guidance it did.

The schema is no longer interpolated into an f-string. `build_module_prompt` appends
`model_json_schema()` at build time, so the schema in the prompt is by construction
the one the validation tool enforces -- and a test asserts each specialist's prompt
names **its own** model and no other, because a prompt holding two modules' field
names is how a specialist configures the wrong module.

**A second test asserts the default-configuration block in each prompt is the schema
default**, field by field, and that it omits no field. Two values ported straight from
the first-generation prompts were already wrong: the guide's `eGuideShapeY` and
`eGuideShapeZ` said `0` (VT_CONSTANT) where the schema says `1` (VT_LINEAR), so a model
reading the prompt would configure a different guide from the one the user was shown.
One exception is named in the test with its reason -- read-in's `sInstrInfIn`, where the
prompt deliberately overrides a schema default that names a file which does not exist.

**A third test asserts each prompt names exactly the tools that specialist has**, in
both directions. The first-generation read-in prompt told the model to call
`get_instrument_file` and `instrument_file_status`, neither of which its builder
returned; a weaker model follows the prompt, the call fails, and it has no instruction
for what to do instead. The opposite mistake -- a tool the specialist has and the
prompt never mentions -- is a capability the model will not discover.

#### The tool surface was seven tools too wide

A module specialist's whole job is a conversation and one validation call. Each was
being bound **eleven tools**: `ls`, `read_file`, `write_file`, `edit_file`, `delete`,
`glob`, `grep` and **`execute`**, on top of its own three. `FilesystemMiddleware`
exposes everything the backend supports unless it is told otherwise, and core's
`build_specialist_middleware` never told it.

It takes an allowlist, so core's builder now passes one through, defaulting to `"all"`
so juena-chatbot's research specialists are untouched -- a core test pins that default
precisely because narrowing it would change the other application. v2 asks for
`read_file` alone, which is the one the middleware requires in any list and the one
that earns its place: the delegation boundary carries `/findings/` inbound, so a later
module can read what an earlier one recorded.

| | before | after |
|---|---|---|
| `readin`, `guide` | 11 tools | 4 |
| `writeout`, `monitor1d`, `monitor2d` | 10 tools | 3 |

`execute` and `delete` are gone from every module specialist. Four more deliberate
breaks confirm it: widening the allowlist, dropping it at the call site, a prompt that
stops naming a tool it has, and core narrowing its default. Three more cover the
prompt defaults: the old VT_CONSTANT value restored, a field dropped from a block, and
a field named that the model does not have.

#### Three defects the port had to correct rather than carry

**The monitor prompts demanded a full absolute path** for `fMonitorFilename`, in
capital letters, while the monitor *tools* quietly took the basename -- prompt and
tool disagreed, and CP3's plot tools accept a plain name only, so what the prompt
asked for would have been refused there. The filename is now checked to be a plain
name at validation, for `sOutFileName` and both `fMonitorFilename` fields.

**`ReadInParameters.sInstrInfIn` defaults to the bare name `instrument.inf`**, a file
that exists only if the user uploaded one. VITESS resolves it against the run
directory and read-in fails with an error nobody can trace to a cause. The old prompt
worked around it by telling the model to send `null`; a prompt is not a check. A file
parameter must now name a path beneath `{project}/{thread_id}/uploads/`, which also
refuses another conversation's upload.

**`file_status` / `get_files` read a module-level global and the `THREAD_ID`
environment variable.** Replaced by one `list_staged_files` tool bound to its module,
reading the thread id from `runtime.execution_info` and the volume through the MCP
gateway -- the store is the authority, not the transcript. Only read-in and guide get
it; the other three write files and have nothing staged to look at.

#### Twenty-one guarantees broken on purpose

Nineteen failed the moment they were broken. Two survived their first break and then
failed when the break was made total -- both are held by **two independent layers**,
which is worth recording rather than glossing:

| Guarantee | First break | Why it survived |
|---|---|---|
| A planned module with no configuration stops the run | `_configured_arguments` narrows the plan | `InternalSimulationRequest` (CP3a) refuses the mismatch too |
| A file parameter must name a staged upload | the absolute-path check goes | resolving a relative path lands outside `uploads/` anyway |

Removing both layers fails the tests in each case. Among the nineteen caught directly:
`module_results` marked private, `run_simulation` falling back to the catalog when
nothing was planned, a specialist returning another module's entry, a flagless field
skipped, an over-long file list truncated, an output filename allowed to be a path, a
failed validation writing `{"validation_status": False}` into the channel, the reducer
overwriting instead of merging, and core wrapping an application boundary twice.

#### Proved against real VITESS, from inside the application container

The five **real** validation tools produced the configurations; the real supervisor
graph planned, delegated five times and executed; the MCP server ran VITESS over HTTP:

```text
delegated in order: readin, guide, writeout, monitor1d, monitor2d
result.txt:  Input file .../uploads/readin/guide-10_in.dat used with weight 1.00000
             1..5 number of trajectories read/written : 1000 each
<verified_by_server>  STATUS: VERIFIED
  Executions: 5 -- completed (exit 0) x5
  Result artifacts delivered: guide_shape.dat; monitor1D.dat; monitor2D.dat;
                              output.dat; result.txt
  Produced but NOT delivered: geometry.inf, instrument.inf (type not allowed)
artifacts attached: ..., monitor1D.png
```

The 1D monitor was configured for wavelength over 0-12 A and the rendered PNG holds a
real spectrum between 3 and 6 A with error bars -- from a configuration that came out
of the validation tools, not out of the test.

#### What CP4 deliberately left

- **`vitess_ai/server/service.py`'s one import line.** There is no server module yet;
  it lands in CP6. `test_importing_the_agent_module_registers_exactly_the_vitess_agent`
  stands in for it until then, and the `agents/__init__.py` docstring names where the
  line goes.
- **The `agent_id`-on-resume check.** It belongs with the server, in CP6.
- **`RuntimeModelContext` carrying the project root.** The plan suggested it; the
  project root is deployment configuration read once from `VITESS_PROJECT_PATH` and
  passed to the builders, which is the same conclusion as "those become deployment
  configuration" and keeps core from learning what a VITESS project directory is.
- **The UI half of "Done when".** `vitess-app` still runs `sleep infinity` until CP6,
  so "in the UI" is CP6's check. Everything below the browser is proved above.

### CP4 post-completion review

Reviewed and corrected on 2026-09-17 in `Vitess-AI-Agent-v2` commit `ef21174`.
This section supersedes the stronger claims above where they describe the original
`e49d5f0` implementation rather than the reviewed one.

The golden test proved that its **scripted** supervisor delegated in order, but
`run_simulation` still checked only the set of `module_results`. Reversing all five
delegations reproduced the exact failure the plan warned about: the complete set passed
and VITESS executed in catalog order. The application boundary now appends a
server-authored `SimulationOrderEvent` whenever its own specialist returns a validated
configuration; `plan_simulation` appends the plan event; and `run_simulation` compares
the first occurrence of every module after the latest plan, element by element. A later
reconfiguration remains valid, while delegation before the latest plan or in a different
first-pass order is refused. A specialist-supplied event is discarded and replaced by
the boundary's own module name.

Four other boundary defects were found by adversarial tests:

- `schema_version` was recorded but never read. Execution now compares it with the
  current model, and the fingerprint covers the complete canonical JSON schema rather
  than only field names and flags. Old checkpointed configurations must be revalidated
  after a type, constraint, nested field, default or flag changes.
- The five parameter models still had Pydantic's default `extra="ignore"`. A misspelled
  field therefore passed validation and silently selected its default. All command-line
  parameter objects, including writeout's nested objects, now forbid unknown fields.
- Several promises existed only in descriptions and prompts: a read-in could have a
  different number of files and weights, a guide could have negative dimensions, and a
  monitor could have zero bins or reversed ranges. Those are model constraints now, as
  are writeout's filter ranges. NUL-bearing arguments are refused before process launch.
- Upload validation checked only that a path was somewhere under the conversation's
  `uploads/` tree. It accepted a read-in trajectory from the `instrument` slot and a
  nonexistent path. Each file field now names its catalog-owned slot and must resolve to
  an existing file there; the trace-file field is covered too. The read-in specialist's
  staged-file tool now lists both `readin` and `instrument`, which is necessary because
  `sInstrInfIn` is supplied by the separate catalog row.

The guide prompt also called the default enum `constant` while the schema says
`VT_LINEAR`; it now describes the actual default: linear with equal entrance and exit
dimensions, producing a constant cross-section.

```text
uv run pytest -q                                206 passed
juena-core delegation boundary                   7 passed
uv sync --frozen                                ok (187 packages audited)
wheel contents                                  supervisor + all five AGENT.md files
docker compose up -d --build                    image sha256:65fc24f03091...
vitess-app -> http://vitess-mcp:9005/health      healthy, both checks ok
real five-module MCP pipeline                    exit 0 x5
```

Both application containers use that same image. The real pipeline used the existing
staged trajectory, produced seven run files, and exercised the stricter models and the
reviewed converter before crossing the MCP boundary. The stack remains running; the UI
gate and service entrypoint remain CP6 work exactly as recorded above.

### CP4 second review — the prompts claimed more than the validator enforced

Reviewed and corrected on 2026-09-17, on top of `67cc612`. The review probed the five
**real** validation tools with ten configurations the prompts describe as impossible.
All ten were recorded as "valid and recorded". Two defect classes, one of them the same
shape as the one CP4's own review had already found once.

**Empty file names were skipped rather than checked.** Every file field was gated on
`if value:`, so a blank name went past both the staged-path check and the plain-filename
check without being looked at. `parameters_to_arguments` then drops an empty string, so
the flag vanished from the command line too — `sInputFileName=[""]` produced `-a1.0`,
the weight for input file 1, with no `-A` beside it, and read_in ran with nothing to
read and exited 0. The same hole swallowed writeout's `-A` and both monitors' `-O`.

Both layers were fixed, and the division between them is the point:

- **The schemas decide whether "no file" is allowed**, because only they can express
  the conditional case — `sOutFileName` may be blank exactly when `bActive` is false,
  which is writeout's documented way of running without writing, and a rule about
  another field cannot live in a generic helper.
- **`omitted_file_value` decides whether there is a file to check**, reading the answer
  off the field itself: `None` where the annotation admits it, blank where the field's
  own default is blank. That is what keeps `GuideParameters.ShapeFileName=""` working —
  the documented way to omit `-S` — with no second table of optional fields to fall out
  of step with the models.

The first attempt put the conditional rule in both places, and the new tests caught it
immediately: the tool layer refused `bActive=False, sOutFileName=""`, a configuration
the schema accepts. **Two layers that hold opinions about the same question are worse
than one layer**; two layers that answer different questions are what was wanted.

**Four physics rules existed only as prose.** `nRep=0`, `FactInt=0` on both read-in and
writeout, `eParX=NO_PAR` on monitor1D, and both axes `NO_PAR` with `NO_2D_FORMAT` on
monitor2D were all recorded while the module's own prompt said in as many words that
they could not be. `NO_PAR` (0) and `NO_2D_FORMAT` (-1) are sentinels this schema
invented — neither is in the VITESS parameter list or among its four documented 2D
formats — so a monitor configured with them asks VITESS to plot a quantity that does not
exist, and still exits 0. They are model constraints now.

**The VITESS documentation, not the prompt, settled each rule.** `rag/vitess-rag/data/`
gives `repetition >= 1`, `intensity factor > 0` and `colour >= -1` — which means the
prompt was the wrong one in exactly one case: writeout's said colour had to be "-1 for
no filter, or a positive integer", and `0` is a colour like any other. Refusing it would
have made a legal configuration impossible to express. The prompt was corrected to the
documentation and a test pins the direction, so it cannot be "fixed" back into the
schema later.

**One canonical order of work, in all five prompts.** Each prompt had described two
different orders in three places: PATH B ended "build, validate, present", the
guidelines said "present the final configuration before validating it", and the
validation rules ended "always validate the final JSON before presenting it". Monitor2D
managed to say "validate, then present the JSON" and, eighty lines later, "after
validation, return immediately". The sequence — collect, build, present, validate, stop
— is now one authored block pasted into all five, and a test asserts the five copies are
identical word for word, so an edit to one has to be an edit to all five. Presenting
before validating is the direction kept: it is the user's only chance to catch a value
that is legal and still not what they meant.

**`read_file` is gone, and so is the paragraph describing it.** The tool trim left every
specialist with `read_file` alone, on the theory that the delegation boundary carries
`/findings/` in so a later module could read what an earlier one recorded. It could not:
a `/findings/` file exists only because some specialist called `write_file`, none of
these five has it, and without `ls` or `glob` there is no path to guess at. These
specialists hand off through `module_results`, a typed state channel. Since `read_file`
is mandatory in any allowlist `FilesystemMiddleware` accepts, core gained
`filesystem_tools=None` — mount the middleware not at all. Core also now rejects a bare
string: `Sequence[str]` admitted `"read_file"` by its type and turned it into eight
one-letter tool names.

**The prompt/tool regression test did not enforce its own guarantee.** Its docstring
claimed it would catch read-in's historical `get_instrument_file` and
`instrument_file_status`, but its regex matched a hard-coded list of tool names — so
putting either back would not have matched the pattern at all and the test would have
passed. It now reads **every** snake-case backticked word as a tool name and subtracts
the ones that provably are not: parameter fields come from the models, executables from
the catalog, and three VITESS 2D format names from a named list, because their enum
members are spelled `MATR_CMPT`, `MATR_INT` and `XYZ_CMPT` and cannot be matched to the
lower-case names the documentation uses. Separately, the one sanctioned prompt-versus-
schema exception — read-in's `sInstrInfIn`, which the prompt must set to `null` rather
than to the schema's unusable `instrument.inf` — was *skipped* rather than asserted, so
the prompt could have drifted to any other value and the test would still have passed.
The exception now carries the required value.

```text
uv run pytest -q (v2)                            257 passed  (was 221)
juena-core                                       476 passed  (+2; same 2 failed,
                                                 24 errored as before the change --
                                                 all socket-bound, pre-existing)
./juena test (chatbot, against the changed core) 232 passed
ten deliberate breaks                            8 caught directly, 2 masked by the
                                                 other layer and caught when both
                                                 were broken together
argument vectors before vs after                 byte-identical
live five-module pipeline                        exit 0 x5, 7 files, both plots
```

The live run is the one worth reading twice: its `cli_parameters` are **produced by the
five real validation tools**, not hand-written, so a validator that had started refusing
something VITESS needs would show up as a missing flag or a non-zero exit code rather
than as a passing unit test. Five exit codes of 0 and a 3–6 Å spectrum with error bars.

---

### CP4 third review — the validator claimed more than VITESS requires

A further round of review fixes arrived uncommitted: read-in weights bounded and summed,
`allow_inf_nan=False` on every CLI-bound float, a shared monitor-filter validator, an
`ask_user` confirmation between presenting and validating, and a tool-name test that
finally sees one-word tools such as `execute` and `ls`. Its own note said the monitor
rules were inferred from the pinned documentation and the repository's examples, because
the upstream source was behind a browser check.

That is the sentence worth acting on. **The documentation is silent on filter
completeness, so the binary is the authority** — and `vitess-mcp` has a real VITESS 3.8
build in it. Every rule was measured on a 1000-trajectory beam whose unfiltered total is
6.01e10, by piping `read_in` into `monitor1D` and summing the monitor file.

Six of the new rules were checked. **Three are right, and for stronger reasons than
were given:**

| Half-written form | What VITESS 3.8 actually does |
|---|---|
| `-l4` with no `-L` | monitors **0** — the window is λ ∈ [4, 0] and keeps nothing |
| `-L12` with no `-l` | no filtering at all |
| `-u-0.5` with no `-U` | 3.87e10 — a filter on [-0.5, 0] that nobody asked for |
| `-I1` with no bounds | no filtering at all |
| `-u`/`-U` with no `-I` | no filtering at all |

A missing bound is **0**, not "no bound", and the run exits 0 either way. So a filter is
all three flags or none of them — and the lambda pair, which the review had not covered,
belongs to the same rule and is now in it.

**Three refuse configurations the binary handles correctly**, which is the CP4 defect
class pointed the other way — the `iDetectColor=0` case again:

- **`[1.0, 1.0]` is a correct answer to "weight the two files equally."** read_in divides
  every weight by their total: `[1.0, 1.0]`, `[0.5, 0.5]` and `[0.1, 0.1]` all monitor
  4.19578e10, and `[2.0, 6.0]`, `[0.5, 1.5]` and `[0.25, 0.75]` all monitor 3.2863e10.
  Only the ratio survives. The VITESS sentence "their sum should give 1" is a
  readability convention, not a condition the binary imposes, and a validator enforcing
  it refuses a correct simulation over its spelling. The bounds stay — 0.0–1.0 is
  documented, and a negative weight is nonsense — the sum rule goes, and the prompt now
  teaches the normalisation instead of asserting the sum.
- **Filter 2 works on its own.** `-J5 -v4 -V12` with no filter 1 monitors 4.15848e10,
  identical to the same filter in slot 1.
- **A combination with fewer than two filters changes nothing.** One complete filter
  monitors 1.62002e10 whether the combination says `NO_FCOMB`, `AND` or `OR`.

**And one rule the review got right for the wrong reason, which is the find of this
round.** `NO_FCOMB` is not "no combination". With both filters complete, `-C-1` (the
schema default), `-C0` and `-C2` all monitor **4.63264e10** — the union — and only `-C1`
monitors **1.14587e10**, the intersection. A user who configures two filters and leaves
the combination alone has silently chosen OR and gets four times the beam. So
`filterComb` is required exactly when both filters are in use, and nowhere else. The
loop was closed end to end: the vector the real `validate_monitor1d_parameters` produces
for two filters and `AND_AND_AND` —
`-I1 -J5 -C1 -u-0.5 -U0.5 -v4.0 -V12.0` — monitors 1.14587e10 against the real binary,
and the configuration now refused monitors 4.63264e10.

The `ask_user` confirmation was checked against the first-generation prompts rather than
kept on taste: their `DO NOT ask for any confirmation` is **post-validation** behaviour,
which THE ORDER OF WORK already carries in step 6. Nothing in v1 objects to confirming
before recording, so the step stays, now as step 4 of six in all five prompts.

`test_a_rule_a_prompt_states_is_a_rule_the_validator_enforces` was itself half a test:
its third column was a comment, and two of its claims appeared in no prompt at all. It
now asserts the prompt says the thing before proving the validator enforces it.

```text
uv run pytest -q (v2)                     308 passed  (was 257 at CP4, 296 as reviewed)
twelve deliberate breaks                  12 caught, after splitting one weight case
                                          that covered two bounds and neither
argument vectors before vs after          byte-identical to CP4's
validator vector vs real monitor1D        1.14587e10 (AND) against 4.63264e10 (default)
```

The weight-bound case is worth keeping in mind: `[-0.1, 1.1]` looks like it covers both
bounds and covers neither, because deleting either one leaves the other value still out
of range. One case per bound.

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
| **Executed** | checkpoints 0, 1 and 2 complete in `Vitess-AI-Agent-v2`, suite at 50 passed. CP0 `5ba4aeb`: the five parameter schemas ported verbatim, every leaf field carrying a CLI flag. CP1 `8cd7b8d`: `generate_cli_command` as a pure function emitting argument vectors, with an MCP-side runner that never builds shell text. CP2 `06ea450`, reviewed in `d33925e`: the catalog as pure data — importing it pulls in neither `langchain` nor `deepagents`, executables are basenames, the three `path_only` rows are gone and their filenames are asserted to still be owned by the parameter schemas; the review added exact row, field, import-surface and direct-dependency guards. CP3 `4e21722`, reviewed in `cd7ffe6`: the FastMCP server as an internal Compose service with an explicit `/health` route, four exactly allowlisted tools, one pinned image run by two services sharing `/data/projects`, and a new monitor-file reader covering all five layouts `Monitor2DParameters.format` can ask for — proved by a real five-module VITESS pipeline run over MCP from the application container; the review added event-loop isolation, volume-boundary enforcement, unique-run evidence, concurrent health safety and reproducible VITESS/uv pins. CP3a `c2fdfbd`: the sole typed MCP gateway, four closed model façades, private run references, verified application-side file registration and the two root delivery middlewares — proved by a real five-module run and PNG plot through the application container. CP4 `e49d5f0`, with `juena-core` `08c013c`: the simulator rebuilt on `create_agent` and `SubAgentMiddleware` with **no legacy fallback** — `plan_simulation` writes the pipeline order into private state and `run_simulation` reads it back, so the order is a checked precondition rather than a graph shape; five explicit module specialists each with their own `AGENT.md` and one validation tool that is the sole writer of a typed `ModuleConfigurationResult`; one parameter-to-argument converter replacing five that had drifted; and a delegation boundary that returns a specialist's own module and nothing else. The three-order golden test compares what was planned, what was delegated and what was executed element by element, and fourteen deliberate breaks were caught. Proved by a real five-module VITESS run driven by the real validation tools from inside the application container. The module prompts were then restored to the originals' full detail -- the first pass cut them to a third of their length, which is wrong for a model that has to be told an m-value above 6 does not exist -- and each specialist's tool surface was narrowed from eleven tools to four, `execute` and `delete` among those removed (`f55e140`, with `juena-core` `4cd5969`). Suite at 216 passed. CP5 is next |
| **Decided** | schemas ported verbatim and kept out of core; `generate_cli_command` becomes a pure function in `cli/command.py`, building **argument vectors** rather than shell text; catalog becomes pure data carrying `cli_executable` and `accepts_upload` independently; **MCP is an internal Compose service sharing a volume**; simulator rebuilt with **no legacy fallback**; two registered agents rather than one supervisor; **PNG artifacts canonical**; Chroma stays; fixed local principal; **per-module upload slots kept, the three `path_only` rows deleted, sidebar becomes a manifest, `ask_user` is the second way in** |
| **Open** | whether `research/` should come into core after all, once a sweep is lost to a closed browser (CP5); whether a run manifest on the volume is needed alongside the returned metadata (CP3a); whether content classification of uploads is worth adding — *reopen when files start arriving from other people, or in bulk* (CP6) |
| **Revised** | 2026-09-15 after [REVIEW.md](REVIEW.md) — Compose topology replaces the host process, CP3a added for the evidence bridge, argument vectors replace shell text, recursive flag test, `simulator_legacy` dropped, real order test, `agent_id`, binary uploads separated |
| **Revised** | 2026-09-15, upload workflow — `cli_executable` and `accepts_upload` are independent, the three `path_only` rows deleted as duplicates of existing schema fields, sidebar becomes a manifest, `ask_user` added as the in-chat route |
