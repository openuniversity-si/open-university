# U4 app-course audit (read-only; D-067, D-069, D-029)

Base: `mod/roadmap-integration` at a2c09043 (includes LR1 #575, CO1 #576). Evidence is from the repository on that head.

## The unit
`units/app-course/unit.json`: paths `apps/web/src/app/c/**` and `apps/web/src/app/signed-in-c/**`, owner `app-lane`, no `contract`,
no `battery`. 14 production files (308 lines, 5 `.tsx` views/pages in `c/`, 8 one-line or thin files in `signed-in-c/`, 2 `.css`),
no test file of its own. Far below `units.size_ceiling` (1500): no `unit.oversize`.

## Findings
1. **Physical move.** S1 (P-03, `docs/process/spikes/S1-progress-workspace-package.md`) answered: units stay logical; "U4 moves nothing physically; it
   migrates literals and imports to `@ou/<id>` addresses inside `apps/web/src`". Independently, Next's App Router needs these routes
   under `src/app`. So scope item 1 is a no-move: the address `@ou/app-course/*` (generated into `tsconfig.json` `paths`) stays the seam.
2. **Importers.** Only one file outside the unit imports it: `src/app/(test)/fixtures/states/page.test.tsx`
   (`@ou/app-course/c/CatalogLoading`, default export). Other mentions of the paths (`lesson-figure.test.ts`,
   `lesson-stage.test.ts`, `screen-measures.test.ts`, `progress-reading.test.ts`, `home-routing*.test.ts`, `course-opening.test.ts`)
   read the files as text; they are not imports. The published surface is therefore the `CatalogLoading` default export.
3. **Off-address imports inside the unit.** `signed-in-c/**` imports `@/app/c/...` (4 files) and `c/[courseSlug]/[lessonSlug]/view.tsx` imports
   `@/ui/playback/LectureAbout`, although `@ou/ui-playback/*` and `@ou/app-course/*` exist. Class: any `@/` import in the unit.
4. **Literals** (`scripts/lib/absolute-literals-baseline/app.json`, D-063): `status`, `course` (x9), `tabpanel`, `"true"` (aria-hidden, x3),
   `true`/`false` (`dynamicParams`, `revalidate`, route segment `dynamic = "force-dynamic"` x2) in `.tsx`; plus the `.css` rows
   (numbers, owned by the CSS files, which this PR must not touch). Template strings `/c/${slug}`, `course-lessons-heading-${slug}` embed route and id words.
   Vocabulary for these words lives in `src/app/vocabulary.ts`, owned by `app-home`, so the unit cannot extend it.
5. **User-facing text.** None is written in the unit: every visible string comes from `@ou/site-domain/reader-copy` or from the lesson stage
   (`@ou/ui-playback/lesson-stage`). `aria-hidden`, `role`, test ids are markup words (D-063 vocabulary), not locale text. So no `text.*` entry
   is needed; the L1 text check (`scripts/lib/text_check.py`) must keep passing.
6. **Battery.** `scripts/unit-battery app-course`: green, 6.68 s (types, 15 files), limit `battery.unit_time_limit` = 10 s.
7. **Next constraint.** Route segment config (`dynamic`, `dynamicParams`, `revalidate`) must be statically analyzable literals; an imported
   constant breaks the build. The existing mechanism for `revalidate` is `false satisfies typeof CACHE.untilTagged`.

## Known base defects and owners
- `.css` literal rows in the baseline cannot reach zero without editing `.css` (forbidden here); owner: the visual lane, recorded in the PR.
- `src/app/vocabulary.ts` belongs to `app-home` (separate U4 PR); this PR adds its own `c/vocabulary.ts`.
