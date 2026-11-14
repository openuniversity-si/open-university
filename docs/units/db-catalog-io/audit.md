# db-catalog-io audit (U4)

Read-only findings, base `mod/roadmap-integration` 30e51c3c.

- Unit: `projections.ts` (232 lines), `queries.ts` (71), `table-io.ts` (1114), `queries.int.test.ts` (100), 1,517 lines, under `units.size_ceiling` (no `unit.oversize`).
- Physical form: S1 keeps units logical (P-03). The files keep their paths; `@ou/db-catalog-io/*` is generated into `apps/web/tsconfig.json` and maps to `./src/platform/db/catalog/*`, a home shared with `db-catalog-store`. Nothing moves, so there is nothing to delete (D-029).
- Importers: only `db-catalog-store` (`index.ts`, `store.ts`, `release-load.ts`, `projections.perf.int.test.ts`) imports these modules, and it republishes them through its `index.ts`. No file outside the two units is edited.
- Imported surface: every export of the three production modules (17 + 1 + 172). See `contract.md`.
- Literals: `config_check.literal_findings` reports none; no `x-literal-sites` entry names the unit. The allowlist for it is already zero.
- Battery: red at 12.0 to 14.2 s against `battery.unit_time_limit` (10 s). Cause: `queries.int.test.ts` imported `test/fixtures/admin-catalog.ts` for `NOW` and `testDatabaseUrl`, and that fixture imports the admin harness, so tsc followed 1206 files (production files alone: 698 files, 4.6 s). Fixed in the unit's own test (reads `TEST_DATABASE_URL`, validates it with `validateDatabaseUrl`, one local timestamp constant): green in 7.8 s. No threshold changed.
- Tests are hermetic: the integration test uses the local PostgreSQL test database, no network.
