# Glossary

Plain-English translations for the vocabulary this plugin uses.

You should not need this to run `/architect-team:skiff` — skiff is written to
avoid all of it. You need it when you read anything else in this repository, or
when a helper's output uses a term skiff itself would not.

If a term below still costs you a beat to decode, that is a defect in the term,
not in you.

---

## The terms

| The repo says | It means |
|---|---|
| **Producer ≠ checker** | Whoever wrote it doesn't get to be the one who says it's right |
| **Coverage map** | A checklist tying every thing you asked for to the code and test that delivers it |
| **Review gate** | A checkpoint that won't let work through without proof |
| **Hard gate** | A checkpoint that cannot be skipped |
| **Process gate** | An optional pause for your approval |
| **Domain gate** | A stop where the tool needs a fact only you know |
| **Solution requirement (SR)** | A to-do the tool wrote for itself when it found a problem mid-build |
| **Ralph loop** | Three reviewers arguing until they agree |
| **Fan-out** | Running several helpers at once on the same question |
| **Unbounded solving** | It keeps going until it works — there is no "give up after N tries" |
| **Oracle spec** | A frozen copy of what you asked for, used to grade the result |
| **Parity verb** | Words like "match", "rebuild", "mirror" that mean *copy this exactly* |
| **Phenotype** | A pre-built starter architecture you can adopt instead of starting empty |
| **Scaffold** | The starter files a phenotype writes for you |
| **Worktree** | A separate copy of your repo so the work doesn't disturb your main one |
| **Real not stubbed** | Actual working code, not a placeholder that pretends |
| **Confirmed stub** | A deliberate blank you approved, so it won't be reported as a bug |
| **Standing red** | A test left failing on purpose — forbidden here |
| **Acceptance criteria** | The handful of things you'd check to say "yes, it works" |
| **Playwright flow** | A robot clicking through your app like a user would |
| **Dev-API integration test** | A test against the real backend, not a fake one |
| **Dispatch mode** | Whether the tool uses long-lived named helpers or fresh one-shot ones |
| **Escalation** | The small pipeline giving up and handing the job to the big one |
| **VAO** | Machinery that checks helpers actually did what they said |
| **OpenSpec bundle** | The written plan, in a fixed set of files, before any code is written |
| **Agent / teammate** | One helper doing one job. Costs money each time one runs |
| **Tier** | Which model a helper runs on. Cheaper tiers for mechanical work |
| **Ceiling** | The most expensive model a run is allowed to use |
| **Phase −1** | A stage of the big pipeline. It counts from below zero for historical reasons; skiff does not number its steps at all |

---

## skiff's own words

skiff introduces four terms and no more. Each one is meant to be self-evident;
they are listed here so the list is complete, not because they need decoding.

| Term | Meaning |
|---|---|
| **Go word** | The word you type to start a run. It changes every run, on purpose — so you have to read the summary to find out what it is |
| **Readback** | The plain-language summary of what's about to happen, shown before anything starts |
| **The table** | The fixed list saying which model each helper runs on. Looked up, never decided in the moment |
| **Helper** | One agent doing one job — the same thing the rest of the repo calls an agent or teammate |

---

## Three things worth knowing about the house style

**The register is imperative.** "MUST", "NEVER", "non-negotiable". That is
correct for a machine contract and punishing as a human interface. Read it as
emphasis for the tool, not as being shouted at.

**Terms are used before they're defined.** The repository has no other glossary.
If a term appears with no explanation, it is usually defined nowhere. Check the
table above first; then ask.

**Numbers below zero.** The big pipeline's stages start at −2. There is no
meaning in the negative numbers beyond the order stages were added. skiff
sidesteps this entirely by naming its steps instead: Understand, Confirm, Plan,
Build, Check, Decide, Report.
