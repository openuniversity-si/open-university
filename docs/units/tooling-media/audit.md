# tooling-media audit (U4)

Read-only findings, base `mod/roadmap-integration` 4a5471b2.

- Unit: 21 files under `apps/web/scripts/` (9 entry scripts and 12 files under `scripts/lib/` including 5 tests and one test helper), 1,845 lines with tests, 1,159 production lines, under `units.size_ceiling` (1500; production lines only), so no `unit.oversize`.
- Physical form: S1 keeps units logical (P-03 `validated`). The files keep their paths; `@ou/tooling-media/*` is generated into `apps/web/tsconfig.json`. Nothing moves, so there is nothing to delete (D-029). The brief asked for `units/tooling-media/`; `units/<id>/` holds only the manifest.
- Importers (not this unit's files, not edited): `media/server/r2.test.ts` (media-server) imports `@ou/tooling-media/lib/s3-fake.test-helpers.ts`; `test/int/media-content.int.test.ts` and `test/int/media-r2.int.test.ts` (testing-support) import `media-content-migrate.ts` and `media-migrate.ts` by relative path. Other `media-*` hits in the import scan belong to other units (`media-gateway`, `media-owners`, `media-object`). `migrate-dns.ts` appears only inside an architecture-check test fixture string.
- Imported surface (the contract): `lib/s3-fake.test-helpers` (`startFakeS3`), `lib/media-content-migrate` (`backfillContent`, `contentSummary`, `copyContent`, `planContentMigration`, `rollbackContent`, `verifyContent`), `lib/media-migrate` (`applyUrlMap`, `listAllMediaRows`, `planMigration`).
- Literals: `scripts/structure-check` reports zero errors and no `x-literal-sites` entry names the unit, so the allowlist is already zero.
- UI text: none. These are operator scripts; their output is not user-facing site copy.
- Battery: `scripts/unit-battery tooling-media` green in 10.7 s wall (types 9.95 s, unit 5.5 s) against `battery.unit_time_limit` (10 s, applied per step). Tests are hermetic: a fake S3 on loopback, no network.
