# site-server contract (1.0.0)

The unit is logical (S1, P-03). Its published surface is four application modules with no single entry file; adding an `index.ts` re-export would be a shim (D-029), so the manifest `contract` slot stays empty and the surface is recorded here. Importers keep `@ou/site-server/application/<file>`.

| Module | Exports other units import |
|---|---|
| `application/site-data.ts` | `siteData`, `LEGAL_EMAIL` |
| `application/indexing.ts` | `siteIndexingFacts` |
| `application/build-info.ts` | `buildInfo` |
| `application/csp-report.ts` | `answerCspReport` |

`ports/`, `server/` and `testing/` are internal: nothing outside the unit imports them. A breaking change goes expand->contract (P-07, D-029): add the new form, move callers, remove the old. No consumer file is edited here.

Literals: none (no `x-literal-sites` entry names the unit). UI text: none. Battery: `scripts/unit-battery site-server`, limit `battery.unit_time_limit`. Generated outputs: `scripts/generate --check` shows no drift.
