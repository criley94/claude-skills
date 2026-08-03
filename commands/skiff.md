---
description: "Small-build pipeline — the light lane. Takes either a requirements folder or a plain-language description typed directly, reads the job back in plain words, waits for a randomly chosen go word, then builds it with the model for each helper looked up from a fixed table under an Opus 5 ceiling. Works on a project with no test suite, no deployed environment, and no git remote. On three failed attempts it stops and reports rather than handing the work to a bigger, more expensive team — escalation happens only if the user asked for it up front."
argument-hint: "<requirements-folder | plain-language requirement> [--on-failure stop|escalate|ask] [--yes] [--ceiling <tier>]"
---

# /architect-team:skiff

The small boat. Use it when the job is small, the project is young, and the full
pipeline would cost more than the work is worth.

This command runs the `skiff-pipeline` skill. Read that skill for the seven-step
playbook. What follows is only what the command itself needs to know.

## Inputs

`$ARGUMENTS` is either:

1. **A requirements folder** — a path resolving to an existing directory.
2. **A plain-language requirement** — prose typed directly. The prose IS the
   requirement; it is not a path.

Never refuse prose. Never treat the first word of a sentence as a path. Ask only
when `$ARGUMENTS` is genuinely empty.

## Flags

Each is independent. Every one of them **pre-answers a question the readback
would otherwise ask — none of them skips the readback itself**, except `--yes`.

- `--on-failure stop|escalate|ask` → what happens after three failed attempts.
  Default `ask`, which means the readback asks. `stop` halts and reports;
  `escalate` hands off to the full pipeline, announced, on its own branch.
  Natural-language equivalents: *"stop if it doesn't work"* / *"escalate if you
  get stuck"* / *"hand it off if you're stuck"*.
- `--yes` → skip the pre-flight readback and go word entirely. For scripted or
  repeat runs. **Must be explicit; never a default.** The run report says the
  gate was skipped rather than passed.
- `--ceiling <tier>` → raise the model ceiling above Opus 5. The **only** way to
  exceed it. Never inferred, never set by a sub-skill, never a default. Costs
  more than the parent pipeline does today; say so before honoring it.

Anything not listed here is not a flag skiff supports. Do not invent flag stacks
or presets — an untested combination handed to a non-specialist is exactly the
failure this pipeline exists to avoid.

## The pre-flight gate — the part that matters

Before **any** helper is spawned or any file is written, skiff reads the job
back in plain language and waits for a go word that **changes every run**.

The word is chosen by `scripts/skiff/preflight.py`, never by the model running
the command. It is shown once, at the end of the readback. A wrong or mistyped
word is treated as more conversation, never as a refusal. Any change to the plan
produces a fresh readback and a fresh word.

Only the current run's go word starts the run — not "yes", not "ok", not a bare
Enter.

## What this command deliberately does not do

No worktree creation, no auto-merge to `main`, no push, no branch reconciliation
sweep, no notification wiring, no map regeneration, no review-gate fan-out. Those
belong to `/architect-team` and `/architect-team:mini`. skiff stays small on
purpose; every convention it adopts is one more thing to keep in sync later.

Commit locally at the end. Say plainly what was and was not done — including any
step skipped for want of a test suite, a running app, or a remote.

## When to reach for something else

Use `/architect-team` when the change is large or its shape is unknown, when it
spans codebases that talk to each other, or when the work warrants the
heavyweight review gates up front. Use `/architect-team:mini` when the project
already has tests, a dev URL, and a remote, and you want auto-merge on green.

Say so plainly rather than running a small pipeline on a job that needs a big one.
