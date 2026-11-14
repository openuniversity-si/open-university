# db-catalog-io contract (1.0.0)

The unit is logical (S1, P-03). Its modules are republished by the `db-catalog-store` entry (`index.ts`, another unit's file), so the manifest `contract` slot stays empty: an entry file here would be a shim (D-029). Importers keep their paths; `@ou/db-catalog-io/<file>.ts` resolves to the same files.

Every export of the three production modules is imported today, so the contract is their whole export list.

| Module | Exports other units import |
|---|---|
| `projections.ts` | `authorIdsOfProjections`, `findActiveReleaseNumber`, `findActiveReleasePayload`, `readActivePayloadSha`, `readActiveReleaseNumber`, `readActiveReleasePayload`, `readCourseRevisions`, `readProjectedRelease`, `readProjections`, `readRedirects`, `readReleaseIndex`, `readReleasePayloadBySha`, `selectCoursePage`, `writeProjection`, `writeProjections`, `writeRedirects`, `writeReleaseIndex` |
| `queries.ts` | `createCatalogQueries` |
| `table-io.ts` | 171 functions plus type `CatalogScope`, listed in the `table-io.ts` re-export block of `index.ts`; families by verb: approve (1), archive (1), assign (1), bump (1), clear (2), commit (1), count (13), course (2), delete (17), insert (15), lock (5), mark (1), open (4), publish (3), read (3), release (1), restore (2), retarget (2), revoke (1), rollback (2), save (1), select (69), set (4), shift (2), subject (1), update (7), upsert (8), write (1) |

A breaking change goes expand->contract (P-07, D-029): add the new form, move callers, remove the old. No consumer file is edited here.

Literals: none (the no-literals check finds zero). Battery: `scripts/unit-battery db-catalog-io`, limit `battery.unit_time_limit`. Generated outputs: `scripts/generate --check` shows no drift. Only this unit speaks SQL for the projection tables (P-06); no migration is added or run.
