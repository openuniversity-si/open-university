# U4 ui-course-card plan (mirrored in the PR description)

- [ ] 1. Audit and plan (`docs/units/ui-course-card/`).
- [ ] 2. Contract: `CourseCard/contract.ts` (published surface), `contract.test.ts` (pins it to other units' imports), manifest `contract {entry, version 1.0.0}`.
- [ ] 3. UI text: the unit's `.tsx` files join `l10n.scoped_files` (zero visible strings).
- [ ] 4. Generated outputs: `scripts/generate` (addresses, codeowners, locale-text) after the manifest edit.

Decisions (reported, reversible): logical form (S1/P-03); entry re-exports only imported names; no literal sites or text to move (audit). Premises: P-03, P-04, P-05, P-07.
