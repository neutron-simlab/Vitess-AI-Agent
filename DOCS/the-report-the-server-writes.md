# The report the server writes when the model does not

## What was wrong

A readin specialist run did everything right. It listed the staged file, asked the user
for the weight, asked for confirmation, and called `validate_readin_parameters`. The
tool succeeded and wrote the configuration into the `module_results` channel. Then the
supervisor was handed this:

```
<specialist_report>
None returned.
</specialist_report>

<verified_by_server>
Specialist: readin-specialist
STATUS: UNVERIFIED
- The specialist returned no structured report. Its run ended early -- most often
  because the model-call budget was exhausted -- ...
Tell the user this attempt failed and say why.
</verified_by_server>
```

The supervisor did as it was told and informed the user that the specialist "didn't
have enough information" — while the module was, in fact, configured. Across the three
threads run that day there was not a single `STATUS: VERIFIED`.

## Why it happened

It is tempting to say the middleware failed to notice the successful validation. It did
not: `module_results` is in the specialist's state and any middleware can read it —
`GuidedAskUserMiddleware` already does. What was missing was a **report** to pair the
recorded configuration with, and there are two separate reasons one never arrived. Both
are in LangChain's `create_agent`, in `langchain/agents/factory.py`:

1. **A prose sign-off ends the run before structured output is considered at all.** The
   agent's routing function returns "end" the moment the latest assistant message has
   no tool calls. That check sits *above* the one that looks for a structured response.
   So when GPT-OSS-120b finished with `✅ Configuration validated and recorded.`
   followed by `**Finding**` / `**Evidence**` / `**Limitations**` as ordinary text, the
   subgraph simply stopped. There is no retry and no nudge to call the report tool.
2. **A report emitted in the same turn as another tool call is captured and then
   wiped.** Because these specialists are built with `response_format=...`, the agent
   explicitly resets `structured_response` to empty on any model response that did not
   produce one — so the next model call erases a report that had been captured.

The prompt helped it along. `readin/AGENT.md` has a `## YOUR REPORT` section that lists
the field names but never says the report is a *tool call*, and step 6 of its order of
work says "one short confirmation line and your report". The model satisfied that
literally, in prose.

Core's `SpecialistOutcomeMiddleware` decides VERIFIED purely on `structured_response`.
That is **correct for juena-chatbot**, where a research specialist's report is the only
thing it produces — if the report is missing, nothing happened. It is wrong for a
module specialist, whose deliverable is the `ModuleConfigurationResult` its validation
tool wrote. That object is the one thing in the subgraph a model cannot author. The
report is only how it gets narrated, and narration is the part a weak model drops.

## The fix

One new middleware, `ModuleReportMiddleware`, in `module_specialist.py` next to
`GuidedAskUserMiddleware` — its sibling, since both exist to rescue the same prose exit.
When `structured_response` is empty *and* this module's entry is recorded in
`module_results` (or `module_variants`, for a sweep), it writes the report from the
recorded result: the parameters' one canonical command line, the timestamp, and the
schema fingerprint.

**No changes to juena-core.** Research specialists in juena-chatbot keep failing closed
exactly as before.

Two details worth knowing:

- **It runs before core's middleware, and that is not luck.** Middleware `after_agent`
  hooks run in *reverse* order of the middleware list. Core mounts
  `SpecialistOutcomeMiddleware` first, so it runs last — it is the exit node. Anything
  appended to the end of the list therefore runs first on the way out, and its state
  write has landed by the time core reads it. Each hook is its own graph node.
- **The report says the server wrote it.** There is a line in `limitations` stating that
  the specialist ended without returning a report and nothing it said mid-run is
  included. Without it the supervisor would present server-authored narration as the
  specialist's own reasoning — and the whole point of the `<verified_by_server>` block
  is that the reader can tell who is speaking.

The command line is rebuilt with `parameters_to_arguments` rather than stored, which is
the rule `ModuleConfigurationResult` already sets: two answers to "what does this run
as" drift apart. It is wrapped in a narrow `except` — not padding for an impossible
case, but for the one real case `schema_version` exists to catch, a configuration
checkpointed under a schema that has since changed. That degrades to a report without
the command line rather than losing the report.

## What was considered and rejected

- **Making `module_results` the proof and rewriting the block.** The first design had a
  replacement for core's middleware that authored its own `<verified_by_server>` block
  for module specialists — dropping `Executions: none.` and `Result artifacts
  delivered: none.`, which are constants for these specialists (no execution
  middleware, no filesystem) and read as failure while carrying no information. It also
  needed a new parameter on core's `build_specialist_middleware` so the outcome
  middleware could be substituted. Rejected as too much: those two lines are noise but
  not *wrong*, and rewriting core's block format for one application buys nothing the
  filled report does not already buy.
- **Keeping the report mandatory and reporting the configuration beside it.** Would
  have left the supervisor still being told the attempt failed, which is the actual
  damage.
- **Only fixing the prompt.** Telling `## YOUR REPORT` that the report is a tool call
  would reduce how often this fires but cannot replace the fix — the model can always
  drop the call, and then nothing catches it.

## Left alone on purpose

- `NO_REPORT`'s claim that the budget ran out. It is false for this incident — the
  loop-guard counter shows the budget was never near exhausted — but module specialists
  no longer reach that sentence once a recorded configuration yields a report. Fixing
  the wording is a one-line core change for its own commit.
- `GuidedAskUserMiddleware` goes inert as soon as the module result exists, which is
  precisely the window this bug lives in. That is deliberate on its part — it must not
  interfere with a final report — and is exactly why the rescue had to be a separate
  `after_agent` hook rather than an extension of it.

## How it is tested

In `tests/test_module_configuration.py`, under "The report the server writes when the
model does not". Every test feeds the middleware state produced by the **real**
validation tools, through the existing `configured_modules` and `swept_modules` helpers,
rather than a hand-written dict — a hand-written dict would only prove the middleware
can parse dicts, not that the branch is reachable from a validation that really
succeeded.

Five tests: the incident itself; the model's own report being left alone; a failed
validation still reading UNVERIFIED (the fail-closed guarantee); the sweep path; and an
end-to-end run through `create_agent` with both middleware in the real mounting order
and a fake model that calls the real validation tool and then signs off in prose.

That last one earned its keep immediately — it failed on the first run because the test
input left `sInstrInfIn` at its schema default, the bare name `instrument.inf`, which
validation deliberately refuses. The code was right and the test input was wrong, which
is the failure mode a real-producer helper prevents everywhere else.

Sabotaging the middleware (`_fill` returning nothing) fails exactly three of the five
and leaves the other two passing, which is the check that they exercise it at all.
