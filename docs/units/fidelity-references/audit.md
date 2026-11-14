# fidelity-references audit (U4)

Read-only findings, base `mod/roadmap-integration` bb8fb9b4.

- Unit: 8 files under `apps/web/fidelity/references/` (`active`, `connect`, `figma`, `storage`, `sync`, a test helper, one unit test, one integration test), 926 lines, far under `units.size_ceiling` (no `unit.oversize`).
- Physical form: S1 keeps units logical (P-03 `validated`, `measurement:S1`). The files keep their paths; the address `@ou/fidelity-references` is generated into `apps/web/tsconfig.json` and maps to `./fidelity/references/*`. Nothing moves, so there is nothing to delete (D-029).
- Importers (not this unit's files, not edited): `fidelity/{references-fetch,media-fetch,media,resolve,run}.ts`, `scripts/{fidelity-sync,fidelity-migrate-r2,tooling-migrate}.ts`, `e2e/fidelity.spec.ts`, `src/media/server/r2.test.ts`; most still use relative paths, `resolve.test.ts` uses the address. Both resolve to the same files.
- Imported surface (the contract): `active` (`DEFAULT_CACHE_DIRECTORY`, `materializeActiveSet`, `writeLocalSet`, `readLocalSet`, `LocalReferenceSet`), `connect` (`connectTooling`, `requiredEnv`, `safeErrorMessage`, `toolingSessions`), `figma` (`DESIRED_SPEC_FILE_KEY`, `createFigmaClient`), `storage` (`referenceStorageFromEnv`, `R2_FIDELITY_BUCKET_DEFAULT`, `sha256`, `createR2Storage`), `sync` (`syncFidelityReferences`).
- Literals: `config_check.literal_findings` reports none for these files and no `x-literal-sites` entry names them; the allowlist for the unit is already zero.
- Battery: `scripts/unit-battery fidelity-references` green in 6.0 s (types 8 files, unit 1 file, integration 1 file) against `battery.unit_time_limit`. Tests are hermetic: fixtures in temp directories, no network.
