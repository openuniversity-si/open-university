# TX13 audit

Base: `origin/mod/roadmap-integration` f1af963d. Measured the way `scripts/lib/budgets.py check-bundle` measures (sum of
`apps/web/.next/static/**/*.js`, `budgets.bundle_globs`, budgets.json:29-33; budgets.py:154-159) after `catalog:bake` and
`next build` with `TOWER_GATE_TYPECHECK=1` (scripts/lib/gate-build.py:150-161), in a throwaway worktree.

## Evidence re-verified

- Limit: config/registry/budgets.json:291-296 `budgets.web_bundle_bytes_max` 695296 (694601 measured 2026-10-27, 19 files).
- Base tip f1af963d: **695469 bytes, 19 files** (reproduces the #742 gate value exactly).
- Correction to the brief: 1b2901ef2 (B1, 06:57Z) is not on the first-parent line. B1 (#580) merged as 0c45afa3 at
  02:53:58Z, after #607 and #605 in the same train batch; #605 and #607 did not change the bundle.

## Bisect (first-parent merges of the base)

| commit | merge | bytes |
|---|---|---|
| a2c09043 | merge-base of B1 and the base | 694601 |
| 158e4840 | #630 | 694601 |
| 06dda543 | #652 | 694601 |
| 49ef3345 | #655 | 694601 |
| f8016e83 | #651 | 694601 |
| **f02bff91** | **#658 ui-lesson-row** | **695469** |
| 6431217c | #730 | 695469 |
| 644b5ab5, 2b3087ce, 5527dd77, 57b653a0 | #671, #607, #605, #726 | 695469 |
| 0c45afa3 | #580 (B1) | 695469 |
| bb30c617 | B1 head at its last gate | 695469 |

The crossing merge is **#658** (f02bff91, `claude/u4-ui-lesson-row`): +868 bytes, and nothing else moved it since.

## Cause

#658 moved the row's accessible name into the registry (L1) through
`apps/web/src/ui/lesson-row/copy.ts:5` `import texts from "@ou/site-text/text.json"`, called from the client component
`apps/web/src/ui/lesson-row/PlaylistItem.tsx:7,49` (`"use client"`). The client chunks now carry the whole generated text
document as a CommonJS module (`locales`, the `text` map and `inDefaultLocale`, including the unrelated empty-catalog
strings), once in each of two route chunks: `34ptx_e0dzkta.js` 22040 -> `1qokoldftzot_.js` 22474 and `3n-_0u0w_om8j.js`
34688 -> `1490pg9yhp0o1.js` 35122, +434 bytes each. A JSON module is not tree-shaken, so each new registry text would
grow every client chunk that reaches it.

Before #658 the document was only read by server code (`src/ui/EmptyCatalog/copy.ts:5`, a server component). The
rows are built on the server already (`src/ui/showcase/course-opening.ts:81-92`, `src/ui/playback/lesson-stage.ts:87-94`),
and `PlaylistItem` documents "The caller writes the meta and the accessible text" (PlaylistItem.tsx:25).

## Why the crossing merge was green

- #658's own gate predates the budget: `check-bundle` entered `gate-build.py` with B1 (cdfb60b8, 07:14Z) and the budget
  itself (#580) merged at 02:53Z on 10-28, so no gate judged #658 against the limit.
- B1's own gates never built production after it set the limit: its gate tables on ee737219 (13:38Z) and bb30c617
  (01:34Z) list only secret scan, structure, generated drift, schema compat and script tests; its diff touches no
  web-build input, so the gate plan skipped `build (production)`. B1's head already measured 695469 > 695296.
- The train judged the batch on the combined result (Tier 2) without a production build, so the first gate that built
  production on the merged base was the next PR that touched a web-build input or carried the full set (#586, #742).

## Fix location (lanes)

- `src/ui/lesson-row/*`, `src/ui/PlaylistItem/*` (ui-lesson-row), `src/ui/playback/*` (ui-playback),
  `src/ui/showcase/*` (ui-showcase): ui-lane.
- The only hand-built row outside the builders: `src/app/(test)/fixtures/long-titles/page.test.tsx:29` (app-home,
  app-lane), asserted by `e2e/states.spec.ts:126-127`.
- Rejected: splitting `CoursePlaylist.tsx`/`PlayerRail.tsx` into a server wrapper and a client view moves their literals
  to new files, which the per-file absolute-literal census refuses (`apps/web/scripts/lib/absolute-literals.ts:467-477`)
  without rewriting `scripts/lib/absolute-literals-baseline/ui.json` (engine-lane).
