# TX13 plan

The row's accessible name is written on the server, where the rows are built, and the client row only reads it. The text
registry stays the one spelling (`copy.ts` keeps reading `@ou/site-text/text.json`).

Why expand/contract: the only hand-built row outside the builders is the app-lane long-titles fixture
(`src/app/(test)/fixtures/long-titles/page.test.tsx:29`, asserted by `e2e/states.spec.ts:126-127`). A required `name` breaks
its typecheck (TS2741, measured), a separate app-lane PR cannot go first (its own gate builds production on the red base and
fails the same budget), and the train refuses a two-lane head. Splitting `CoursePlaylist`/`PlayerRail` into server + client
files moves census literals between files, which `absolute-literals.heavy.test.ts:15` refuses without the engine-lane
baseline. So this PR is the expand step and is green alone.

Commits on mod/tx-bundle (ui-lane; each green alone; trailers `Plan: N`, `Decision: D-070`; one push each):

1. Audit (bisect) and this plan. Files: docs/units/TX13/{audit,plan}.md.
2. Expand fix. `PlaylistItem.tsx`: `CourseLessonRow.name?`, the row takes a named lesson and paints
   `aria-label={lesson.name}`, no copy import. `course-opening.ts`, `lesson-stage.ts`: rows carry
   `name: lessonRowLabel(row)` (server). `PlayerRail.tsx`: takes named rows. `CoursePlaylist.tsx`: names a hand-built row
   that has none (the fixture) with `lessonRowLabel`, the one remaining client reader. Tests: both builders assert the
   name; `lesson-row.test.ts` asserts the row and the rail never import the registry reader.
   Targeted: `pnpm vitest run src/ui`, `pnpm build` + the bundle measure, `scripts/tests/budgets.test.sh`.
3. Retro and gate evidence (docs/units/TX13/retro.md).

After this PR merges (separate PRs, one per lane, each green alone on a green base):
- app-lane: the long-titles fixture writes `name: lessonRowLabel(...)` (no change to its rendered name).
- ui-lane (contract step): drop the `CoursePlaylist` fallback, make `name` required, extend the TX13 test to every client
  module under `src/` (none reaches `src/generated/text/`). Measured with both: 694535 bytes.

Premises:
- P-46 (from the brief). Radius: low here; no gate file, budget or covers manifest changes.
- CRITICAL: the limit is not raised. `git diff origin/mod/roadmap-integration...HEAD -- config/registry/budgets.json` stays empty.
- Every row's accessible name is unchanged (same template, same values): e2e `course.spec.ts:18`, `states.spec.ts:127`.
- No literal added or removed in a census file (per-file absolute-literal census untouched).

Single final gate: pinned offline `gate-dev --pr 756` on the exact head (OU_CONFIG_STORE=file path).
