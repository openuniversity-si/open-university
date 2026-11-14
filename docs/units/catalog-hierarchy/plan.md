## Plan

Premises: P-03 (units stay logical; no physical move, medium), P-04, P-05 (no tunable literal; D-063 census untouched, low), P-07 (no contract change: exports unchanged, high), P-16. CRITICAL: none.

Commits (each owns disjoint files):
1. `docs/units/catalog-hierarchy/audit.md`, `plan.md`, `contract.md` and the manifest `battery.command`; `scripts/generate --check` shows no drift, so no generated file changes.
2. `plan.md` records the commits as made (the contract document and battery command landed in commit 1).
3. `docs/units/catalog-hierarchy/retro.md` after the final gate.

Single final gate: `scripts/gate-dev --pr N`. Known base defects: tower-catalog cover concurrency and read-latency timing tests (not changed).
D-069 items: 3 (no tunable literal), 5 (generated outputs), 8 (ownership), 14 (battery under the limit, never loosened).
