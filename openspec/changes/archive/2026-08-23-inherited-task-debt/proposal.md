# inherited-task-debt (v3.64.0)

## Why

A field report (2026-08-23, a production workspace on plugin 3.63.0): the
completion lock held every turn on four open harness tasks left behind by
TERMINATED sessions — task lists outlive sessions (resume / continue / compact
keeps the store, teams keep the team store, the harness carries lists across
forks), and the lock had no concept of abandonment. The operator ran the one
command the block printed (`run_continuity.py --mark-complete`); it governs a
DIFFERENT gate and REFUSED anyway on the dead runs' worklist debt. The env
kill-switches worked but only in the launch environment, a fact stated
nowhere. The wedge was self-sustaining: every lock block heartbeat the dead
run's marker, so it could never cross the staleness window. Net field
experience: "there is no way to override."

## What

Six closures shipped together: D1 staleness discrimination for the task-list
source (mtime vs an abandonment window; stale = surfaced, never blocking);
D2 an operator `open_work.py retire` surface that cannot touch live tasks
without `--force`; D3 block-message truth (stale section + store dir + the
launch-env fact + the window levers named); D4 the `--mark-complete` refusal
names `--stand-down` as the abandonment verb; D5 the lock's marker heartbeat
scoped to ENGAGED sessions; D0 the pre-existing darwin-red backslash pin on
the measurement-immutability arm closed. Full detail in the delta spec and
CHANGELOG.
