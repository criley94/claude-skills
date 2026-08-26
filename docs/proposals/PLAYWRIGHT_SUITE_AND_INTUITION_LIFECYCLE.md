# Proposal — Playwright suite builder + intuition-map lifecycle

**Status:** design approved by the user 2026-08-25 (brainstorm complete; decisions recorded in §7). Building via a fresh `/architect-team` run against this document — in-place (feature branch in the main checkout, `--no-worktree`), merge `--no-ff` to main on complete.

**Origin:** user request (2026-08-25) — *"we need to ensure that we 1) have the intuition map 2) grow this if users give specific ux playwright tests 3) call this or a sister skill if debugging and new bug paths are identified, those must be added to both existing tests and playwright tests and intuition maps. additionally we need a skill we can call to build playwright suite — it identifies which tests are written, checks freshness of map, refreshes map if older than most recent changes to front end. reviews playwright tests, creates tests that fill in testing gaps. recognizes also test flows that are debugging flows and ensures those are there. groups by persona type etc… and ensures that when playwright testing is called and we call for full integration tests, this entire suite is run. it knows to create dev ones which can modify data (i.e all tests) and prod ones which are only checks (no data modification is allowed unless explicit and test only exceptions)"*

**Scope framing (important):** this repo ships the PLUGIN. The deliverables of this run are skills / commands / deterministic engines / tests **in this repo**. The e2e directories, suite manifests, and Playwright projects described below are artifacts the new skills produce **in target projects** when invoked there — they are the skills' output contract, not files to create in this repo.

---

## 1. The target spec (6 requirements + verification)

- **R1 — Map existence guaranteed.** Any Playwright-authoring context (pipeline OR ad-hoc "write me a Playwright test") ensures `<codebase>/docs/INTERACTION_INTUITION_MAP.md` exists — created if absent, consulted always — before test authoring proceeds.
- **R2 — Map grows from user-given flows.** When the user specifies a concrete UX Playwright test (ux-test literal flow, ad-hoc request, handed-over spec), the elements/routes it exercises are upserted into the intuition map as **confirmed** entries — the user specifying the flow IS the confirmation; no bulk-verify round-trip. A user flow that CONTRADICTS an existing confirmed entry surfaces as one targeted question (domain gate), never a silent overwrite.
- **R3 — Debugging feeds back.** When debugging identifies a new bug path, a callable skill ensures that path lands in three places: (a) the existing test layers (unit/integration regression — already the B2 discipline), (b) the Playwright suite (registered as a debug-flow), (c) the intuition map (upsert with bug-path provenance + a regression pointer).
- **R4 — A callable suite-builder skill** that: inventories which Playwright tests are written → checks map freshness against the most recent frontend changes (refreshes when stale) → reviews existing tests (authenticity/mock/vacuous/fixture-hygiene audits) → authors tests that fill coverage gaps → recognizes debugging flows and ensures they are present → groups the suite by persona.
- **R5 — Full integration runs the entire suite.** When Playwright testing is called as part of full integration testing (pipeline Phase 5 / `dev-api-integration-testing` full runs / `mini-review-sweep`), the ENTIRE persona-grouped dev suite is enumerated from the manifest and run — not just the current slice's flows.
- **R6 — Dev vs prod split.** Dev suite: all tests, data mutation allowed under the existing shared-state hygiene rules. Prod suite: **default-deny read-only checks** — no data modification unless an explicit, user-authorized, test-only exception with mandatory teardown. The prod suite is a first-class runnable smoke suite against the production URL.
- **V — Verification.** A deterministic `verify-suite-manifest` check: manifest ↔ disk reconciliation; the prod project contains zero unauthorized mutating tests; every debug-flow entry has a live `origin_ref`.

## 2. Coverage table (current CT6 vs the spec)

