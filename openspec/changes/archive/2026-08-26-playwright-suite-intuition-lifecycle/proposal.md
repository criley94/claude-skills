# Proposal: playwright-suite-intuition-lifecycle

## Why

Three verified gaps in the CT6 Playwright-flow stack (evidence: skill-body greps + wiring review, 2026-08-25, recorded in `docs/proposals/PLAYWRIGHT_SUITE_AND_INTUITION_LIFECYCLE.md`):

1. `INTERACTION_INTUITION_MAP.md` exists only when a pipeline run's Phase −1D produced it; `playwright-user-flows` contains ZERO references to it, so ad-hoc test authoring neither ensures nor consults the map (R1).
2. Nothing grows the map from user-specified flows (R2) or from bug paths surfaced by debugging (R3) — repro artifacts become regression tests (B2 discipline) but never reach the map, and are never registered in any durable suite.
3. No durable, persona-grouped Playwright suite exists per target project: no registry of which tests are written, no suite-wide gap analysis, no whole-suite enumeration when full integration testing is called (R4, R5), and no dev/prod safety split binding the existing `test-prod-safety-classifier` verdicts per test (R6).

## What Changes

- **NEW skill `intuition-map-lifecycle`** — three verbs callable from any lane: `ensure` (map absent → produce it; inline bulk-verify ad-hoc), `grow` (user-specified flows upsert as confirmed entries, `source: user-flow`; contradictions surface a targeted question, never a silent overwrite), `bug-path-upsert` (`source: bug-path` + `regression_refs[]`). Backward-compatible per-element schema addition (`source`, `regression_refs[]`) documented in `interaction-intuition`.
- **NEW skill `playwright-suite-builder`** + **NEW command `/architect-team:playwright-suite`** — the P0–P9 orchestrator: e2e-dir resolution (follow repo convention), inventory, map freshness (via `hooks/frontend_impact.py` detection), existing-test review (dispatching `test-completeness-verifier` + `interaction-completeness`), gap analysis + gap-fill per `playwright-user-flows`, debug-flow registration, persona grouping, dev/prod classification via `test-prod-safety-classifier`, manifest write + report.
- **NEW engines (stdlib-only)** — `scripts/intuition_lifecycle/` (map parse/upsert/validate + CLI) and `scripts/playwright_suite/manifest.py` (suite-manifest schema validation, reconciliation, `verify-suite-manifest` check).
- **Thin pin-tested EDITS** — `playwright-user-flows` Step 1 (ensure + consult the map), `ux-test-builder` (U2/U5 grow; U9 register), `bug-fix-pipeline` (B2 upsert; B7/B8 register), `architect-team-pipeline` Phase 5 + `dev-api-integration-testing` (full-integration enumerates the manifest and runs the ENTIRE dev suite), `mini-review-sweep` (adds the full-suite run), `test-run-monitor` (prod smoke suite runnable as a command test source — the existing command-spawn/LocalAdapter path against the production URL), `agents/integration.md`, `test-prod-safety-classifier` (manifest-binding note).

Counts: skills 53→55, commands 25→26. No new agents (reuse-first; the suite-builder orchestrates existing checkers). No new third-party dependencies (Python stdlib-only).

## Impact

- Affected specs: NEW capabilities `intuition-map-lifecycle`, `playwright-suite-builder`, `suite-manifest`, `suite-dev-prod-safety`, `suite-pipeline-wiring`.
- Affected code: `skills/` (2 new + 6 edited), `commands/` (1 new + 1 edited), `agents/integration.md`, `scripts/` (2 new engine packages), `tests/` (red-first suites + mutation witnesses), docs grids (counts + capability index + map note ledgers) at Phase 8.
- The e2e directories / manifests / Playwright projects the new skills describe are artifacts produced **in target projects** when the skills run there — NOT files in this repo.
- User decisions binding this change (2026-08-25): suite follows the target repo's e2e convention; prod suite is a runnable read-only smoke suite; Approach A (two skills, thin hooks); in-place build on a feature branch, auto-merge on green.
