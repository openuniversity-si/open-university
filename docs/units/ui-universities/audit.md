# ui-universities audit (U4)

Read-only findings, base `mod/roadmap-integration` b3b1a359.

- Unit: 11 files of `apps/web/src/ui/CountrySection/` and `apps/web/src/ui/Universities/` (5 modules, 2 stylesheets, 4 tests), 696 lines in total; `scripts/units check` raises no `unit.oversize` (`units.size_ceiling` 1500), nothing split here. Owner `ui-lane`.
- Physical form: S1 keeps units logical (P-03 `validated`); `units/ui-universities/` holds only the manifest, and `@ou/ui-universities/*` is generated into `apps/web/tsconfig.json`. The files keep their paths, so nothing moves and nothing is deleted (D-029).
- Importers (consumer units, not edited): 5 files, all already through `@ou/ui-universities/<path>`. `screen-measures.test.ts` and `countries.test.ts` read the unit's files by path; they keep working because the paths are unchanged.
- Imported surface (the contract) is in `contract.md`.
- Tunables: `config_check` reports none and no `x-literal-sites` entry names these files. The remaining D-063 absolute census entries (`ui.json`) shrink only through the D-063 catalogs, as in the other U4 units; no value is added.
- UI text: none owned here. Every sentence is already imported from `@ou/site-domain/reader-copy.ts` and `@ou/ui-showcase/showcase/shelf-sentences.ts`, and the other-countries title from `@ou/catalog-hierarchy/config`; nothing moves to `text.*` in this PR.
- Battery: `scripts/unit-battery ui-universities` green in about 5.5 s (types 9 files, unit 4 files) against `battery.unit_time_limit`. Tests are hermetic: no network.
