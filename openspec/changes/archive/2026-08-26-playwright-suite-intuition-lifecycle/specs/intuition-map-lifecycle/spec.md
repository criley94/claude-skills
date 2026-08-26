## ADDED Requirements

### Requirement: The ensure verb guarantees the intuition map exists before test authoring

The `intuition-map-lifecycle` skill SHALL provide an `ensure` verb that, given a frontend codebase, produces `<codebase>/docs/INTERACTION_INTUITION_MAP.md` when it is absent or was never produced — dispatching the `interaction-intuiter` agent in pipeline context, or running the same rubric and schema inline in ad-hoc context with `low`/`unknown` items surfaced to the user as the single-numbered-list bulk-verify — and SHALL refuse to treat test authoring as map-consulted while no map exists. (R1, A1)

#### Scenario: ensure creates a missing map before authoring proceeds

- **WHEN** the `ensure` verb runs for a frontend codebase with no `INTERACTION_INTUITION_MAP.md`
- **THEN** a map conforming to the `interaction-intuition` artifact schema is produced before any test is authored
- **AND** in ad-hoc context its `low`/`unknown` items are presented as the inline bulk-verify numbered list

#### Scenario: ensure is a cheap no-op when the map exists

- **WHEN** the `ensure` verb runs and a map already exists for the codebase
- **THEN** no re-derivation is triggered by `ensure` itself (freshness is the suite-builder's P2 concern, not ensure's)

### Requirement: The grow verb upserts user-specified flows as confirmed entries

The `grow` verb SHALL accept a user-specified flow (a `.spec.ts` file or prose steps), extract the elements and routes it exercises, and upsert them into the map as confirmed entries — `user_verdict: confirmed`, `source: user-flow`, confidence `high` — without a bulk-verify round-trip, because the user specifying the flow IS the confirmation. When a grown entry contradicts an existing confirmed entry, the verb SHALL surface one targeted question naming both readings and SHALL NOT silently overwrite. (R2, A2)

#### Scenario: a user flow lands as confirmed entries

- **WHEN** `grow` processes a user-specified flow exercising elements not yet in the map
- **THEN** the engine upserts entries with `user_verdict: confirmed` and `source: user-flow`

#### Scenario: a contradiction surfaces a question instead of an overwrite

- **WHEN** `grow` processes a user flow whose action or endpoint contradicts an existing confirmed entry
- **THEN** the existing entry is left unmodified
- **AND** a targeted question artifact naming the two readings is produced for the user

#### Scenario: a caller-marked ambiguous extraction routes to a question, not an upsert

- **WHEN** `grow` receives an element the CALLER marked ambiguous (the extraction from the flow was not certain)
- **THEN** no entry is upserted for that element
- **AND** a targeted question artifact naming the ambiguity is produced instead

### Requirement: The bug-path-upsert verb records debugging discoveries in the map

The `bug-path-upsert` verb SHALL accept a bug artifact (reproduction spec plus diagnosis reference) and upsert the path's elements with `source: bug-path` and a `regression_refs[]` entry pointing at the covering debug-flow test and the SR or bug slug. (R3, A3)

#### Scenario: a resolved bug path reaches the map

- **WHEN** `bug-path-upsert` runs for a resolved bug with a committed reproduction spec
- **THEN** the map carries the path's elements with `source: bug-path` and a `regression_refs[]` entry naming the debug-flow test and the bug reference

#### Scenario: bug-path contradiction follows the same no-silent-overwrite rule as grow

- **WHEN** `bug-path-upsert` processes a path element whose action or endpoint contradicts an existing confirmed entry
- **THEN** the existing entry is left unmodified
- **AND** a targeted question artifact naming the two readings is produced — the same guard the grow verb applies

### Requirement: The schema addition is backward-compatible and deterministically engine-backed

The per-element fields `source` (`intuiter | user-flow | bug-path`) and `regression_refs[]` SHALL be additive: an entry without them is read as intuiter-produced, and no migration of existing maps is required. All verb behavior SHALL be implemented by a stdlib-only engine under `scripts/intuition_lifecycle/` (parse the map's YAML-blocks-in-markdown, upsert, validate, CLI) so every verb is red-first testable; the skill document is the contract and the engine is the mechanism.

#### Scenario: a pre-existing map parses unchanged

- **WHEN** the engine parses a map produced before this change
- **THEN** parsing succeeds and every entry reads as `source: intuiter` with empty `regression_refs`

#### Scenario: engine round-trip preserves untouched entries

- **WHEN** the engine upserts one entry and rewrites the map
- **THEN** every untouched entry survives byte-equivalent in content (ordering and formatting per the artifact schema)
