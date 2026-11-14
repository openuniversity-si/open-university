# GX-19 plan

## Commits (Plan: N trailers)
- [ ] 1 audit.md + plan.md
- [ ] 2 `config/registry/gate-gc.json` (`gate-gc.stage_timeout_s`, `gate-gc.reports_keep`, `gate-gc.build_cache_keep`) + generated module
- [ ] 3 `scripts/lib/gate_gc.py` (timeout lookup, report and build-entry retention) + exit hook call + tests
- [ ] 4 `step` enforces the stage limit (watchdog, exit 124, class env, log tail) + fixture test
- [ ] 5 `gate-build.py` publishes with renames only, refreshes recency on a hit + test
- [ ] 6 RETRO

## Dependency graph / critical path
2 -> 3 -> 4 are real edges (3 reads the keys, 4 calls gate_gc.py); 5 is independent (own file). One session writes all of it: the
diff is small, fan-out would cost more than it saves. Critical path ~40 min incl. one gate.

## Decisions
- Default `*` limit is 300 s as the plan says; stages the plan does not name but that run long (install, builds, e2e browsers, performance) get 600-900 s so a cold run is never a false red (GA-PG5: never shorter than the field p99). Raising an entry is the rollback.
- Timeouts are killed with TERM then KILL (5 s) over the process tree; exit 124; class `env` is printed directly (not guessed from the partial log).

## Tests / gate
Targeted: `test_gate_gc.py`, `gate-local.test.sh`, `gate-fixed.test.sh`. One final `gate-dev --pr` from a base-tip checkout (verdict of record) plus the own-checkout run (report-only).

Premises: GA-PG5 (P-47) low. Decision: D-070.
