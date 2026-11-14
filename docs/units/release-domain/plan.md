## Plan

Premises: P-03 (units stay logical; no physical move, medium), P-04, P-05 (no tunable literal, low), P-07 (no contract change: exports unchanged, high). CRITICAL: none.

Commits (each owns disjoint files):
1. `countries.test.ts` follows the `@ou/catalog-hierarchy/config` import (battery was red on a stale assertion).
2. `docs/units/release-domain/audit.md`, `plan.md`, `contract.md` and the manifest `battery.command`; `scripts/generate --check` shows no drift.
3. `docs/units/release-domain/retro.md` (docs only).

Single final gate: `scripts/gate-dev --pr N`.
D-069 items: 3 (no tunable literal), 5 (generated outputs), 8 (ownership), 14 (battery under the limit, never loosened).
