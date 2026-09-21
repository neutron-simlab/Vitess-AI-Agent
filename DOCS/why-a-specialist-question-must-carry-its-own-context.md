# Why a specialist's question has to carry its own context

Two complaints, one cause.

1. The confirmation card asked *"Here is the configuration based on your request. Does
   it look correct?"* — with no configuration above it. Nothing to check, every time.
2. The monitor1d and monitor2d specialists asked about parameters the user had never
   heard of, instead of first offering sensible defaults.

## The cause

**A module specialist's own messages never reach the user.** The server drops them, in
two places, deliberately:

- `juena-core/src/juena_core/server/streaming/processor.py`, in `_handle_message`:
  `if from_subagent and chat_message.type == "ai": return` — *"A specialist's final
  report is input to the supervisor, not an answer for the user."*
- The same file, for the `messages` stream mode: a subagent's tokens become a
  *"Consulting a specialist…"* status and nothing else.

That policy is right. A specialist's report is raw material the supervisor synthesizes
from, and letting its running commentary into the chat would put two voices in the
conversation. **But it means the only specialist text a user ever sees is an `ask_user`
question.** The interrupt payload carries `question` and up to four `options`, and that
is the whole channel.

Both prompts were written against the opposite assumption. `THE ORDER OF WORK` said:

> 3. **Present** it to the user, formatted, before it is recorded.
> 4. **Confirm** it with the user. Call `ask_user` with one direct question...

Step 3 wrote into a message that is discarded; step 4 then asked about it. Hence a
question with nothing above it. `chat_interface.py`'s own docstring had recorded the
intended design — *"the specialist presents it and calls `ask_user`"* — so the
assumption was written down; it just was not true.

The second complaint is the same bug wearing a different hat. The defaults-or-custom
choice **was** already ported from v1 — every one of the five prompts has
`STEP 0 — ASK WHICH SETUP THE USER WANTS`, with PATH A (Default Setup) and PATH B
(Customize) — but it was framed as *"Open with a short greeting and this choice"*. An
opening greeting is a message, so it was invisible. The user never saw the choice, the
model carried on, and PATH B's parameter-by-parameter interrogation is what arrived.

So v1's solution was not missing. Its **delivery** was.

## The fix

All five prompts now route both moments through `ask_user`:

- `STEP 0` says to put the choice through `ask_user` *as the very first action*, with
  `options: ["Default setup", "Customize"]` so it is one click.
- `THE ORDER OF WORK` gained the setup choice as step 1 and merged the old steps 3 and
  4 into one: **show it and confirm it in a single `ask_user` call, with the complete
  formatted configuration inside the question text.**
- Every `Present ...` instruction in PATH A and PATH B became a *format it for the
  question* instruction.
- A paragraph at the top of `THE ORDER OF WORK` states the underlying fact, because a
  rule whose reason is invisible is a rule the next editor undoes.

The block is authored once and pasted into all five, and
`test_every_prompt_carries_the_same_order_of_work_word_for_word` keeps them identical.

Nothing in `juena-core` changed. The question text renders through `st.write`, so a
```` ```json ```` fence in the question displays as a code block — verified by
rendering the real question card with Streamlit's `AppTest`.

## What was considered and rejected

- **Letting module specialists' messages through.** One flag in the stream processor.
  Rejected: it would put every specialist's commentary — *"Let me check the schema…"* —
  into the chat beside the supervisor's, which is the exact noise the policy exists to
  suppress, and it would affect juena-chatbot's research specialists too.
- **Deriving the configuration server-side for the confirmation.** There is no source
  to derive it from at that moment: the model holds the object and only the validation
  tool ever sees it, which happens *after* confirmation. The prompt is the only lever.
- **Folding preceding prose into the question automatically.** Extend
  `GuidedAskUserMiddleware` so text in the same message as an `ask_user` call is
  prepended to the question. This would survive a model that ignores the prompt, which
  is a real risk — this model has ignored instructions before. Not done, because it can
  just as easily prepend reasoning to a question and make it worse. Worth revisiting if
  the prompt fix proves not to hold.

## Tests

In `tests/test_module_configuration.py`, under "What the user can actually see of a
specialist":

- `test_a_specialists_own_messages_never_reach_the_user` drives core's real
  `StreamEventProcessor` with a subagent-namespaced update and a supervisor one, and
  asserts the first yields nothing and the second yields an event. This is the fact the
  prompts are written around, pinned so the prompts and the stream cannot part company.
- `test_every_prompt_puts_the_setup_choice_through_ask_user` (×5) checks `STEP 0` names
  `ask_user`, passes both options, says it is the first action — and that
  *"Open with a short greeting"* has not come back.
- `test_every_prompt_keeps_the_configuration_inside_the_question` (×5) bans every
  instruction that would put the configuration in a message of its own.

Three existing guards were updated rather than worked around, because their subject
genuinely changed: the six step labels in
`test_every_prompt_carries_the_same_order_of_work_word_for_word`, the present-before-
validate ordering in `test_no_prompt_tells_the_model_to_validate_before_presenting`
(now confirm-before-validate over the merged step), and `options` added to
`PROSE_WORDS_THAT_LOOK_LIKE_TOOLS` so `ask_user`'s argument is not read as a tool name.

---

## Follow-up: the choice itself had the same problem

Routing `STEP 0` through `ask_user` made the choice *visible*. It did not make it
*answerable*, because of what the two options said:

| module | what "Default Setup" offered |
|---|---|
| guide | "a 3 x 3 cm constant guide, 50 cm long, with m-value 3.0" |
| readin / writeout | what the user still had to supply |
| monitor1d / monitor2d | "use optimal default values for the 1D/2D monitor" |

The two monitors named nothing at all — and they are the two that were reported as
interrogating the user about every parameter. That is the same complaint one step
earlier: a user who cannot see what Default Setup means cannot pick it, so Customize
looks like the only way to find out what the values are, and Customize walks the schema.

So the specialist has to *say* what the defaults are. It knows them twice over — each
prompt carries a `DEFAULT CONFIGURATION` block, and `build_module_prompt` appends the
full JSON schema — and `test_the_default_configuration_in_each_prompt_is_the_schema_default`
already pins that block to the schema. Nothing told it to pass them on.

`STEP 0` now requires the question to state the quantity measured, the range, the bin
count and the file name, taken from that block. Both monitors and writeout gained
concrete text.

### A second drift found on the way

`guide`'s choice said "a **constant** guide". `eGuideShapeY`/`eGuideShapeZ` default to
`1`, which is `VT_LINEAR`; `VT_CONSTANT` is `0`. The entrance and exit are both 3 x 3,
so the guide does not taper and the *picture* was right, but the word was the name of
the setting it is not.

This is the same pairing the JSON-block test was written for — its docstring records
catching `VT_CONSTANT` where the schema said `VT_LINEAR` — which had simply moved into
prose, where no test looked. The wording is now "a straight 3 x 3 cm guide — entrance
and exit the same", and
`test_the_setup_choice_names_no_enum_value_the_default_is_not` closes the hole
generally: for every enum in a module's schema, the choice may not name a member that
is no field's default. Values are grouped by enum type, because one enum serves several
fields and each brings its own default — monitor2d measures POS_Y *by* POS_Z, and
neither is a value it "would not use".

Both new tests read their expected values from the schema rather than from a list kept
in the test, so a default that changes fails them until the choice is updated. Verified
by restoring guide's original wording: the guard fails with
*"says 'constant', but no VtGdeShape field defaults to it"*.
