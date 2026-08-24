# Tasks — inherited-task-debt

- [x] D1 abandonment window: `partition_stale_tasks` + `task_stale_hours`
      (CT6_TASK_STALE_HOURS floored 1h, defaulting to the resolved marker
      window); `_mtime` captured in `read_harness_tasks`; the lock blocks on
      LIVE tasks only, stale surfaced in `stale_tasks` + an advisory reason.
      Red-first: stale-releases / fresh-still-blocks control pairs, floor pin,
      marker-window fallback pin, end-to-end hook pins in both directions.
- [x] D2 `open_work.py retire`: audit-trail rewrite (status completed +
      metadata.ct6_retired {at, reason}) via run_continuity's atomic write;
      refuses live tasks without --force (the closed boundary); --task subset;
      session-dir spelling accepted; store stays registered. Red-first ×7.
- [x] D3 block message: inherited-stale FYI section + task-store dir named;
      kill-switch section states the launch-env fact and names BOTH window
      levers; F-A pin preserved (block still never contains `open_work.py`).
- [x] D4 REFUSED --mark-complete names --stand-down (not gated by the audit).
- [x] D5 heartbeat scoped to `engaged` — foreign-session block leaves the
      marker's `updated_at` untouched; orchestrator control still touches.
- [x] D0 `_targets_measurement_artifact` normalizes backslash spelling;
      the pre-existing darwin-red pin `test_backslash_spelling_is_still_refused`
      goes green (recorded red in the v3.63.0 measurement).
- [x] Release: bump 3.64.0, README + CLAUDE.md + CODEBASE_MAP + RELEASE_HISTORY,
      archive-first, measure LAST, artifact, gate exit 0, merge.
