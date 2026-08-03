---
name: skiff-pipeline
description: "Use when a small build needs to go end to end on a small project — often solo or two-person, often with no deployed environment and no test suite yet — and the full architect-team pipeline would cost far more than the job is worth. Also use when a run must not be able to start by reflex, when spend must be predictable ahead of time, or when repeated failure must stop and report rather than quietly hand the work to a bigger, more expensive team. Accepts either a requirements folder or a plain-language description typed directly as prose."
---

# skiff-pipeline

A small boat. It carries a few people a short distance, and you can see the whole
thing from where you sit.

The full pipeline is correct-by-construction at 8 stages and 26 helpers, and
that is the right shape for high-stakes work in an unfamiliar codebase. It is
the wrong shape for a solo builder adding a feature to a project they started
last week. skiff is the second shape: same spirit, a fraction of the spend, and
a hard stop before anything expensive happens without a person saying so.

Three things make it different from every other pipeline in this plugin, and
they are the whole point:

1. **Nothing starts until the user reads a summary and types a word that changes
   every run.** No reflex starts.
2. **Spend is looked up, never decided in the moment.** The same request twice
   produces the same helpers on the same models.
3. **Repeated failure stops.** Handing the work to a bigger team is something
   the user opts into, up front, in advance — never something that happens to
   them.

## Inputs

The requirement comes in one of two forms, both fully supported:

1. **A folder** — a path that resolves to a directory of requirement artifacts.
2. **Prose typed directly** — the words themselves are the requirement.

Never refuse prose. Never treat the first word of a sentence as a path. Ask only
when the requirement is genuinely empty. The project is the current directory
unless the requirement names another path.

## The seven steps

Plain names on purpose. This pipeline does not number its stages, and it never
starts counting below zero.

| Step | What happens |
|---|---|
| **Understand** | Read the request. Look at the project. Work out what is and is not already here. |
| **Confirm** | Read it back in plain words. Wait for the go word. Nothing before this point spawns a helper. |
| **Plan** | Write the OpenSpec bundle. Still mandatory — a small build is not an unplanned one. |
| **Build** | Do the work, naming the model for each helper from the table. |
| **Check** | Prove it works against a running app. Write the tests if there are none. |
| **Decide** | On repeated failure, do what the user said at Confirm. Default: stop. |
| **Report** | What ran, on what, how often it retried, what it cost. |

---

## Step 1 — Understand

Read the requirement. Then establish the four facts that decide whether the
cold-start path applies:

- Is there a test suite?
- Is there a way to run the app locally?
- Is there a deployed environment?
- Is there a git remote?

**A "no" to any of these is not a failure and not a blocker.** It is a fact that
shapes the run. Record all four; they feed the readback and the Check step.

## Step 2 — Confirm — the pre-flight gate

**This is a hard gate. No helper is spawned, no file is written, and no model is
dispatched before it passes.**

### Register

Write it the way you would explain it to a capable adult who does not write
software. Match the user's own words back to them wherever you can.

**Banned from this exchange entirely:** *phase, dispatch, coverage map, oracle,
parity verb, VAO, ralph loop, solution requirement, fan-out, convergence, gate,
orchestrator, agent tier.* If a concept cannot be said plainly, say it plainly
anyway or leave it out. The user reads this to decide whether to spend money;
vocabulary they have to decode is a tax on that decision.

### The five beats

Cover all five. Exact wording is yours.

1. **What it heard.** Restate the job in the user's own terms. *"You want to
   build ____. Right?"*
2. **The brain it will use.** Name the model plainly and offer the change.
   *"I'll use Opus 5, the strongest one. Want something different?"* State the
   helper count and mix here too — this is where cost becomes visible before it
   is spent. Get the line from `scripts/skiff/tiers.py preview --plain`.
3. **What happens if it struggles.** State the stopping rule and offer the
   change. *"If I can't get it right in three tries, I'll stop and come back to
   you rather than hand it to a bigger, more expensive team. Want me to escalate
   instead?"*
