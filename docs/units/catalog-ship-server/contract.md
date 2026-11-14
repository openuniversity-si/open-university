# catalog-ship-server contract (1.0.0)

The unit is logical (S1, P-03). Entry: `apps/web/src/catalog/server/ship-batch.ts`, address `@ou/catalog-ship-server` (the existing `@ou/catalog-ship-server/<file>` wildcard still resolves each file). The manifest `contract` slot is filled with entry `ship-batch.ts`, version `1.0.0` (contracts/units/unit.v1.json). It re-exports only what other units import today (plus its own `shipBatch`):

| Export | Source | Importer |
|---|---|---|
| `applyBatch` | `batch-apply.ts` | `catalog/application/admin-handlers.ts` (relative path) |
| `writeCourses`, `writeMedia`, `writeRefs` | `batch-apply.ts` | `catalog/testing/bench.ts` (relative path) |
| `applyBundle`, `diffBundle`, `exportBundle`, `validateBundle` | `bundles.ts` | `admin-handlers.ts` |
| `deleteCourse`, `deleteEdition`, `deleteLesson`, `mediaReferences` | `deletion.ts` | `admin-handlers.ts` |
| `createImport`, `draftImport`, type `ImportReport` | `imports.ts` | `admin-handlers.ts` |
| `shipBatch` | `ship-batch.ts` | `admin-handlers.ts` |

Not published: `bundle-apply.ts` (reached through `bundles.ts`), `loadBatchRefs`, `writeBatchRows`, `publishAppliedBatch`, `drainPendingObjects`, `itemExclusion`, `itemWarnings`. A consumer that needs one adds it in an expand step first. A breaking change goes expand->contract (P-07, D-029). No consumer file is edited here; moving the two consumers to the address is their own units' work.

Literals: none (the no-literals check finds zero; the slug race tunables are `tests.author_race_rounds` and `tests.author_race_lead_ms`). Battery: `scripts/unit-battery catalog-ship-server`, limit `battery.unit_time_limit`. Generated outputs (`tsconfig` aliases, CODEOWNERS, the tests registry types) come from `scripts/generate`.

Why `ship-batch.ts` and not a new `contract.ts`: the catalog context budget (`L3.context-size`, D-060) is shrink-only and sits exactly at the context's size (84 files, 8631 lines), so a new production file fails it and raising it needs a decision. The entry therefore lives in an existing file and the change is line-neutral (the four export lines are offset by merged imports and removed duplicate comment lines). A follow-up decision that excludes contract entries from the budget would let each catalog unit carry a plain `contract.ts`; that is the architecture-rules owner's call, not made here.
