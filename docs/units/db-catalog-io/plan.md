## Plan

Commits (each owns disjoint files):
1. Battery fits its limit: `queries.int.test.ts` and the manifest `battery` slot.
2. `docs/units/db-catalog-io/audit.md`, `plan.md`.
3. `docs/units/db-catalog-io/contract.md`.
4. `docs/units/db-catalog-io/retro.md` after the final gate.

Premises: P-03 (units stay logical, medium), P-04, P-05 (zero literals verified, low), P-06 (no SQL outside the db package, no migration, high), P-07 (no export changes, high). CRITICAL: none.

Single final gate: `scripts/gate-dev --pr 630`. Known base timing tests (tower-catalog cover concurrency, read-latency) are not changed.
