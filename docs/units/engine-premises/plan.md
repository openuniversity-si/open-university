## Plan

Commits (each owns disjoint files):
1. `docs/units/engine-premises/audit.md`, `plan.md`: audit findings and this plan.
2. `scripts/lib/premises.py`, `scripts/lib/decision_premises.py`, `scripts/tests/test_premises.py`: read each registry value once per process and fix the stale P-03 assertion (KD-4db6e693). Targeted test: `scripts/unit-battery engine-premises`.
3. `docs/units/engine-premises/contract.md`: the published surface, why the contract slot stays empty.
4. `docs/units/engine-premises/retro.md` after the final gate.

Premises: P-03 (units stay logical; no physical move, medium), P-04, P-05 (zero literals verified, low), P-07 (no contract change: executable and module functions unchanged, high). CRITICAL: none.

Single final gate: `scripts/gate-dev --pr N`. Known base defects: tower-catalog cover concurrency and read-latency timing tests (not changed). KD-4db6e693 is resolved by `scripts/defects resolve` with the merge sha, after merge.
