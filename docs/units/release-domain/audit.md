# release-domain audit (U4)

Read-only findings, base `mod/roadmap-integration` 76cc5f2d.

- Unit: all 27 files of `apps/web/src/release/domain/` (14 modules plus `intents.ts`, `preview.ts` and 11 tests), 1,013 production lines and 713 test lines; `scripts/units check` raises no `unit.oversize` (`units.size_ceiling`), nothing split here. Owner `release-lane`.
- Physical form: S1 keeps units logical (P-03 `validated`); `units/release-domain/` holds only the manifest and the gate suite renames, and `@ou/release-domain/*` is generated into `apps/web/tsconfig.json`. The files keep their paths, so nothing moves and nothing is deleted (D-029).
- Importers (consumer units, not edited): 50 files, all already through `@ou/release-domain/<file>`.
- Imported surface (the contract) is in `contract.md`.
- Tunables: `config_check` reports none and no `x-literal-sites` entry names these files. The D-063 absolute census is shared with the catalog area and shrinks only through the D-063 catalogs, as in the other U4 units.
- UI text: none owned here.
- Base defect fixed: `countries.test.ts` still asserted the old `@/catalog/domain/config` import in `CountrySection.tsx`; the component imports `@ou/catalog-hierarchy/config` since U3b, so the battery was red. The assertion now names the real import; no threshold or test removed.
- Battery: `scripts/unit-battery release-domain` green in about 5.7 s (types 27 files, unit 11 files) against `battery.unit_time_limit`. Tests are hermetic: no network.
