# tooling-media contract (1.0.0)

The unit is logical (S1, P-03). Its published surface is three modules with no single entry file; adding an `index.ts` re-export would be a shim (D-029), so the manifest `contract` slot stays empty and the surface is recorded here. `@ou/tooling-media/<file>.ts` resolves to the same files.

| Module | Exports other units import |
|---|---|
| `lib/media-content-migrate.ts` | `backfillContent`, `contentSummary`, `copyContent`, `planContentMigration`, `rollbackContent`, `verifyContent` |
| `lib/media-migrate.ts` | `applyUrlMap`, `listAllMediaRows`, `planMigration` |
| `lib/s3-fake.test-helpers.ts` | `startFakeS3` |

Nothing outside this list is imported today. The entry scripts (`media-*.ts`, `fidelity-migrate-r2.ts`) are run from the command line, never imported. A breaking change goes expand->contract (P-07, D-029): add the new form, move callers, remove the old. No consumer file is edited here.

Literals: none (the no-literals check finds zero; no `x-literal-sites` entry names the unit). UI text: none. Battery: `scripts/unit-battery tooling-media`, limit `battery.unit_time_limit`. Generated outputs: `scripts/generate --check` shows no drift for this unit.
