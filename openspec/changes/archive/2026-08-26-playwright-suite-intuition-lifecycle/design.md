# Design: playwright-suite-intuition-lifecycle

## Context

Source brief: `docs/proposals/PLAYWRIGHT_SUITE_AND_INTUITION_LIFECYCLE.md` (design approved by the user 2026-08-25; decisions §7 are binding). This change builds plugin capability — skills, a command, engines, tests — in THIS repo; the e2e dirs / manifests it describes are the skills' output contract in target projects.

## Goals / Non-Goals

**Goals:** R1 map existence guaranteed; R2 map grows from user flows; R3 debugging feeds map + suite; R4 callable suite-builder (P0–P9); R5 full-integration runs the whole dev suite; R6 dev/prod safety split; V deterministic verification.

**Non-Goals:** no live e2e suite in this repo (no frontend here); no new agents; no analytics/telemetry-driven path detection (explicitly out of scope per the 2026-08-25 review); no change to the −1D bulk-verify gate semantics for intuiter-produced entries.

## Decisions

- **D1 — Two skills, not one (user decision §7.3, Approach A).** `intuition-map-lifecycle` is a cheap, callable-from-any-lane discipline; `playwright-suite-builder` is a phased orchestrator. Folding them would force debugging lanes to drag suite machinery in to record one bug path.
- **D2 — grow bypasses bulk-verify deliberately.** The −1D gate resolves the intuiter's uncertainty; a user-specified flow carries no uncertainty to resolve — the user IS the source. The asymmetry is documented in both skills. Contradiction with an existing confirmed entry is the one case that still asks (domain gate).
- **D3 — Provenance is additive.** `source` + `regression_refs[]` absent ⇒ intuiter-produced. No migration; old maps parse unchanged. The engine treats absence as the default rather than rewriting entries.
- **D4 — The manifest lives in the target repo, committed.** Durable, CI-runnable, survives run state (user decision §7.1). One manifest per frontend codebase at `<e2e-dir>/suite-manifest.json`; `<e2e-dir>` resolution: Playwright config `testDir` → existing conventional dir → create `e2e/` only when none exists.
- **D5 — Checkers are dispatched, never duplicated.** P3 dispatches `test-completeness-verifier` + `interaction-completeness`; P2 reuses `hooks/frontend_impact.py` detection; P8 reuses `test-prod-safety-classifier`; prod smoke runs via `test-run-monitor` as a command test source — its existing command-spawn path (LocalAdapter) pointed at the prod project against the production URL (user decision §7.2 named the monitor, not an adapter; the ProductionQAAdapter is APM-poll/log-tail and cannot spawn a test run — corrected per adversarial finding F2).
- **D6 — Default-deny prod.** Prod project ⊆ `prod-check` ∪ authorized `prod_exceptions[]` (authorization + `it-<prefix>` tag + teardown). `verify-suite-manifest` makes the violation blocking.
- **D7 — Migration boundary.** Absent manifest ⇒ every wired skill behaves exactly as today. The wiring activates only where a manifest exists (mirrors the v3.62.0 unbound-legacy convention).
- **D8 — Engine-first, red-first.** Both engines are stdlib-only with CLIs; every verb/check behavior lands as a red-first pytest before implementation; load-bearing pins get mutation witnesses. Green under cp1252 AND `PYTHONUTF8=1` (pin subprocess/file encodings).
- **D9 — Frontmatter discipline.** New SKILL.md descriptions contain no `": "` (the yaml.safe_load trap); instruction-compliance lint must report zero findings on the new surfaces.

## Reuse Decision Log

| New file / surface | Decision | Why not extend (anchor: docs/CODEBASE_MAP.md + docs/CAPABILITY_INDEX.md) |
|---|---|---|
| `skills/intuition-map-lifecycle/SKILL.md` | build-new (skill) | `interaction-intuition` is a discovery-phase discipline whose sole writer is the dispatch-only `interaction-intuiter`; adding lane-callable verbs there would overload its Phase −1D contract. Extends its ARTIFACT (schema addition documented there), composes its rubric. |
| `skills/playwright-suite-builder/SKILL.md` | build-new (skill) | `playwright-user-flows` is a per-feature authoring discipline (600+ lines); suite-wide orchestration (inventory/freshness/gap-fill/grouping) is a phased pipeline like `ux-test-builder`, which is persona-run-scoped, not suite-scoped. Composes both. |
| `commands/playwright-suite.md` | build-new (command) | House pattern: each callable pipeline has a command wrapper (25 existing); no existing command drives suite building. |
| `scripts/intuition_lifecycle/` (`__init__.py`, `engine.py`, `cli.py`) | build-new (engine pkg) | No existing engine parses INTERACTION_INTUITION_MAP YAML-blocks-in-markdown (`scripts/` catalog: data_dictionary, sql_mining, delivery, contract, mcp_design, helpdesk, token_compression, memory, claude_design, phenotypes, notify, bauplan — none touch the map). Follows the `scripts/<domain>/` convention. |
| `scripts/playwright_suite/` (`__init__.py`, `manifest.py`) | build-new (engine pkg) | No existing manifest/registry engine; `scripts/delivery/delivery_manifest.py` is the closest shape (validate+build CLI) and is the pattern template, but its schema/domain is delivery reporting — composing it would couple unrelated contracts. |
| `tests/test_intuition_lifecycle.py`, `tests/test_suite_manifest.py`, `tests/test_playwright_suite_wiring.py`, `tests/test_playwright_suite_hooks.py` | build-new (tests) | House pattern: one top-level test file per engine/surface; wiring pins live beside the existing skill-pin test conventions; the hooks pin file is task-3.7's mandated disjoint sibling (AUD-2 completion). |

New third-party dependencies: **none** (stdlib-only, house constraint).

## Risks / Trade-offs

- **Suite-builder cost on large repos** — P4 gap analysis is bounded by the map's element count; the skill states coverage math is per-element and escalation (not guessing) is the unknown-persona path.
- **grow extraction quality** — extracting elements from a `.spec.ts` is heuristic (selectors → element ids); the engine records extraction confidence and the skill routes ambiguous extractions to a targeted question rather than a wrong upsert.
- **Wiring breadth** — 8 surfaces edited; each edit is a thin named hook with a pin test so drift is caught by the suite, not review memory.

## Migration Plan

No stored-state migration. Old intuition maps parse unchanged (D3). Projects without a manifest keep today's behavior (D7). First manifest in a target project is created by the first `/architect-team:playwright-suite` run there.
