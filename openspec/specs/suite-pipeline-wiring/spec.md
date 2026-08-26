# suite-pipeline-wiring Specification

## Purpose
TBD - created by archiving change playwright-suite-intuition-lifecycle. Update Purpose after archive.
## Requirements
### Requirement: Full integration testing enumerates the manifest and runs the entire dev suite

When Playwright testing is called as part of full integration testing — the `architect-team-pipeline` Phase 5 cross-layer run and the `dev-api-integration-testing` full-run discipline — the run SHALL enumerate the target codebase's `suite-manifest.json` and execute the ENTIRE dev suite, not only the current slice's flows, with failures routed as solution requirements exactly as today. The skill texts SHALL name the manifest as the enumeration source. Absent a manifest, behavior is unchanged (the named migration boundary). (R5, A5)

#### Scenario: Phase 5 names the manifest as the enumeration source

- **WHEN** the `architect-team-pipeline` Phase 5 text and the `dev-api-integration-testing` full-run text are read
- **THEN** each names `suite-manifest.json` enumeration of the entire dev suite when a manifest exists
- **AND** each states the absent-manifest behavior is unchanged

#### Scenario: mini stays narrow while the sweep runs the suite

- **WHEN** the `mini-architect-team-pipeline` and `mini-review-sweep` texts are read
- **THEN** mini's narrow-flow behavior is unchanged and the sweep names the full-suite run among its batched gates

### Requirement: playwright-user-flows ensures and consults the intuition map

`playwright-user-flows` Step 1 SHALL ensure the intuition map exists via the `intuition-map-lifecycle` skill and consult it alongside `ROUTE_MAP.md`, and its Phase C SHALL note suite-manifest registration when a manifest exists. (R1, A1)

#### Scenario: Step 1 names the lifecycle ensure

- **WHEN** the `playwright-user-flows` Step 1 text is read
- **THEN** it names the `intuition-map-lifecycle` ensure verb and the map-consult obligation before authoring

### Requirement: The ux-test and bug-fix lanes feed the map and the suite

`ux-test-builder` SHALL call the `grow` verb for the U2 literal and U5 distilled flows and register the flows into the suite manifest at U9. `bug-fix-pipeline` SHALL call `bug-path-upsert` at B2 and register the reproduction artifact as a `debug-flow` manifest entry at the B7/B8 archive step. The `agents/integration.md` brief SHALL reflect the Phase 5 full-suite enumeration. (R2, R3, A2, A3)

#### Scenario: the lane texts name their verbs

- **WHEN** the `ux-test-builder` and `bug-fix-pipeline` bodies are read
- **THEN** ux-test names `grow` at U2/U5 and manifest registration at U9
- **AND** bug-fix names `bug-path-upsert` at B2 and debug-flow registration at B7/B8

