# U3b-ui census: before and after the rewrite

Measured on this branch at the commit named in each row (D-069 item 6: evidence, not claims).

| Check | Before (base a2c09043) | After (this branch) |
|---|---|---|
| Cross-unit path specifiers in lane-owned files | 148 (dry run, 52 files) | 0 (dry run: `already-ou` 148, `same-unit` 85, `unresolved` 122, rewrite 0) |
| `scripts/units addresses` path importers of the 10 lane units | 148 | 3 on `ui-billboard`, 1 on `ui-playback`, 1 on `ui-shell`, all in files of other units (below) |
| `tsc --noEmit` (apps/web) | exit 0, no output | exit 0, no output |
| `vitest list --project unit` | 1256 lines | 1256 lines; identical after sorting (order of listing varies between runs) |
| `scripts/units check` | 104 valid, 0 errors | 104 valid, 0 errors |
| Touched test files | — | 1 + 3 + 5 + 2 files, all green; `lesson-row.test.ts` updated for the new address text |
| `scripts/unit-battery` (types + unit-tests) | — | green for all ten units |

## Remaining path importers (other units, not this lane's to rewrite)
- `apps/web/scripts/lib/perf-budget-home.test.ts` (`@/ui/Billboard/BillboardSelection`, `@/ui/Rail/eager`): tooling-perf.
- `apps/web/scripts/lib/perf-budget.ts` (`../../src/ui/Rail/eager.ts`): tooling-perf; a Node-run file (`perf:budget`), keeps its relative import.
- `apps/web/src/app/c/[courseSlug]/[lessonSlug]/view.tsx` (`@/ui/playback/LectureAbout`): app-course.
- `apps/web/scripts/lib/check-architecture.test.ts` (`@/ui/Footer/Footer`): tooling checks.

These are for their owners' U3b lanes; this PR does not edit other units' files.

## Test change
`src/ui/lesson-row/lesson-row.test.ts` asserted the alias text of `PlayerRail.tsx` (ui-playback, rewritten). The assertion now names the
address. No threshold, timeout or test was removed or skipped.
