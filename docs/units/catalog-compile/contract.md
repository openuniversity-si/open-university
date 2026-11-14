# catalog-compile contract (1.0.0)

The unit is logical (S1, P-03). Its published surface is three modules with no single entry file; adding an `index.ts` re-export would be a shim (D-029), so the manifest `contract` slot stays empty and the surface is recorded here. Importers keep `@ou/catalog-compile/<file>`.

| Module | Exports other units import |
|---|---|
| `release.ts` | `PublicCatalog`, `parseRelease`, `parseStoredRelease`, `normalizeRelease`, `RELEASE_SCHEMA_VERSION` |
| `compile.ts` | `compileRelease` |
| `incremental-compile.ts` | `ReleaseFrame`, `CatalogReleaseIndex`, `CompiledCourseProjection`, `compileReleaseIndex`, `stitchRelease`, `assembleReleaseFromProjections`, `compileSingleCourseProjection`, `scopeCourseTables` |

Every other export of these files is internal. A breaking change goes expand->contract (P-07, D-029): add the new form, move callers, remove the old. No consumer file is edited here.

Literals: no tunable (`config_check` clean, no `x-literal-sites` entry). UI text: none. Battery: `scripts/unit-battery catalog-compile`, limit `battery.unit_time_limit`. Generated outputs: `scripts/generate --check` shows no drift.