4. **Anything else.** *"Any other changes before I start?"*
5. **The go word.** *"When you're ready, type RUDDER and I'll begin."*

If the project has no tests or no way to run locally, say so at beat 1 or 4 in
plain words, and say what you propose to do about it. Do not smuggle it in later.

### The go word

**Pick it with the script. Never choose it yourself.**

```bash
$(command -v python3 || command -v python) "${CLAUDE_PLUGIN_ROOT}/scripts/skiff/preflight.py" --workspace . arm --on-failure <ask|stop|escalate> --summary "<one line>"
```

A model asked to pick a random word is not random — it converges on the same few
words within a handful of runs, and a predictable word gets typed from muscle
memory without reading what is above it. The script uses a system random source
over a curated word list. **The user having to read to the end to find out what
to type is the entire mechanism.**

Show the word once, at beat 5, and never earlier — an early reveal lets the user
skip ahead and miss the summary.

Check what the user typed:

```bash
$(command -v python3 || command -v python) "${CLAUDE_PLUGIN_ROOT}/scripts/skiff/preflight.py" --workspace . check "<what they typed>"
```

### Rules of the gate

- **Only the current run's go word starts the run.** Not "yes", not "ok", not a
  bare Enter, not enthusiasm.
- **A wrong or mistyped word is not a refusal.** The script leaves the gate
  armed. Re-show the word plainly and wait.
- **Anything that is not the go word is more conversation.** Keep talking,
  adjust, re-offer. Never read a typo as "no".
- **Any change means a fresh readback and a fresh word.** Re-arm with
  `--reconfirm`, which excludes the current word so the user cannot satisfy the
  gate from the previous screen. Never start on an unconfirmed change.
- **Beat 3 is the failure question, asked once.** Whatever the user answers sets
  the run's behavior. Do not ask again later, at the moment of failure or ever.
- **Flags pre-answer beats; they never skip the readback.** If the user already
  passed `--on-failure escalate`, beat 3 states it as the setting rather than
  asking. The readback still happens; the go word is still required.
- **One documented bypass.** `--yes` skips the gate for scripted or repeat runs,
  via `preflight.py bypass`. It must be explicit, it is never the default, and
  the report says the gate was skipped rather than passed.

## Step 3 — Plan

Write the OpenSpec bundle. This does not get dropped for being a small job — an
unplanned build is how a small job becomes a large one.

Follow `reuse-first-design` before proposing any new module, file, or
dependency. Extend before compose, compose before reuse, reuse before build-new.

Keep the bundle proportionate. A change with three acceptance criteria does not
need a design document arguing with itself.

## Step 4 — Build

**Name the model on every dispatch. Read it from the table; do not reason about
it.**

```bash
$(command -v python3 || command -v python) "${CLAUDE_PLUGIN_ROOT}/scripts/skiff/tiers.py" model <role>
```

Pass the result as the `model` parameter of the Agent tool. An agent file's
`model:` line is a default, not a lock — whatever launches the agent names the
model, and that wins. **Therefore skiff edits no agent file.** Nothing to be
overwritten by a plugin update, and no self-heal hook needed. This also means
every existing agent in this plugin is reusable by skiff exactly as it is.

**The ceiling is Opus 5.** Nothing exceeds it without an explicit flag on the
invoking command — never a default, never inferred, never raised by a sub-skill.
Enforced in `model_for`, not in prose.

**Escalate on failure: one tier, once, logged.** If a helper returns a failure
or an explicit low-confidence verdict, retry it one step up exactly one time and
record it. Never two steps. Never above the ceiling. Never silently.

Scope discipline applies unchanged — see `common-pipeline-conventions`
`## Scope discipline`. A small pipeline is not licence to quietly deliver less
than was agreed at Confirm.

## Step 5 — Check

**Verify against a running app.** A local one counts:

- If the project has a dev server, start it and verify there.
- A deployed environment is **optional**. Its absence is not a failure and never
  routes the run anywhere else.

