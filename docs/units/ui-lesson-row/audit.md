# U4 ui-lesson-row audit (read-only; cheap evidence only)

Brief: migrate unit `ui-lesson-row` (plan v3 §9.2 row U4, v3.1 §3): physical form, explicit versioned contract, zero literals, battery, generated outputs, UI text in `text.*`. Precedent: `docs/units/app-home/`.

## Findings
| Area | Evidence | Consequence for U4 |
|---|---|---|
| Physical form | `docs/process/spikes/S1-progress-workspace-package.md`: units stay logical (manifest + `@ou/<id>` address + checked boundary); "U4 moves nothing physically". | Step 1 is satisfied by the address: no file moves, no old path to delete, no shim (D-029). `@ou/ui-lesson-row/*` already maps to `./src/ui/*`. |
| Size | `scripts/units measure`: 409 production lines, ceiling `units.size_ceiling` 1500, 6 files. | Not oversize; no `unit.oversize`. |
| Importers | `rg "@ou/ui-lesson-row"`: `playback/PlayerRail.tsx` (`CourseProgressBar`, `CourseProgressPercent`, `WatchedProgress`, `PlaylistItem`, `CourseLessonRow`, `LessonRowMark`), `app/c/[courseSlug]/(course)/view.tsx` and `long-titles/page.test.tsx` (`CoursePlaylist`). | The published surface is exactly those seven names. `PlaylistPart` is unit-internal. The CSS modules stay unit-internal. |
| Contract slot | `contracts/units/unit.v1.json` `contract = {entry, version}`; the entry is relative to the address home (`apps/web/src/ui`). | Add `lesson-row/contract.ts`, version `1.0.0`. |
| Literals | No `x-literal-sites` entry for the unit's files; values come from `@ou/site-domain` copy (`reader-copy`). The `${noun}s` / `aria-label` join punctuation is template structure, not a tunable. | Allowlist already zero; nothing to shrink. |
| UI text | `l10n.scoped_files` lists only `EmptyCatalog.tsx`. All visible words in the unit come from `reader-copy` (site-domain) or the caller. | No text moves; the unit's `.tsx` files join `l10n.scoped_files` so the gate keeps them at zero visible strings (the L1 check verifies). |
| Battery | `scripts/unit-battery ui-lesson-row` green (limit `battery.unit_time_limit`). | Gains a `contract` step. |
