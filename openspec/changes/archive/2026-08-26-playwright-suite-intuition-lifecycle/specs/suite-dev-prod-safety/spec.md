## ADDED Requirements

### Requirement: Dev and prod suites split on classifier-bound safety

The dev Playwright project SHALL contain all tests with data mutation allowed under the existing shared-state hygiene rules (run-unique values or teardown restore; every flow runnable twice). The prod Playwright project SHALL be default-deny: only `kind: prod-check` tests, navigation and assertion only, with the `test-prod-safety-classifier` verdict recorded per test in the manifest (`safety`, `mutates_data`). A new or unclassified test SHALL land dev-only. (R6, A6)

#### Scenario: classifier verdicts are bound per test

- **WHEN** the suite-builder's P8 stage classifies the suite
- **THEN** every manifest entry carries a `safety` value and a `mutates_data` flag derived from the `test-prod-safety-classifier` discipline

#### Scenario: unclassified tests never enter prod

- **WHEN** a test has no recorded classification
- **THEN** it is excluded from the prod project and carries `safety: dev`

### Requirement: Prod mutation requires an explicit authorized exception

A `mutates_data: true` test SHALL enter the prod project ONLY via a `prod_exceptions[]` entry carrying the user's recorded authorization (who, when, why), a test-only data tag per the `it-<prefix>` convention from `dev-api-integration-testing`, and mandatory teardown. (R6, A6)

#### Scenario: an authorized exception admits a mutating prod test

- **WHEN** a mutating test's `prod_exceptions[]` entry carries authorization, the test-only tag, and teardown
- **THEN** `verify-suite-manifest` accepts its presence in the prod project

#### Scenario: authorization without the test-only tag still blocks

- **WHEN** a `prod_exceptions[]` entry lacks the test-only data tag or the teardown declaration
- **THEN** `verify-suite-manifest` reports a blocking finding for that entry

### Requirement: The prod suite is a runnable smoke suite

The prod (read-only) suite SHALL be runnable against the production URL as a first-class smoke suite, and the `test-run-monitor` skill SHALL name the suite-manifest prod project as a runnable TEST SOURCE through its existing source-selection — the command-spawn path (LocalAdapter) invoking the prod project's Playwright command against the production URL — so scheduled prod health checks reuse the monitor unchanged. The wiring SHALL NOT claim the ProductionQAAdapter (an APM-poll / log-tail adapter) executes the suite, and SHALL require no adapter change.

#### Scenario: test-run-monitor names the prod suite

- **WHEN** the `test-run-monitor` skill body is read
- **THEN** it names the suite-manifest prod project as a runnable test source via the existing command-spawn path (LocalAdapter) against the production URL
- **AND** it does not claim the ProductionQAAdapter executes the suite
