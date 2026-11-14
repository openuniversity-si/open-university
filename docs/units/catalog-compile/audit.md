# catalog-compile audit (U4)

Read-only findings, base `mod/roadmap-integration` c9e8f890.

- Unit: 4 files under `apps/web/src/catalog/domain/` (`compile`, `incremental-compile`, `release`, `release.test`), 1,218 lines, under `units.size_ceiling` (no `unit.oversize`). Owner `catalog-lane`.
- Physical form: S1 keeps units logical (P-03 `validated`). The files share `catalog/domain/` with other catalog units, so nothing moves and nothing is deleted (D-029). `units/<id>/` holds only the manifest; `@ou/catalog-compile/*` is generated into `apps/web/tsconfig.json`.
- Importers (consumer units, not edited): 25 files across `release-*`, `catalog-testing`, `ui` and `tooling` units already use `@ou/catalog-compile/<file>`; no importer needs a change.
- Imported surface (the contract): `release` (`PublicCatalog`, `parseRelease`, `parseStoredRelease`, `normalizeRelease`, `RELEASE_SCHEMA_VERSION`), `compile` (`compileRelease`), `incremental-compile` (`ReleaseFrame`, `CatalogReleaseIndex`, `CompiledCourseProjection`, `compileReleaseIndex`, `stitchRelease`, `assembleReleaseFromProjections`, `compileSingleCourseProjection`, `scopeCourseTables`).
- Tunables: `config_check.literal_findings` reports none for the four files and no `x-literal-sites` entry names them. The D-063 prose census stays shared with the catalog area and shrinks only through the D-063 catalogs, as in the other U4 units.
- UI text: none.
- Battery: `scripts/unit-battery catalog-compile` green in 3.8 s (types 4 files, unit 1 file) against `battery.unit_time_limit`. Tests are hermetic.
