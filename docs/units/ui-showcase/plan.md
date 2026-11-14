# ui-showcase: plan

Premises: P-03 (units stay logical, medium), P-04, P-05 (one string moves, low), P-07 (additive contract, no consumer edited, high). CRITICAL: none.

Commits (each owns disjoint files):
1. `audit.md`, `plan.md`, `contract.md`.
2. UI text: `CreditsList.tsx` and `AreaGrid.tsx` join `l10n.scoped_files`; the "Last updated" move waits for a visual capability (D-006).
3. Contract: `showcase/contract.ts`, its test, manifest `contract` and `battery.command`, and the generated `@ou/ui-showcase` address (`scripts/generate addresses`).
4. `retro.md` after the final gate.

One final `scripts/gate-dev --pr N`. D-069 items: 3, 5, 8, 14, 15. D-067, D-029.
