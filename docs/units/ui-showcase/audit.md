# ui-showcase audit (U4)

Read-only findings, base `mod/roadmap-integration` a52ec158.

- Unit: `apps/web/src/ui/{CreditsList,LegalPage,showcase}/**`, 627 production lines (`scripts/units measure`), under `units.size_target` and `units.size_ceiling`; no `unit.oversize`. Owner `ui-lane`.
- Physical form: S1 keeps units logical (P-03). The unit's three folders sit among sibling UI folders and its stylesheets are imported by relative path, so a move would only churn them. Nothing moves and nothing is deleted (D-029). `@ou/ui-showcase/*` already maps to `apps/web/src/ui/*` in the generated `tsconfig.json` paths.
- Importers (other units, not edited): `app-home` pages (`about`, `contact`, `credits`, `privacy`, `terms`, `page.tsx`, `signed-in-home`), `app-course` (`course-opening`), `app-universities` (`AreaGrid`, `shelf-sentences`), `app-authors` (`home-shelves`), `ui-billboard` (`HomeShelf` type), `ui-universities` (`shelf-sentences`) and the `release-domain` credits test (`CreditsList`). All use `@ou/ui-showcase/<folder>/<file>`.
- Imported surface (the contract) is in `contract.md`; `showcase/contract.ts` publishes it and `showcase/contract.test.ts` pins it to the imports.
- Tunables: no `x-literal-sites` entry names these files and they spell no engine parameter; values come from `site-domain` copy. The allowlist for them is already zero.
- UI text: one visible string, "Last updated" in `LegalPage.tsx`. Editing that line is a markup change, which the D-006 visual guard refuses without a `visual: yes` capability with a Figma node, and none exists; the string stays and is recorded as a follow-up. `CreditsList.tsx` and `AreaGrid.tsx` have no visible string and join `l10n.scoped_files`.
- Battery: `scripts/unit-battery ui-showcase`.
