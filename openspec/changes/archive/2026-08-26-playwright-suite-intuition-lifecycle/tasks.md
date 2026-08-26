# Tasks: playwright-suite-intuition-lifecycle

## 1. Engines (red-first) — layer: backend

- [ ] 1.1 `tests/test_intuition_lifecycle.py` RED: parse round-trip (pre-existing map → source defaults to intuiter, empty regression_refs); upsert preserves untouched entries; grow-confirmed upsert shape (`user_verdict: confirmed`, `source: user-flow`); contradiction → question artifact, no overwrite (both directions); bug-path-upsert shape (`source: bug-path`, `regression_refs[]`); validation rejects malformed entries. (A1 engine-half, A2, A3 map-half)
- [ ] 1.2 `scripts/intuition_lifecycle/` engine + CLI GREEN against 1.1.
- [ ] 1.3 `tests/test_suite_manifest.py` RED: schema validation (conforming passes; missing field / unknown enum blocks with entry+field named); verify-suite-manifest (a) two-direction disk reconciliation, (b) prod ⊆ prod-check ∪ authorized exceptions (unauthorized mutating prod test blocks; authorization missing tag or teardown still blocks), (c) debug-flow origin_ref liveness, (d) schema validity. (V, A6, A7)
- [ ] 1.4 `scripts/playwright_suite/manifest.py` engine + CLI GREEN against 1.3.
- [ ] 1.5 Mutation witnesses for the load-bearing pins (contradiction-no-overwrite; prod default-deny; reconciliation both directions). Both-encodings green (cp1252 + PYTHONUTF8=1).

## 2. Skills + command — layer: infra

- [ ] 2.1 `skills/intuition-map-lifecycle/SKILL.md` — three verbs, pipeline vs ad-hoc ensure paths, grow bulk-verify-bypass asymmetry documented, engine named. Frontmatter description without `": "`.
- [ ] 2.2 `skills/interaction-intuition/SKILL.md` — additive schema fields (`source`, `regression_refs[]`) + sister-skill writer note. Backward-compat stated.
- [ ] 2.3 `skills/playwright-suite-builder/SKILL.md` — P0–P9 per the spec, e2e-dir resolution ladder, checker dispatch (never duplicate), unknown-persona escalation, migration boundary. Frontmatter clean.
- [ ] 2.4 `commands/playwright-suite.md` — `/architect-team:playwright-suite` wrapper (standard flags; binds the skill).
- [ ] 2.5 `tests/test_playwright_suite_wiring.py` RED→GREEN pins for 2.1–2.4 (skill/command existence, verb naming, P-phase naming, frontmatter lint-clean).

## 3. Thin hooks (pin-tested edits) — layer: infra

- [ ] 3.1 `skills/playwright-user-flows/SKILL.md` Step 1: ensure + consult the map via intuition-map-lifecycle; Phase C manifest-registration note. (A1)
- [ ] 3.2 `skills/ux-test-builder/SKILL.md`: U2/U5 grow; U9 manifest registration. (A2)
- [ ] 3.3 `skills/bug-fix-pipeline/SKILL.md`: B2 bug-path-upsert; B7/B8 debug-flow registration. (A3)
- [ ] 3.4 `skills/architect-team-pipeline/SKILL.md` Phase 5 + `skills/dev-api-integration-testing/SKILL.md`: full-integration enumerates the manifest, runs the ENTIRE dev suite; absent-manifest behavior unchanged. `agents/integration.md` brief updated. (A5)
- [ ] 3.5 `skills/mini-review-sweep` command/skill surface: full-suite run added to the batched gates; mini pipeline text confirms narrow behavior unchanged. (A5)
- [ ] 3.6 `skills/test-run-monitor/SKILL.md`: prod smoke suite named as a runnable test source via the existing command-spawn path (LocalAdapter) against the production URL — NOT via ProductionQAAdapter (an APM-poll/log-tail adapter; the F2 correction). `skills/test-prod-safety-classifier/SKILL.md`: manifest-binding note. (A6)
- [ ] 3.7 Wiring pins in `tests/test_playwright_suite_hooks.py` (its own file — disjoint from 2.5's `tests/test_playwright_suite_wiring.py` so the two task groups never share a file) for every 3.x hook (text names the verb/manifest/boundary).

## 4. Docs + release — layer: infra

- [ ] 4.1 Regenerate `docs/CAPABILITY_INDEX.md` (55 skills / 26 commands); count updates in doc grids per documentation-currency.
- [ ] 4.2 Instruction-compliance lint zero findings on new/edited surfaces; full suite green both encodings.
- [ ] 4.3 Version bump (plugin.json + marketplace.json) + CHANGELOG entry; release-order steps (archive change, clean tree, measurement bracket LAST, `changelog_check.py --require-measurements`) at Phase 8.
