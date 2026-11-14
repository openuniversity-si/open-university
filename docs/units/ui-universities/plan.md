## Plan

Premises: P-03 (units stay logical; no physical move, medium), P-04, P-05 (no tunable literal and no owned text, low), P-07 (no contract change: exports unchanged, high). CRITICAL: none.

Commits (each owns disjoint files):
1. `docs/units/ui-universities/audit.md`, `plan.md` and `contract.md` (docs only).
2. The manifest `battery.command`; `scripts/generate --check` shows no drift.
3. `docs/units/ui-universities/retro.md` (docs only).

Single final gate: `scripts/gate-dev --pr N`.
D-069 items: 3 (no tunable literal), 5 (generated outputs), 8 (ownership), 14 (battery under the limit, never loosened), 15 (no owned text).
