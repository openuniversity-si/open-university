# U4 ui-foundation audit (read-only; cheap evidence only)

Brief: migrate unit `ui-foundation` (plan v3 §9.2 row U4, v3.1 §3). Base `mod/roadmap-integration` @ 76cc5f2d.

| Area | Evidence | Consequence |
|---|---|---|
| Physical form | S1 (P-03): units stay logical; `apps/web/src/ui/**` is also where `globals.css` imports the three stylesheets by relative path. No unit has moved. | No file moves, no old path to delete, no shim (D-029). `@ou/ui-foundation/*` already maps to `./src/ui/*`. |
| Size | 6 production files (fonts, lesson-figure, icons, 3 stylesheets); far below `units.size_ceiling` (1500). | Not oversize; no `unit.oversize`. |
| Importers | `rg "@ou/ui-foundation"`: `towerInter` (layout), `ChevronLeftIcon`, `ChevronRightIcon`, `PlayIcon` (nine ui and app files), `chosenLessonCover` (two ui files). The stylesheets are imported by path from `app/globals.css`, which a TypeScript entry cannot re-export. | The published surface is exactly those five names. |
| Contract slot | `contract = {entry, version}` in `contracts/units/unit.v1.json`; no entry yet. | Add `apps/web/src/ui/contract.ts`, version 1.0.0, plus a surface test. |
| Literals | No `x-literal-sites` entry names any of the unit's files. `fonts.ts` options must be static literals for `next/font`. | Allowlist already zero; nothing to shrink. |
| UI text | `icons.tsx` renders decorative SVG without visible text; the other files hold none. | No `text.*` entries needed; production `.tsx` joins `l10n.scoped_files` so it stays at zero. |
