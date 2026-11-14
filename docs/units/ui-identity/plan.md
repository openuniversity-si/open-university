# U4 ui-identity plan

Premises: P-03, P-04, P-05, P-07. None critical (no production, money or source-of-truth change). D-067, D-069 (3, 5, 8, 14, 15), D-029.

## Commit plan
- [x] 1. Audit and plan (`docs/units/ui-identity/`).
- [ ] 2. Contract: `contract.ts` (the three imported names), `contract.test.ts`, manifest `contract {entry, version 1.0.0}`, relative imports in `AuthShell`, regenerated address.
- [ ] 3. UI text: the unit's `.tsx` files join `l10n.scoped_files`.
- [ ] 4. Retro.

Decisions (reversible): logical form; contract names computed from the import graph; CSS modules not re-exported.
Tests: `scripts/unit-battery ui-identity`, `scripts/structure-check`, one final `gate-dev`.
