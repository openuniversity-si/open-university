# U4 ui-foundation plan (mirrored in the PR description)

## Commit plan
- [x] 1. Audit (`docs/units/ui-foundation/audit.md`).
- [x] 2. Plan (this file).
- [ ] 3. Contract: `apps/web/src/ui/contract.ts`, `contract.test.ts`, manifest `contract {entry, version 1.0.0}`.
- [ ] 4. UI text scope: `icons.tsx` joins `l10n.scoped_files`.
- [ ] 5. Generated outputs (`scripts/generate`).
- [x] 6. Retro.

## Decisions (reported, reversible)
- Physical form: logical (S1/P-03); nothing moves, nothing retired remains (D-029).
- Contract re-exports only names other units import today; stylesheets stay path imports.
- Literals already zero; no text to move.

Premises: P-03, P-04, P-05, P-07.
