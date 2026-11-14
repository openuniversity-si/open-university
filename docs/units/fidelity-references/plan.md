## Plan

Commits (each owns disjoint files):
1. `docs/units/fidelity-references/audit.md`, `plan.md`: audit findings and this plan.
2. `docs/units/fidelity-references/contract.md`: the published surface and why the manifest slot stays empty.
3. `docs/units/fidelity-references/retro.md` after the final gate.

Premises: P-03 (units stay logical; no physical move, medium), P-04, P-05 (zero literals verified, low), P-07 (no contract change: exports unchanged, high). CRITICAL: none.

Single final gate: `scripts/gate-dev --pr N`. Known base defects: tower-catalog cover concurrency and read-latency timing tests (not changed).
