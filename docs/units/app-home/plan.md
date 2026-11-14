# U4 app-home plan (mirrored in the PR description)

## Commit plan
- [x] 1. Audit (`docs/units/app-home/audit.md`).
- [x] 2. Plan (this file).
- [x] 3. Contract: `apps/web/src/app/contract.ts` (the published surface), `contract.test.ts` (pins the surface to the imports of other units), manifest `contract {entry, version 1.0.0}` and path.
- [x] 4. UI text: the unit's production `.tsx` files join `l10n.scoped_files` (zero visible strings); fixture pages stay as they are.
- [x] 5. Generated outputs: `scripts/generate` (addresses, codeowners, aggregates, status) after the manifest edit.
- [x] 6. Retro (`docs/units/app-home/retro.md`) and the RETRO comment.

## Dependency graph and owned files
`1 -> 2 -> 3 -> 5`; `4` touches only `config/registry/l10n.json` and runs beside 3; `6` last. The coordinator is the sole committer.

| Commit | Files owned |
|---|---|
| 3 | `apps/web/src/app/contract.ts`, `apps/web/src/app/contract.test.ts`, `units/app-home/unit.json` |
| 4 | `config/registry/l10n.json` |
| 5 | generated outputs only |

## Decisions (reported, reversible)
- Physical form: logical (S1/P-03). No file moves; routes must stay in `src/app`. Nothing retired remains (D-029).
- The contract entry re-exports only names other units import today; the CSS module is not re-exportable and stays an address-path import.
- Literals: no `x-literal-sites` for these files; already zero (audit). UI text: no visible string in production files; fixture words are test data, left alone so browser tests keep asserting them.

## Premises
Premises: P-03, P-04, P-05, P-07. No CRITICAL premise (no production, money or source-of-truth change).
- (medium) P-03 logical form holds: a `contract.ts` inside `src/app` is not a Next route file.
- (low) The L1 lexical text check has no false hits on the listed files (verified in the audit).

## Targeted tests, then one final gate
3: `scripts/unit-battery app-home`, `scripts/units check`. 4: `structure-check`. 5: `scripts/generate --check`. Then one `gate-dev`.
