# media-server audit (U4)

Read-only findings, base `mod/roadmap-integration` 0c87de1f.

- Unit: `apps/web/src/media/server/**`, 29 files (11 test files), far under `units.size_ceiling` (no `unit.oversize`).
- Physical form: S1 keeps units logical (P-03); the files stay at `apps/web/src/media/server` and `@ou/media-server/<file>` resolves there through the generated `tsconfig` `paths`. Nothing moves, so no importer changes and no alias is edited by hand.
- Importers of `@ou/media-server/*` (computed from the import graph): `deps.ts`, `fs-store.ts`, `index.ts`, `invalidate.ts`, `objects.ts`, `prepare.ts` (2), `public-hosts.ts` (2), `revalidate.ts`, `storage.ts` (2). One relative import remains in a catalog test (`catalog/server/ship-batch.int.test.ts` -> `media/server/public-hosts.ts`); it belongs to the catalog unit and is not edited here.
- Literals: `config_check.literal_findings` reports none for these files; no `x-literal-sites` entry names the unit. The allowlist for the unit is already zero.
- Battery: `scripts/unit-battery media-server` is green in about 9 s against `battery.unit_time_limit` (10 s).
- Hermeticity: `tests.unhermetic_sites` lists `media/server/admin.test.ts:random` (unseeded `randomBytes` for an incompressible PNG). Fixed by the seeded source from `@ou/testing-support/hermetic.ts`; the entry is removed (the list only shrinks).
