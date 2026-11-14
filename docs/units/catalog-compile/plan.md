## Plan

Premises: P-03 (units stay logical; no physical move, medium), P-04, P-05 (no tunable literal, low), P-07 (no contract change: exports unchanged, high), P-16. CRITICAL: none.

Commits (each owns disjoint files):
1. `docs/units/catalog-compile/audit.md`, `plan.md`: audit findings and this plan.
2. `docs/units/catalog-compile/contract.md` and the manifest `battery.command`; `scripts/generate` shows no drift.
3. `docs/units/catalog-compile/retro.md` after the final gate.

Single final gate: `scripts/gate-dev --pr N`.
D-069 items: 3 (no tunable literal), 5 (generated outputs), 8 (ownership), 14 (battery under the limit, never loosened).