| # | Requirement | Verdict | Current mechanism (evidence) | Gap |
|---|---|---|---|---|
| R1 | map existence guaranteed | **GAP** | `interaction-intuition` exists but is pipeline-dispatch-only (Phase −1D of `intake-and-mapping`, per-frontend-codebase `interaction-intuiter`); `playwright-user-flows` Step 1 consults only `ROUTE_MAP.md` and contains ZERO references to the intuition map (verified by grep, 2026-08-25) | no ensure verb; no ad-hoc path; authoring discipline never reads the map even when it exists |
| R2 | map grows from user flows | **GAP** | `ux-test-builder` U2 authors the literal flow; the map's `user_verdict`/`confirmed_*` fields exist and are written ONLY by the −1D bulk-verify gate | nothing upserts user-specified flows into the map; no provenance field |
| R3 | debugging feeds back | **PARTIAL** | B2 reproduction IS the regression test, QA-replayed verbatim + code-path witness (`bug-fix-pipeline`, `qa-replayer`) — the tests half is COVERED | bug paths never reach the intuition map; repro specs are never registered in any durable suite |
| R4 | callable suite-builder | **GAP (largest)** | pieces exist: `test-completeness-verifier` (per-slice gap detection), `interaction-completeness` (element wiring audit), `hooks/frontend_impact.py` (frontend-change detection), `intake-and-mapping` (freshness discipline), `playwright-user-flows` Phase C (coverage math) | no orchestrator composes them; no durable suite registry; no persona grouping across slices |
| R5 | full integration = full suite | **GAP** | Phase 5 runs the slice's flows + the integration suite; `mini-review-sweep` replays gates per mini-slug diff | no whole-suite enumeration; nothing durable to enumerate |
| R6 | dev/prod split | **PARTIAL** | `test-prod-safety-classifier` EXISTS (test-vs-prod safety classification discipline + `/architect-team:classify-test-prod-safety`); `test-run-monitor` has a **ProductionQAAdapter**; `dev-api-integration-testing` has the `it-<prefix>` test-only data convention | no suite-level dev/prod Playwright projects; no prod_exceptions allowlist; classifier verdict not bound per-test in any registry |

## 3. Design (approved 2026-08-25)

### 3.1 The suite manifest — the durable registry

One per frontend codebase, committed **in the target repo** at `<e2e-dir>/suite-manifest.json`. `<e2e-dir>` auto-detection (reuse-first, follow repo convention): the Playwright config's `testDir` → an existing `e2e/` / `tests/e2e/` conventional dir → create `e2e/` only when none exists. Per-test entries: `file`, `test_names[]`, `persona`, `kind` (`journey | debug-flow | prod-check`), `source` (`user-flow | explorer | gap-fill | bug-path | pre-existing`), `covers_elements[]` (intuition-map `element_id`s), `covers_routes[]`, `safety` (`dev | prod`), `mutates_data` (bool), `origin_ref` (SR path / bug slug / null). Top-level: `schema_version`, `e2e_dir`, `personas[]`, `last_built`, `prod_exceptions[]` (§3.5). The manifest is the single artifact that answers "which tests are written", binds tests to map elements, and is what R5 enumerates.

### 3.2 `intuition-map-lifecycle` — the sister skill (NEW)

Three verbs, callable from any lane:

- **ensure** — map absent/never produced → produce it. In-pipeline: dispatch `interaction-intuiter` per `intake-and-mapping` (unchanged). Ad-hoc: run the same rubric + schema inline; surface `low`/`unknown` items to the user directly as the same single bulk-verify numbered list (the −1D gate logic executed inline). Never authors tests against a missing map.
- **grow** — given a user-specified flow (`.spec.ts` or prose steps), extract the elements/routes it exercises; upsert entries with `user_verdict: confirmed`, `source: user-flow`, confidence `high`. Contradiction with an existing confirmed entry → one targeted question (domain gate), never a silent overwrite.
- **bug-path-upsert** — given a bug artifact (repro spec + diagnosis), upsert the path's elements with `source: bug-path` and `regression_refs[]` pointing at the covering debug-flow test + the SR/bug slug.

