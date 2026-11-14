# B1 audit: performance budgets with a measured baseline

Read-only findings with evidence (D-069 items 5, 6, 14). Base `a2c09043` (#576 merged). Restart from the merged base; the
earlier branch is not reused.

## What exists and must be reused
- **Registry**: `config/registry/budgets.json` already holds `budgets.admin_list_read_ms_max` (a perf-test ceiling, tightens
  only), `budgets.pr_changed_lines`, `budgets.pr_commits_min|max`. No bundle, latency or tolerance entry exists. The file has
  no unit owner (`scripts/units owner config/registry/budgets.json` -> none).
- **Battery limit**: `battery.unit_time_limit` (10 s, `config/registry/battery.json`) is the one name for the per-unit battery
  budget; `scripts/lib/unit_battery.py` reads it and sets `over_limit`. B1 reads it and adds no second name.
- **Measurements**: `unit_battery.emit` publishes `engine.step.measured` through the forge_events port, step =
  `battery.unit_step`, `payload.unit` = the unit, `duration_ms` from the injected clock; one event per battery and one per
  sub-step. Re-emitting at the same sha is a no-op (natural key).
- **Reader**: `scripts/lib/slo.py` (O1) has `collect(adapter, repo)`, `ordered`, `percentile` (nearest rank, `slo.percentile`)
  and `step_stats`. B1 imports them; no second percentile or fold.
- **Structure-check modules**: `config_check` compares registry files with the base (`_registry_params_at`, `x-literal-sites`
  shrink-only). B1's looseness check follows that pattern. `structure.py` calls modules in `main`.
- **Generator**: `generate.targets` derives files from repo files; the baseline is derived from the event log, which is not in
  the repo, so it cannot be a drift-checked target. It is a committed, schema-validated file written by `scripts/budgets
  baseline --write` with its provenance (newest event id, sample count, percentile, window).
- **Decisions**: D-069 item 14 (budgets in config, regression against the baseline, never loosen), D-064 (f) (180 s ceiling
  stays a warning), D-025 (gate files change only with a cited decision), D-068 (every value in the registry).

## Measured, not guessed
- The real event log (`forge-events.adapter` = github, repo channel) holds 9 events: 8 `defect.detected`, 1 `config.changed`.
  **No `engine.step.measured` event exists yet**, so there is no battery baseline to compute from the log today.
- A local build (`pnpm build` in `apps/web`) is measured for the bundle; see the plan for how that number enters the registry.
- No page-latency probe exists (no server runs in the offline gate; e2e is report-only for pixels).

## Gaps B1 must close
1. No bundle, latency or tolerance budget; no reader that turns events into a baseline.
2. No refusal when a budget is made looser.
3. No event for a non-duration measurement (bytes). `engine.step.measured` carries `duration_ms` only; an additive
   `budget.measured` v1 carries `metric`, `value`, `unit_of_measure` (M2 owns the event catalog; additive only).

## Known base defects expected
- tower-catalog cover concurrency ('expected 6 to be 7') and read-latency ('lists 10,000 courses in under a second') on 4 vCPU:
  timing-sensitive, owned by the perf stage (H0); never changed here.
