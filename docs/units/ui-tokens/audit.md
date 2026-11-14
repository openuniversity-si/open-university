# ui-tokens audit (U4)

Read-only findings, base `mod/roadmap-integration` 8ec7a507.

- Unit: `apps/web/src/ui/tokens/**`: 13 stylesheets (generated `tokens.css` plus the screen sheets), `layout.ts` and 7 tests. Owner `ui-lane`; `requires` config-theme. Not above `units.size_ceiling` (no `unit.oversize`).
- Physical form: S1 keeps units logical (P-03). `app/globals.css` imports the sheets by relative path, the generator and its D-063 catalog entry name `tokens.css`, and no `.css` file may be edited in this PR, so a move would only churn them. Nothing moves and nothing is deleted (D-029). `@ou/ui-tokens/*` is generated into `apps/web/tsconfig.json`.
- Importers (consumer units, not edited): `app/layout.tsx` and `app/manifest.ts` import `TOWER_THEME_COLOR` from `@ou/ui-tokens/layout`; `app/globals.css` `@import`s the 13 sheets; three tests of other units read `tokens.css` (`ui/font-identity.test.ts`, `ui/TowerMark/TowerMark.test.ts`, `config/domain/documents.test.ts`).
- Tunables: `tokens.css` is a generated D-063 catalog. The other sheets are CSS and untouched. `layout.ts` held 28 numeric, regex and string offenders in the absolute baseline (`ui.json`); they were layout measures and the Spec 05 gradient constants.
- UI text: none; the one string is a developer error message, kept as a catalog key.
- Battery: the 7 tests of the unit, hermetic (they read files and call pure functions).
