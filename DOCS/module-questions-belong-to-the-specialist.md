# Module questions belong to the specialist

## What went wrong

A real run, thread `fc436612-97b9-4cd4-85c5-38e5ed770120`. The whole conversation was
four messages, read straight from the Postgres checkpointer:

1. User: *"I want to run a VITESS simulation. Walk me through configuring the five modules."*
2. Supervisor calls `plan_simulation` → `readin -> guide -> writeout -> monitor1d -> monitor2d`.
3. Supervisor calls `ask_user` **itself**: *"For the readin module, which neutron trajectory
   file would you like to use (provide the filename you have uploaded), what is the weight
   factor for the neutrons, and which instrument file should be associated (if any)?"*

It never called `task`. So the readin specialist never ran, and its opening — the
*"Hello! 👋 I'm the Read-in Agent"* greeting with the **Default setup / Customize** choice
(`STEP 0` in `readin/AGENT.md`) — never appeared. That opening is the one place the user is
told what the defaults are. The "missing greeting" and "the supervisor asking about module
details" are one bug seen from two sides.

## Why the model did it

Nothing in `SUPERVISOR.md` forbade it clearly, and two lines invited it:

- The tool list said `ask_user` is for *"when a decision cannot be inferred safely"*. A
  trajectory file the user has not named is exactly such a decision, read literally.
- The delegation rule said *"Give it a self-contained objective: what the user wants from
  this module"*. The same wording is in the `task` tool's description
  (`SUPERVISOR_TASK_DESCRIPTION` in `vitess_agent.py`). A weaker model reads that as
  "find out everything the user wants first, then delegate".

The only guard was half a sentence at the end of *Talking to the user*: *"do not ask a
question a specialist is about to ask"*. That asks the supervisor to predict what a
specialist will ask, which it cannot see.

For comparison, the first generation never had this problem because its supervisor had
**no** `ask_user` at all — it was a router that greeted and handed over.

## What changed

Prompt text only, all additions, nothing removed:

- **`SUPERVISOR.md`, tool list** — `ask_user` *"is never for a module's own values"*, with
  a pointer to the rule below.
- **`SUPERVISOR.md`, The order is not yours to choose** — *"Delegate as soon as
  `plan_simulation` returns."* Self-contained means passing on what the user **has already
  said**, not collecting what they have not; if they said nothing, the objective is simply
  "configure it with them".
- **`SUPERVISOR.md`, Talking to the user** — a bold rule: *every question about a module
  belongs to that module's specialist, and only to it* — files, weights, parameters,
  whether to take the defaults. It says why: the specialist opens with its greeting and
  its default-or-customize choice, and it still does so after the supervisor has asked, so
  the user would be asked twice, the first time with no defaults offered.
- **`SUPERVISOR_TASK_DESCRIPTION`** — one line: pass on what the user already said; do not
  ask them about the module first; the specialist greets them and asks itself.

## What was considered and rejected

- **Take `ask_user` away from the supervisor**, as in the first generation. Rejected: the
  supervisor still needs it for real simulation-level decisions — whether a failed module
  should be reconfigured or abandoned — and the documentation policy uses it to ask which
  module the user means when a lookup is ambiguous.
- **A code guard** that refuses the supervisor's `ask_user` while a planned module has no
  configuration. Rejected for now: a question about a failed module comes at exactly that
  moment and is legitimate. Telling a "module question" from a "simulation question" would
  mean reading the question's text, which is a guess dressed as a rule. Worth revisiting
  only if the prompt stops holding.
- **Let the supervisor collect the answers and hand them to the specialist.** That is what
  the model was trying to do. It still skips the defaults offer, and the specialist opens
  with `STEP 0` regardless, so the user answers twice.
- **A supervisor greeting**, like the first generation's mandatory one naming the modules.
  Not added: the specialist already greets, and two greetings in a row is noise. The
  supervisor's existing instruction to *"say what you are doing as you do it"* covers
  telling the user where they are.

## How it was checked

- No pytest guard was kept. One was written to pin the new sentences, then removed: it
  only protects wording from being edited away and says nothing about whether the model
  obeys it, so it is not worth its upkeep for a prompt-only change.
- **Obedience was checked on the real app.** Rebuilt with `./vitess up`, then sent the same
  opening message through the real `/vitess/stream` endpoint three times, on fresh threads
  `3f1e3dde…`, `2e156e54…`, `8ccabd75…`. All three: `plan_simulation`, then straight to the
  readin specialist, whose first event was the *"Hello! 👋 I'm the Read-in Agent"* question
  with `options: ["Default setup", "Customize"]`. The supervisor asked nothing itself.
- Not measured: how often the old prompt failed. The only evidence is the one user run,
  so 3 of 3 is encouraging, not proof.
- Full suite, run once before the guard was removed: 478 passed.

## Files

- `src/vitess_ai/agents/SUPERVISOR.md`
- `src/vitess_ai/agents/vitess_agent.py` (`SUPERVISOR_TASK_DESCRIPTION`)
