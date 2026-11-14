# U4 ui-lesson-row plan (mirrored in the PR description)

## Commit plan
- [x] 1. Audit and plan (`docs/units/ui-lesson-row/`).
- [x] 2. Contract: `apps/web/src/ui/lesson-row/contract.ts`, `contract.test.ts` (pins the surface to the imports of other units), manifest `contract {entry, version 1.0.0}`.
- [x] 3. UI text: the row's accessible-name template moves to `text.lesson_row_label` (read through `lesson-row/copy.ts`); `CourseProgress.tsx` joins `l10n.scoped_files`. Residual (D-006 guard): `CoursePlaylist.tsx` (`${noun}s` aria-label, list heading and count) and the row's trailing-mark ternary stay as they are, because any edit of their JSX lines is a visual change and no `visual: yes` capability with a figma node exists; no visual change is allowed here.
- [x] 4. Generated outputs: `scripts/generate` (addresses, CODEOWNERS, aggregates) after the manifest edit.
- [x] 5. Retro (`docs/units/ui-lesson-row/retro.md`).

## Decisions (reported, reversible)
- Physical form: logical (S1/P-03). No file moves; nothing retired remains (D-029).
- Contract re-exports only names other units import today; expand->contract (P-07).
- Literals already zero; UI text: no visible string in the unit, so no `text.*` entries move.

## Premises
Premises: P-03, P-04, P-05, P-07.
- (medium) P-03 logical form holds: `contract.ts` in `ui/lesson-row` is not a route file.
- (low) The L1 lexical check has no false hits on the unit's `.tsx` files.
