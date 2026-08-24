# completion-lock — delta for inherited-task-debt (v3.64.0)

## ADDED Requirements

### Requirement: Open tasks age into inherited debt instead of wedging later sessions

The task-list source SHALL treat an open task whose file has gone untouched
longer than the abandonment window (`CT6_TASK_STALE_HOURS`, floored at 1.0h,
defaulting to the resolved `CT6_RUN_MARKER_STALE_HOURS` window) as INHERITED
DEBT: reported in the block (count, items, task-store dir) and in an advisory
reason, but never the thing refusing the stop. A task with no readable mtime
SHALL count LIVE (unknown is not abandoned). Any harness `TaskUpdate` rewrites
the file and SHALL thereby revive the task as ordinary blocking open work.

#### Scenario: the field wedge releases

- **GIVEN** a store holding only tasks untouched for 200h
- **WHEN** the session stops
- **THEN** the stop is allowed (exit 0)

#### Scenario: live work still holds the turn

- **GIVEN** the same store with a freshly written open task
- **WHEN** the session stops
- **THEN** the stop is refused, listing only the live task as blocking and the
  stale ones as inherited debt

### Requirement: An operator verb retires a dead list without weakening the lock

`open_work.py retire --session <sid> --reason <why>` SHALL rewrite each
targeted OPEN task to `completed` with `metadata.ct6_retired = {at, reason}`,
refusing LIVE open tasks unless `--force`, so the verb can never release a
turn the lock is holding. The store SHALL remain non-empty (registered). The
block message SHALL continue to never contain the substrate path (the F-A
rule); the human's surface is documented in the README.

#### Scenario: retire refuses live work

- **GIVEN** a fresh open task
- **WHEN** retire runs without --force
- **THEN** exit 1, the task stays open, and the refusal names --force

### Requirement: The heartbeat is the engaged run's pulse

The completion lock SHALL touch the active-run marker on a block ONLY when the
stopping session is ENGAGED (the marker's orchestrator session, or a
transcript that invoked a pipeline skill), so an abandoned run's marker can
cross `marker_is_stale` while unrelated sessions keep working in the repo.

#### Scenario: a foreign session's block does not refresh the marker

- **GIVEN** an active marker recording another session id and a lock block in
  this session
- **THEN** the marker's `updated_at` is unchanged

### Requirement: Refusals name the verb that fits the decision

`--mark-complete`'s worklist-debt refusal SHALL name `--stand-down` as the
abandonment path. The block's kill-switch section SHALL state that switches
are read from the launch environment (or settings env), and SHALL name both
staleness windows.