**No pre-existing test suite is required.**

- Missing tests are not a failing verdict.
- Say so plainly and ask, or take the clearance already given at Confirm.
- **When writing tests, skew comprehensive.** This is the one place skiff
  deliberately spends more than it has to. A new project's first test suite is
  the thing everything after it leans on.

**No git remote is required to finish a run.** Commit locally and say so.

## Step 6 — Decide

**Default on three failed attempts: stop and report.** Say what was tried, what
failed, and what you would try next. Spend nothing further.

Escalation to the full pipeline happens **only** if the user chose it at beat 3.
When it does:

- Announce it before it starts.
- Put it on its own branch.
- Never same-branch, never unannounced, never as a surprise consequence of a
  third red result.

The failure to avoid is the one the parent's mini variant has today: three red
cycles hand the work to an unbounded 26-helper pipeline on the same branch with
no prompt and no cap. skiff does not inherit that.

## Step 7 — Report

Every run ends with a report containing at minimum:

- **What ran** — each helper, and the model it ran on.
- **Retries** — per-role retry count and the resulting rate.
- **Cost shape** — helper count and tier mix, alongside what was predicted at
  beat 2, so the estimate can be checked against reality.
- **Gate status** — passed with a go word, or bypassed with `--yes`.
- **What was skipped and why** — no tests written, no deploy verified, no push.
  Silence about a gap reads as coverage that did not happen.

**Calibration.** The retry rates are the input to re-tiering. A role that
routinely escalates moves up a tier. A role that never escalates gets tested one
step down. Re-tier from observed rates, not from argument. Two assignments are
flagged in the table to check first: `qa-replayer` at haiku (its contract
forbids judgment, but it emits a verdict that gates the run) and `bug-classifier`
at sonnet (simple work, but it picks which pipeline the run enters).

---

## What skiff borrows from the rest of the plugin

Recorded deliberately, because every borrowed convention is a line that has to
be re-synced when the parent changes it. This list is meant to stay short.

| Borrowed | Used for |
|---|---|
| `common-pipeline-conventions` `## Cross-platform Python invocation` | Every script call above |
| `common-pipeline-conventions` `## Scope discipline` | Delivering what was agreed at Confirm |
| `common-pipeline-conventions` `## In-flight clarification discipline (v2.5.0)` | A message arriving mid-run is an amendment, not a new job |
| `reuse-first-design` | Step 3, before any new module or dependency |
| `superpowers:test-driven-development` | Step 5, when writing tests |
| `superpowers:systematic-debugging` | Step 6, before proposing a fix for a repeated failure |

**skiff copies none of these.** It references them. If a convention above
changes, skiff inherits the change.

Everything else in this plugin — the review gates, the visual and editability
and interaction reviewers, the map regeneration, the multi-persona work — is
deliberately **not** wired in. Reach for `/architect-team` when a job needs them.

## When not to use skiff

- The change is large, or its shape is unknown.
- It spans codebases that talk to each other.
- The work is high-stakes enough to want the heavyweight review gates up front.

In those cases the full pipeline is cheaper than the rework. Say so plainly and
recommend it.

## Common mistakes

| Mistake | What to do instead |
|---|---|
| Choosing the go word yourself | Always call the script. A model's "random" word is predictable within a few runs. |
| Showing the go word early | Beat 5 only. An early reveal lets the reader skip the summary. |
| Reading a typo as "no" | The gate stays armed. Re-show the word and wait. |
| Asking about failure behavior at the moment of failure | It was answered at beat 3. Asking again teaches the user the answer does not stick. |
| Reasoning about which model a role deserves | Look it up. Runtime judgment is what makes spend unpredictable. |
| Treating a missing test suite as a red verdict | It is a fact about a young project, not a defect. |
| Escalating because three tries failed | Escalation requires the user's word from beat 3. Otherwise: stop and report. |
| Skipping the readback because flags answered everything | Flags pre-answer beats; only `--yes` skips the gate. |
