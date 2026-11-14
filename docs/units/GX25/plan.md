# GX-25 plan

Deadline: 90 min from launch. Premises: P-32 (events never a clock, high), P-46 (pinned verdict, high), P-47 (switch, medium). None CRITICAL.

## Commits (Plan: N trailers)

1. Audit and plan (this file and `audit.md`). Files: `docs/units/GX25/*`.
2. Config: new `config/registry/gate-eta.json` (`eta_quantile` 0.5, `eta_history_events` 50, `started_enabled` true, `fallback_stage_s`, `report_quantiles`), generated module, unit manifest/CODEOWNERS through `scripts/generate`. Files: registry, generated, manifest.
3. `scripts/lib/gate_timing_report.py` (harvest GS2: critical path, p50/p90 per stage, ETA error from gate.started vs verdict) + `scripts/tests/gate-timing-report.test.sh`, `test_gate_timing_report.py`, covers sidecar. Files: those only.
4. `scripts/lib/slo.py`: `expected_seconds(events, names, quantile, window, fallback)` (step_stats at the quantile) + tests in `test_slo.py`. Files: slo.py, test_slo.py.
5. `scripts/lib/gate_status.py`: `begin` publishes `gate.started`; `final` calls `gate_slow` and `slo.run` on tier-1 verdicts; `started_enabled` switch; live panel shows the critical-path ETA instead of the sum; tests in `test_gate_status.py`. `docs/process/EVENTS.md` producer note.
6. RETRO `docs/units/GX25/retro.md`.

## Dependency graph / critical path

2 -> {3, 4} (parallel; different files) -> 5 -> 6. Real edges: 3,4 need the keys of 2 (fallback, quantiles); 5 needs `critical_path` (3) and `expected_seconds` (4). No collision edges (each commit owns distinct files). Critical path about 2 + 12 + 20 + 10 = ~45 min plus one gate run. Executed serially by the coordinator because each step is small; sub-agents would cost more than they save.

## Tests

Per commit: its own test file. Final: `scripts/run test gate-status`, `slo`, `gate-timing-report`, `event-contracts`, then the pinned `scripts/gate-dev --pr 740`.
