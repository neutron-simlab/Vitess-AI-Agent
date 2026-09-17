# Documentation retrieval, and why it is wired the way it is

Plain-language note for whoever touches `src/vitess_ai/retrieval/` next.

## What this does

The VITESS manual is indexed into a Chroma database. Four tools search it:
`vitess_search` for a broad question, `vitess_option_lookup` for a flag,
`vitess_module_lookup` for one module, and `vitess_debug_retrieval` for when
retrieval itself looks wrong.

Before this change, only the five module specialists could search, and they got
three of the four. The agent a user actually meets first — the guided `vitess`
supervisor — had none. So "what does `-z` do?" could only be answered by first
delegating to a module specialist, which means already knowing which module the
flag belongs to. That is the question.

Now both supervisors hold all four, and the specialists keep their three.
`vitess_debug_retrieval` is for noticing that retrieval is answering badly, and
only an agent that sees the whole conversation can notice that.

## The one rule worth keeping

**A prompt must never name a tool its agent does not hold.** A weaker model
follows the prompt, calls the missing tool, and has no instruction for what to
do next. This is the failure the whole design is arranged around.

The old code let the two drift apart in three places at once: advanced mode
bound tools in its *factory* but appended the policy in its *graph builder*, so
anyone building a graph directly — which is what every test does — got a prompt
naming four tools that were not there. And `build_module_prompt` appended its
retrieval note unconditionally while the tools defaulted to none.

The fix is not a test. It is `orchestrator_documentation(unattended=...)`,
which returns the tools and the policy *together*, so a caller cannot take one
without the other. `build_module_prompt` appends its note only when it is
handed the matching tool objects. The invariant holds by construction; the
tests only confirm it.

## Two policies, not one

Guided mode resolves an ambiguous flag by asking: `ask_user`. An unattended
sweep has no user and deliberately has no `ask_user` tool, so the same sentence
would tell it to call something it does not have — the exact mistake above.
`SWEEP_RAG_POLICY` instead tells it to retry with its own module named, then
record the reading it chose under `limitations`.

## Failing well

Retrieval can be absent in a perfectly good deployment: the index is built by a
separate command that spends embedding quota. So the tools are always present
and answer `RAG_UNAVAILABLE` rather than disappearing.

That was only handled while the tools were being *built*. But Chroma embeds
every query, so an expired key first shows up when the model invokes a tool
that was bound successfully minutes earlier. Each real tool is now wrapped in a
plain `try`/`except`.

Three details in that wrapper are deliberate:

- It catches `Exception`, never `BaseException`. Swallowing `CancelledError`
  turns a cancelled request into one that never ends.
- It degrades **per call**. Flipping the process-cached tool set to stubs after
  one 429 would make a ten-second outage last until the container restarted.
- It keeps the real tool's name and description. The description is what the
  model reads to decide whether to call it.

The raw exception stays in the server log. An invalid key was observed to arrive
as `AttributeError: 'str' object has no attribute 'data'` — the OpenAI SDK
parsing an error body as an embedding response. Relaying that to the model sends
the user toward application code, not the setting they can fix. The tool result
instead tells the user to verify `BLABLADOR_API_KEY`, `BLABLADOR_BASE_URL`, and
index readability, while the log retains the exception type and traceback for
an operator.

## Rejected approaches

- **`BaseTool.handle_tool_error`.** Looks like the one-line version of the
  wrapper. It is not: it handles `ToolException` only, and these tools raise
  whatever Chroma and the OpenAI client raise. Checked against the LangChain
  reference rather than assumed.
- **Filtering the index to modules this app can run.** The manual documents
  `filter`, `bender`, `guide_ideal`, `mon1` and others that this application
  cannot execute — about half the indexed rows. Dropping them destroys the
  honest answer ("VITESS has it, this application does not run it") and leaves
  silence. Filtering by metadata at query time is no better, because the module
  label is derived heuristically from headings. The caveat is in the prompt
  instead, and it interpolates the runnable five from `execution_order()` so it
  cannot go stale.
- **Backticking those module names.** The prompt/tool test reads every
  backticked lower-case token as a tool name, so `bender` would break it — and
  `filter2D` would not, which is worse, because it makes backticks look safe.
  They are bold.
- **Editing the `vitess-rag` submodule** to bound its embedding client. It is a
  reusable package; deployment policy belongs here. `build_embedding_function`
  swaps in a client built from `VITESS_RAG_QUERY_TIMEOUT_SECONDS` and
  `VITESS_RAG_MAX_RETRIES`, and closes the one it replaced — otherwise every
  graph construction leaks an idle HTTP transport.
- **A `vitess seed-index` command** for copying the first-generation index. It
  would bake a one-time migration into a permanent surface, named after another
  Compose project's volume, and keep working against a stale index long after
  anyone remembered why. The commands are in `README.md` instead.

## Things that will bite you

- `get_rag_tools()` is `lru_cache`d, so a graph first built against an empty
  index keeps its stub tools for the life of the container. Rebuilding the
  index must restart `vitess-app`.
- The copied index must be owned by uid 10001. SQLite writes journal files even
  to read, and a root-owned copy surfaces as `RAG_UNAVAILABLE` — which looks
  exactly like "no index".
- After any re-index, check `collections.config_json_str` is still `{}`. Chroma
  1.5.9 refuses to reopen a collection whose persisted config names an
  embedding function its registry does not know.
