# fidelity-references contract (1.0.0)

The unit is logical (S1, P-03). Its published surface is spread over five modules with no single entry file; adding an `index.ts` re-export would be a shim (D-029), so the manifest `contract` slot stays empty and the surface is recorded here. Importers keep their paths; `@ou/fidelity-references/<file>.ts` resolves to the same files.

| Module | Exports other units import |
|---|---|
| `active.ts` | `DEFAULT_CACHE_DIRECTORY`, `materializeActiveSet`, `writeLocalSet`, `readLocalSet`, type `LocalReferenceSet` |
| `connect.ts` | `connectTooling`, `requiredEnv`, `safeErrorMessage`, `toolingSessions` |
| `figma.ts` | `DESIRED_SPEC_FILE_KEY`, `createFigmaClient` |
| `storage.ts` | `referenceStorageFromEnv`, `R2_FIDELITY_BUCKET_DEFAULT`, `sha256`, `createR2Storage` |
| `sync.ts` | `syncFidelityReferences` |

Nothing outside this list is imported today. A breaking change goes expand->contract (P-07, D-029): add the new form, move callers, remove the old. No consumer file is edited here.

Literals: none (the no-literals check finds zero; no `x-literal-sites` entry names the unit). Battery: `scripts/unit-battery fidelity-references`, limit `battery.unit_time_limit`. Generated outputs: `scripts/generate --check` shows no drift for this unit.
