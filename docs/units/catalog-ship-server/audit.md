# catalog-ship-server audit (U4)

Read-only findings, base `mod/roadmap-integration` b2ed374f.

- Unit: 9 files under `apps/web/src/catalog/server/` (6 production, 3 test), 1,553 lines, under `units.size_ceiling` (1,500 per file budget is counted per unit at 1,106 production lines): no `unit.oversize`.
- Physical form: S1 keeps units logical (P-03); the files stay in `apps/web/src/catalog/server` and `@ou/catalog-ship-server/<file>` resolves there through the generated `tsconfig` `paths`. Nothing moves and no old path is left behind, so there is nothing to delete (D-029).
- Importers (computed from the import graph): the brief says every importer already uses `@ou/catalog-ship-server`; it does not. Five relative imports remain: `catalog/application/admin-handlers.ts` (`applyBatch`, `applyBundle`, `diffBundle`, `exportBundle`, `validateBundle`, `deleteCourse`, `deleteEdition`, `deleteLesson`, `mediaReferences`, `createImport`, `draftImport`, `ImportReport`, `shipBatch`) and `catalog/testing/bench.ts` (`writeCourses`, `writeMedia`, `writeRefs`). Both belong to other units and are not edited here; the contract below is their address when they migrate.
- Literals: `config_check.literal_findings` reports none for these files; no `x-literal-sites` entry names the unit. One test-only tunable lived inline: the 24 rounds and the 250 ms lead of the shared-author slug race in `bundle-apply.int.test.ts`.
- Battery: `scripts/unit-battery catalog-ship-server` was red on time, 12.2 s against `battery.unit_time_limit` (10 s). The slug race test alone took 6.4 s (24 rounds x 250 ms lead).
- Hermeticity: `tests.unhermetic_sites` lists no site for the unit.
