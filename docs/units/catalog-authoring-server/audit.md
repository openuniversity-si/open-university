# catalog-authoring-server audit (U4)

Read-only findings, base `mod/roadmap-integration` fbca2e52.

- Unit: eight files under `apps/web/src/catalog/server/` (`authors`, `common`, `courses`, `editions`, `lesson-slugs`, `lessons`, `reference`, `texts`), 1402 lines, under `units.size_ceiling` (1500): no `unit.oversize`.
- Physical form: S1 keeps units logical (P-03). `@ou/catalog-authoring-server/*` maps to `src/catalog/server/*`, a directory shared with the release and ship server units, so nothing moves and nothing is deleted (D-029). `units/<id>/` holds only the manifest.
- Importers (not this unit's files, not edited): the brief says every importer already uses the address; it does not. All importers use relative paths: `catalog/application/admin-handlers.ts` (catalog-application), `catalog-ship-server` (`deletion`, `imports`, `bundle-apply`, `ship-batch`, `batch-apply`), `catalog-release-server` (`doctor`), `test/fixtures/admin-catalog.ts` and four `test/int/*` files. They are other units' files; rewriting them is their units' slice.
- Imported surface: 60 names, listed in `contract.md`; no entry file (see there). `changed`, `editionRow`, `assertCourseEdition`, `textSummary` stay private.
- Literals: `config_check` has no `x-literal-sites` entry for the unit, so that allowlist is already zero. The D-063 absolute census (`scripts/lib/absolute-literals-baseline/catalog.json`) still lists 423 offenders in the eight files (SQL table and column names, status words, error prose, audit action names, small counts).
- Battery: `scripts/unit-battery catalog-authoring-server` green in 7.3 s against `battery.unit_time_limit` (10 s); the unit owns one test file.
- Hermeticity: unit tests use no network; integration coverage of these modules lives in `test/int/` with the local test database.
