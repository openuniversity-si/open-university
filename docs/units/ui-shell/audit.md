# U4 ui-shell audit and plan (D-067, D-069, D-029)

Template: the merged `app-home` U4 (docs/units/app-home). Base `mod/roadmap-integration` @ 76cc5f2d.

## Findings
| Area | Evidence | Consequence |
|---|---|---|
| Physical form | S1/P-03: units stay logical; the unit lives in `apps/web/src/ui/{Footer,OverlayLayer,TopNav,TowerMark}`; `@ou/ui-shell/*` already maps there. | No file moves, no old path, no shim (D-029). |
| Size | ~330 production lines, 11 files, far under `units.size_ceiling`. | No `unit.oversize`. |
| Importers | `app/layout.tsx` (Footer, TopNav); `ui/identity` x3 (OverlayLayer). TowerMark, `fade`, `context` are unit-internal. | Surface = `Footer`, `TopNav`, `OverlayLayer`. |
| Literals | No `x-literal-sites` entry names these files. `FOOTER_FADE_DISTANCE` is a named design constant from Addendum 2.5 with its test; routes and test ids are the unit's own vocabulary. | Allowlist already zero. |
| UI text | Visible copy comes from `useShellCopy` / `site-domain/reader-copy` (other units). The only literal glyph is the `·` separator (not text). | The four production `.tsx` join `l10n.scoped_files`. |
| Battery | `scripts/unit-battery ui-shell` green (contract, types, unit-tests). | Contract step added through the manifest entry. |

## Commit plan
- [x] 1. `l10n.scoped_files` gains the four production files.
- [x] 2. `TopNav/contract.ts` (1.0.0) + `contract.test.ts` pinning it to the imports; manifest `contract`.
- [x] 3. Regenerated address map (`@ou/ui-shell` bare entry).
- [ ] 4. This audit and plan.

Premises: P-03, P-04, P-05, P-07.
