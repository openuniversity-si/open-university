# catalog-release-server contract (1.0.0)

The unit is logical (S1, P-03). Its published surface is seven modules with no single entry file; adding an `index.ts` re-export would be a shim (D-029), so the manifest `contract` slot stays empty and the surface is recorded here. Importers keep `@ou/catalog-release-server/<file>`; inside `catalog/server/` the sibling units still import by relative path, which resolves to the same files.

| Module | Exports other units import |
|---|---|
| `releases.ts` | `publishRelease`, `scheduleActivation`, `Publication`, `ReleaseSummary` |
| `doctor.ts` | `runDoctor`, `Finding` |
| `home.ts` | `getHome`, `putHome` |
| `redirects.ts` | `createRedirect`, `deleteRedirect`, `listRedirects` |
| `release-routes.ts` | `activateRelease`, `createRelease`, `getRelease`, `listReleases` |
| `list-projection.ts` | `projectCoursePage` |
| `invalidate.ts` | `invalidateCatalog` |

Every other export of these files is internal. A breaking change goes expand->contract (P-07, D-029): add the new form, move callers, remove the old. No consumer file is edited here.

Literals: no tunable (`config_check` clean, no `x-literal-sites` entry); the D-063 prose census for the files is unchanged. UI text: none. Battery: `scripts/unit-battery catalog-release-server`, limit `battery.unit_time_limit`. Generated outputs: `scripts/generate --check` shows no drift.
