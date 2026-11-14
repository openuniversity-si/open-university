## Plan

Commits (each owns disjoint files):
1. `docs/units/db-migrations/audit.md`, `plan.md`: audit findings and this plan.
2. `units/db-migrations/unit.json` gets `contract` (`entry: meta/_journal.json`, `version: 1.0.0`); `scripts/generate addresses` regenerates the bare `@ou/db-migrations` key in `apps/web/tsconfig.json`. The battery gains its `contract` step.
3. `docs/units/db-migrations/contract.md`: the published surface, its version and the expand->contract rule.
4. `docs/units/db-migrations/retro.md` after the final gate.

Premises: P-03 (units stay logical; no physical move, medium), P-04 (size under the ceiling, low), P-05 (zero literals verified, low), P-06 (global journal, numbers from the train, high), P-07 (contract recorded at 1.0.0, no breaking change, high).

Single final gate: `scripts/gate-dev --pr N`. Known base defects: tower-catalog cover concurrency and read-latency timing tests (not changed).
