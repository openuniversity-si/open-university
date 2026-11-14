# config-theme: plan

Premises: P-03 (units stay logical; the generator and its test name these paths, medium), P-04, P-05 (generated D-063 catalogs, allowlist already zero, low), P-07 (no contract change: exports unchanged, high). CRITICAL: none.

Commits (each owns disjoint files):
1. `audit.md`, `plan.md`, `contract.md`.
2. Manifest `battery.command`; `scripts/generate --check` shows no drift.
3. `retro.md` after the final gate.

One final `scripts/gate-dev --pr N`. D-069 items: 3 (no tunable literal), 5 (generated outputs), 8 (ownership), 14 (battery under the limit, never loosened). D-067, D-029.
