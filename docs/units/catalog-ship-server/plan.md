## Plan

Commits (each owns disjoint files):
1. `docs/units/catalog-ship-server/audit.md`, `plan.md`: audit findings and this plan.
2. `bundle-apply.int.test.ts`, `config/registry/tests.json`: the race rounds and lead become registry entries (`tests.author_race_rounds` 24, unchanged; `tests.author_race_lead_ms` 250 -> 80) so the battery fits `battery.unit_time_limit`. Same rounds, same assertions.
3. `ship-batch.ts` (entry), `contract.test.ts`, `units/catalog-ship-server/unit.json`, `apps/web/tsconfig.json` (generated), `CODEOWNERS` (generated), `docs/units/catalog-ship-server/contract.md`: contract 1.0.0 with the published surface computed from the import graph.
4. `docs/units/catalog-ship-server/retro.md` after the final gate.

Premises: P-03 (units stay logical, no physical move, medium), P-04, P-05 (zero literals verified, low), P-07 (contract is additive, high), P-16. CRITICAL: none.

Single final gate: `scripts/gate-dev --pr N`. Known base defects: tower-catalog cover concurrency and read-latency timing tests (not changed).
