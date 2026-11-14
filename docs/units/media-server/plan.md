## Plan

Commits (each owns disjoint files):
1. `docs/units/media-server/audit.md`, `plan.md`: audit findings and this plan.
2. `apps/web/src/media/server/admin.test.ts`, `config/registry/tests.json`: seed the noise source and drop the unit's `tests.unhermetic_sites` entry. Targeted test: `scripts/unit-battery media-server`.
3. `units/media-server/unit.json`, `docs/units/media-server/contract.md`: fill the contract slot (entry `index.ts`, version 1.0.0) and record the published surface computed from the import graph.
4. `docs/units/media-server/retro.md` after the final gate.

Premises: P-03 (units stay logical; no physical move, medium), P-04, P-05 (zero literals verified, low), P-07 (no behaviour change; contract added, high). CRITICAL: none.

Single final gate: `scripts/gate-dev --pr N`. Known base defects: tower-catalog cover concurrency and read-latency timing tests (not changed).