Schema addition to `INTERACTION_INTUITION_MAP.md` per-element fields (backward-compatible; absent = intuiter-produced): `source` (`intuiter | user-flow | bug-path`), `regression_refs[]`. `interaction-intuition/SKILL.md` documents the fields and names the sister skill as the sole writer of non-intuiter entries.

Deterministic engine: `scripts/intuition_lifecycle/` (stdlib-only) — parse the map's YAML-blocks-in-markdown, upsert, validate, CLI — so every verb's behavior is red-first-testable. The skill is the contract; the engine is the mechanism.

### 3.3 `playwright-suite-builder` — the orchestrator skill (NEW) + `/architect-team:playwright-suite` (NEW command)

Phases (the command drives them; standard flags `--no-commit` / `--no-push` / `--no-compact` apply):

- **P0 — Target resolution.** Identify frontend codebase(s) in scope; resolve `<e2e-dir>` per §3.1; read the Playwright config.
- **P1 — Inventory.** Glob spec files, parse test names, reconcile against the manifest (new / gone / renamed → manifest updates; `pre-existing` source for tests the builder did not author).
- **P2 — Map freshness.** Compare the map's `last_intuited` against the most recent commit touching frontend paths (reuse `hooks/frontend_impact.py` detection). Stale → lifecycle **ensure**/re-intuit; new `low`/`unknown` items → bulk-verify gate. `playwright-user-flows`' existing rule stands: tests are never built on a stale map.
- **P3 — Review existing tests.** Dispatch the existing checkers — `test-completeness-verifier` (vacuous navigate-and-assert, `page.request` substitutes, mock-backed happy paths, fixture hygiene) and `interaction-completeness` (element wiring, placeholder pages). Findings become gap-fill work items or SRs per the existing routing.
- **P4 — Gap analysis.** Coverage = manifest `covers_elements` ∪ persona×goal journeys vs the confirmed map + user-intent maps (`playwright-user-flows` Phase C math applied suite-wide). Personas come from existing user-intent maps / `domain-research-team` outputs / ux-test intake artifacts; unknown personas → escalate per Step 0's PROCEED test — never guessed.
- **P5 — Gap-fill authoring.** Author missing tests per the FULL `playwright-user-flows` discipline (Step 0 citations or escalation included).
- **P6 — Debug-flow registration.** Sweep resolved bug artifacts (`.architect-team/solution-requirements/`, run-history, `ux-tests/*/bugs/`, committed B2 repro specs; the debugging-enhancement's `REGRESSION_COMPENDIUM` index when that ships — forward-compatible). Every resolved bug path has a registered `debug-flows/` test (`kind: debug-flow`, `origin_ref` set) + a lifecycle **bug-path-upsert**.
- **P7 — Persona grouping.** Organize specs under `<e2e-dir>/personas/<persona-slug>/`, `<e2e-dir>/debug-flows/`, `<e2e-dir>/prod-checks/`; define Playwright projects `dev` (full suite) and `prod` (prod-checks only) in the target's config.
- **P8 — Dev/prod classification.** Invoke `test-prod-safety-classifier` per test → `safety` + `mutates_data` recorded in the manifest; generate/derive read-only `prod-check` variants of the smoke-worthy journeys; enforce §3.5.
- **P9 — Manifest write + report.** Validate via the engine; write the manifest; emit the run report (counts per persona/kind/safety, gaps closed, gaps escalated).

### 3.4 Thin hooks into existing skills (EDITS)

- `playwright-user-flows` — Step 1 gains "**ensure + consult** the intuition map via `intuition-map-lifecycle`" (closes the verified R1 gap); Phase C notes suite-manifest registration when a manifest exists.
- `ux-test-builder` — U2 (literal) + U5 (distilled) flows call **grow**; U9 registers the flows into the suite manifest.
- `bug-fix-pipeline` — B2 repro → **bug-path-upsert**; B7/B8 archive → register the repro as a `debug-flow` manifest entry.
- `architect-team-pipeline` Phase 5 + `dev-api-integration-testing` — when full integration tests are called, enumerate the manifest and run the ENTIRE dev suite; failures route as SRs exactly as today. `integration` agent brief updated accordingly.
- `mini-architect-team-pipeline` — unchanged (mini stays narrow by design); `mini-review-sweep` adds the full-suite run to its batched gates.
- `test-run-monitor` — the prod smoke suite is a named runnable test source via the monitor's existing command-spawn path (LocalAdapter) against the production URL (scheduled prod health checks; the ProductionQAAdapter is APM-poll/log-tail and cannot spawn a test run — mechanism corrected in-run per adversarial finding F2).

### 3.5 Dev/prod safety model

Dev project: all tests; mutation allowed under the existing shared-state hygiene rules (run-unique values / teardown restore; every flow runnable twice). Prod project: **default-deny** — only `kind: prod-check` tests, navigation/assertion-only; the classifier verdict is recorded per test; a `mutates_data: true` test enters the prod project ONLY via a `prod_exceptions[]` entry carrying the user's recorded authorization (who/when/why), a test-only data tag (the `it-<prefix>` convention from `dev-api-integration-testing`), and mandatory teardown. New/unclassified tests land dev-only. The `verify-suite-manifest` check (§3.6) makes an unauthorized prod-mutating test a blocking finding.

### 3.6 Verification (house style)

Deterministic `verify-suite-manifest`: (a) manifest ↔ disk reconciliation (every listed file exists; every spec under the suite dirs is listed), (b) prod project ⊆ `prod-check` ∪ authorized exceptions, (c) every `debug-flow` has a live `origin_ref`, (d) schema validity. Enforcement shape — Layer-3 tool under `hooks/vao/` vs suite-test + P9 gate — is the run's architect's call; the acceptance criteria (§8) bind either way. Red-first tests for both engines; 15/15-style mutation witnesses for the load-bearing pins.

## 4. Deliverables inventory (this repo)

- NEW `skills/intuition-map-lifecycle/SKILL.md`; NEW `skills/playwright-suite-builder/SKILL.md`; NEW `commands/playwright-suite.md` (skills 53→55, commands 25→26 — counts disk-anchored, doc grids updated per doc-currency).
- NEW `scripts/intuition_lifecycle/` engine + NEW suite-manifest engine (e.g. `scripts/playwright_suite/manifest.py`) — both stdlib-only with CLIs.
- Schema addition (backward-compatible) documented in `skills/interaction-intuition/SKILL.md`.
- EDITS per §3.4: `playwright-user-flows`, `ux-test-builder`, `bug-fix-pipeline`, `architect-team-pipeline`, `dev-api-integration-testing`, `mini-review-sweep` command/skill, `test-run-monitor`, `agents/integration.md`; `test-prod-safety-classifier` gains a "manifest binding" note.
- **No new agents expected** (reuse-first): the suite-builder orchestrates `interaction-intuiter`, `test-completeness-verifier`, `interaction-reviewer`s, and the authoring teammates. A new agent requires a proven gap + Reuse Decision.
- Red-first tests for every engine + instruction-surface lint zero-findings on the new skills; CHANGELOG + version bump + measurement bracket per release order.

## 5. Already well-covered (do NOT rebuild)

Replicate-first + reproduction-is-the-regression-test + verbatim QA replay + code-path witness (bug-fix B1/B2/B6); per-slice gap detection (`test-completeness-verifier`) and element-wiring audit (`interaction-completeness`) — the suite-builder DISPATCHES these, never duplicates them; test-vs-prod safety classification (`test-prod-safety-classifier`); frontend-change detection (`hooks/frontend_impact.py`); map freshness discipline (`intake-and-mapping`); persona/goal grounding + coverage math (`playwright-user-flows` Step 0 / Phase C); prod-run plumbing (`test-run-monitor` source-selection / command-spawn path); shared-state hygiene + `it-<prefix>` fixtures (`dev-api-integration-testing`).

## 6. Constraints (house rules that bite here)

Python 3.10+ stdlib-only; green under Windows cp1252 AND `PYTHONUTF8=1` (pin subprocess encodings). SKILL.md frontmatter descriptions must NOT contain `": "` (breaks the test parser's yaml.safe_load — use em-dash/comma). The map schema addition must be backward-compatible (absent fields = pre-existing intuiter entries; no migration of existing maps required). The −1D bulk-verify remains a domain gate; **grow** deliberately bypasses it (user-specified = confirmed) — document that asymmetry explicitly in both skills. Release order per CLAUDE.md conventions (reconcile version/CHANGELOG → archive OpenSpec change → clean tree → measure LAST → `changelog_check.py --require-measurements`).

## 7. Recorded user decisions (2026-08-25)

1. **Suite home:** follow the target repo's convention (auto-detect existing Playwright/e2e layout; impose the structure inside it; create `e2e/` only when none exists). Committed to the target repo.
2. **Prod suite:** a first-class runnable smoke suite against the production URL — read-only enforced, `prod_exceptions[]` requires explicit user authorization, runnable via `test-run-monitor`.
3. **Approach:** A — two new skills (`intuition-map-lifecycle` + `playwright-suite-builder`) with thin hooks into existing skills (B: one combined skill, and C: extend-in-place, were rejected).
4. **Build route:** fresh `/architect-team` run against this document, in-place (`--no-worktree`, feature branch in the main checkout), auto-merge `--no-ff` to main on complete.

## 8. Acceptance criteria

- **A1 (R1):** invoking `playwright-user-flows` or the suite-builder for a frontend codebase with no `INTERACTION_INTUITION_MAP.md` produces one (pipeline: intuiter dispatch; ad-hoc: inline derivation with the inline bulk-verify) BEFORE any test is authored; the authoring step consults the map.
- **A2 (R2):** a user-specified flow upserts confirmed entries (`source: user-flow`) via the engine; a contradiction with an existing confirmed entry produces a targeted question artifact, not an overwrite (both directions red-first-tested).
- **A3 (R3):** a resolved bug path results in: the B2 regression artifact (existing), a `debug-flow` manifest entry with live `origin_ref`, and map entries with `source: bug-path` + `regression_refs[]` (engine-tested).
- **A4 (R4):** the suite-builder run on a fixture project produces a valid manifest: pre-existing tests inventoried, stale map refreshed (frontend-change detection exercised), at least one authenticity finding routed, gap-fill tests authored per discipline, debug-flows registered, persona grouping on disk.
- **A5 (R5):** the Phase 5 / `dev-api-integration-testing` full-integration path enumerates the manifest and runs every dev-suite test; the skill text names the manifest as the enumeration source (pin-tested).
- **A6 (R6):** classifier verdict bound per test in the manifest; prod project default-deny verified by `verify-suite-manifest` (an unauthorized mutating test in prod = blocking finding, red-first); `prod_exceptions[]` entries carry authorization + `it-<prefix>` tag + teardown.
- **A7 (V):** `verify-suite-manifest` implements §3.6 (a)–(d) with red-first tests + mutation witnesses.

## 9. Build sequence (recommended for the run)

1. Engines first, red-first: `scripts/intuition_lifecycle/` (parse/upsert/validate) → suite-manifest engine + `verify-suite-manifest`.
2. `intuition-map-lifecycle` SKILL.md + the `interaction-intuition` schema addition.
3. `playwright-suite-builder` SKILL.md + command (P0–P9), wired to the engines + existing checkers.
4. Thin hooks (§3.4) — each a small pin-tested edit.
5. Docs + counts + CHANGELOG + measurement per release order.
