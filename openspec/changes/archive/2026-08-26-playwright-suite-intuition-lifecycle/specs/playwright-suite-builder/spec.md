## ADDED Requirements

### Requirement: A callable suite-builder orchestrates the P0-P9 phases

The `playwright-suite-builder` skill, reachable via the NEW `/architect-team:playwright-suite` command, SHALL orchestrate: P0 target + e2e-dir resolution, P1 inventory (glob specs, parse test names, reconcile against the manifest), P2 map freshness (the map's `last_intuited` vs the most recent commit touching frontend paths via the `hooks/frontend_impact.py` detection; stale → lifecycle ensure/re-intuit with the bulk-verify gate for new `low`/`unknown` items), P3 review of existing tests by DISPATCHING the existing checkers (`test-completeness-verifier`, `interaction-completeness`) rather than duplicating them, P4 gap analysis (manifest `covers_elements` union persona-goal journeys vs the confirmed map, per the `playwright-user-flows` Phase C coverage math applied suite-wide; unknown personas escalate per Step 0, never guessed), P5 gap-fill authoring per the FULL `playwright-user-flows` discipline, P6 debug-flow registration, P7 persona grouping with `dev` and `prod` Playwright projects, P8 dev/prod classification via `test-prod-safety-classifier`, and P9 manifest write + report. (R4, A4)

#### Scenario: a suite-builder run on a fixture project produces a valid grouped suite

- **WHEN** the suite-builder runs against a fixture project with pre-existing tests, a stale map, one inauthentic test, at least one uncovered map element, and one resolved bug artifact
- **THEN** the run produces a valid manifest with the pre-existing tests inventoried, the map refreshed, an authenticity finding routed, gap-fill tests authored, the debug-flow registered, and persona grouping reflected on disk

#### Scenario: e2e-dir resolution follows the target repo's convention

- **WHEN** P0 resolves the e2e directory
- **THEN** the Playwright config's `testDir` wins, an existing conventional e2e directory wins next, and a fresh `e2e/` is created only when none exists

#### Scenario: freshness refresh routes through the lifecycle skill

- **WHEN** P2 finds the map's `last_intuited` older than the most recent frontend-touching commit
- **THEN** the refresh routes through the `intuition-map-lifecycle` ensure/re-intuit path and new `low`/`unknown` items surface via the bulk-verify gate before authoring proceeds

### Requirement: The suite-builder reuses existing checkers and adds no new agents

The suite-builder SHALL dispatch the existing `interaction-intuiter`, `test-completeness-verifier`, and `interaction-reviewer` agents for its verification stages and SHALL NOT introduce a new agent unless a proven gap earns a Reuse Decision.

#### Scenario: review stages name the existing checkers

- **WHEN** the skill body's P3 stage is read
- **THEN** it names `test-completeness-verifier` and `interaction-completeness` as the dispatched reviewers rather than defining new reviewer roles
