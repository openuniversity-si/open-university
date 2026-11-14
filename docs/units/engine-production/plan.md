## Plan

Commits (sequential; each owns disjoint files):
1. `docs/units/engine-production/audit.md` — audit findings.
2. `docs/units/engine-production/plan.md` — this plan.
3. `scripts/tests/test_production_guard.py` — read the marker list once instead of once per environment variable, so the battery fits `battery.unit_time_limit` (limit untouched). Targeted test: `bash scripts/tests/production-guard.test.sh`, `scripts/unit-battery engine-production`.
4. `docs/units/engine-production/contract.md` — the published surface, why the `contract` slot stays empty, generated outputs.
5. `docs/units/engine-production/retro.md` after the final gate.

Premises: P-03 (units stay logical; confirmed, medium: a physical move would break every caller of the two executables), P-04, P-05 (zero literals already verified, low), P-07 (no contract change, high). CRITICAL: none.

Single final gate: `scripts/gate-dev --pr N`. Production is not touched: `production-check` and `preview-deploy` are not run; only their tests (stubs).
