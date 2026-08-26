# suite-manifest Specification

## Purpose
TBD - created by archiving change playwright-suite-intuition-lifecycle. Update Purpose after archive.
## Requirements
### Requirement: The suite manifest is the durable per-codebase registry

One manifest per frontend codebase SHALL live at `<e2e-dir>/suite-manifest.json` in the target repo, committed. Per-test entries SHALL carry `file`, `test_names[]`, `persona`, `kind` (`journey | debug-flow | prod-check`), `source` (`user-flow | explorer | gap-fill | bug-path | pre-existing`), `covers_elements[]` (intuition-map element ids), `covers_routes[]`, `safety` (`dev | prod`), `mutates_data`, and `origin_ref` (SR path / bug slug / null). Top-level fields SHALL include `schema_version`, `e2e_dir`, `personas[]`, `last_built`, and `prod_exceptions[]`. The manifest SHALL be validated by a stdlib-only engine (`scripts/playwright_suite/manifest.py`) with a CLI. (V)

#### Scenario: the engine validates a conforming manifest

- **WHEN** the engine validates a manifest carrying every required field with valid enum values
- **THEN** validation reports zero blocking findings

#### Scenario: the engine rejects a malformed manifest

- **WHEN** the engine validates a manifest missing a required field or carrying an unknown `kind`/`source`/`safety` value
- **THEN** validation reports a blocking finding naming the entry and the field

### Requirement: verify-suite-manifest is the deterministic ship check

A `verify-suite-manifest` check SHALL verify (a) manifest-to-disk reconciliation — every listed file exists and every Playwright test file (a `.spec.*` or `.test.*` stem with a JS/TS extension — the engine's published SPEC_SUFFIXES set of 12, both stems across js/jsx/ts/tsx/mjs/cjs, case-insensitively and leading-dot anchored) under the suite directories is listed, (b) the prod project is a subset of `prod-check` entries union authorized exceptions, (c) every `debug-flow` entry has a live `origin_ref`, and (d) schema validity. Each violation SHALL be a blocking finding, with ONE named exception — an `origin_ref` in the bare-slug form (a bug/SR slug rather than a resolvable path) is an ADVISORY, the migration-friendly reference shape, and only a null, dead-path, directory, or empty-file `origin_ref` blocks. (V, A7)

#### Scenario: an unauthorized mutating test in prod blocks

- **WHEN** `verify-suite-manifest` runs against a manifest whose prod project includes a `mutates_data: true` test with no matching `prod_exceptions[]` entry
- **THEN** the check reports a blocking finding naming the test

#### Scenario: a dangling manifest entry blocks

- **WHEN** `verify-suite-manifest` runs and a listed `file` does not exist on disk, or a Playwright test file (any `.spec.*`/`.test.*` form in the published SPEC_SUFFIXES set) under the suite directories is not listed
- **THEN** the check reports a blocking finding naming the path in each direction

#### Scenario: a debug-flow without provenance blocks

- **WHEN** `verify-suite-manifest` runs and a `kind: debug-flow` entry carries a null or dead `origin_ref`
- **THEN** the check reports a blocking finding naming the entry

