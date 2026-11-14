# factory-domain contract (1.0.0)

The unit is logical (S1, P-03): its files stay in `apps/web/src/factory/domain/**`. The manifest contract entry is `index.ts`, which exports only what other units import today (computed from the import graph):

| Export | Imported by |
|---|---|
| `parseCurated`, `CuratedV1` | `factory/server/youtube-adapter.ts`, `factory/testing/adapter-contract.ts`, `factory/ports/source-adapter.ts` |
| `youtubeDurationSeconds` | `factory/server/youtube-adapter.ts` |

Importers keep their `@ou/factory-domain/<file>` subpaths and are not edited; the bare `@ou/factory-domain` alias is generated into `apps/web/tsconfig.json` by `scripts/generate addresses`. A breaking change goes expand->contract (P-07, D-029): add the new form, move callers, remove the old.

Literals: none (the no-literals check finds zero; no `x-literal-sites` entry names the unit). Battery: `scripts/unit-battery factory-domain`, limit `battery.unit_time_limit`. Size: 764 production lines, under `units.size_ceiling` (not oversize). Generated outputs: `scripts/generate --check` shows no drift.
