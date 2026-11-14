# U4 ui-lesson-row retro

- Logical form (S1/P-03): nothing moved; `@ou/ui-lesson-row` is the generated address, contract entry `lesson-row/contract.ts` v1.0.0 (seven names, pinned to the importers by `contract.test.ts`).
- The audit said "no visible string" before the L1 check ran; it found the row's `aria-label` template and parser false positives on a nested ternary. First fix (extract `trailingMark`, template the list heading) edited JSX lines, which the D-006 visual guard counts as a visual change, so structure-check went red. Final scope: only the non-markup `aria-label` line moves to `text.lesson_row_label`; `CoursePlaylist.tsx` and the ternary stay and are not in `l10n.scoped_files`. Follow-up (for the owner of a visual capability with a figma node): move the list heading/count templates and the ternary.
- Lesson: run `structure-check --pr-body` with the diff before writing the audit's UI-text row; and a text move that touches a JSX line is a visual-capability question, not a lane-only one.
- `scripts/generate intents` fails on this base (known `intents-doc.ts` defect); other targets were regenerated one by one. Size 409 lines, not oversize.
