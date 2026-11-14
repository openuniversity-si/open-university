# media-server contract (1.0.0)

The unit is logical (S1, P-03); `@ou/media-server/<file>` resolves to `apps/web/src/media/server/<file>` through the generated `paths`. The manifest `contract` slot is filled with entry `index.ts`, version `1.0.0` (contracts/units/unit.v1.json).

Published surface, computed from the import graph (only these files are imported through `@ou/media-server` today; every other file is internal):

| File | Imported by |
|---|---|
| `index.ts` | one consumer |
| `deps.ts` | one consumer |
| `fs-store.ts` | one consumer |
| `invalidate.ts` | one consumer |
| `objects.ts` | one consumer |
| `prepare.ts` | two consumers |
| `public-hosts.ts` | two consumers |
| `revalidate.ts` | one consumer |
| `storage.ts` | two consumers |

Not published: `inheritance.ts`, `institution-cover.ts`, `og.ts`, `owner-list.ts`, `r2*.ts`. A consumer that needs one adds an address in an expand step first. A breaking change goes expand->contract (P-07, D-029): add the new form, move callers, remove the old. No consumer file is edited here.

Literals: none (the no-literals check finds zero; no `x-literal-sites` entry names the unit). Battery: `scripts/unit-battery media-server`, limit `battery.unit_time_limit`. Generated outputs: `scripts/generate` shows no drift for this unit (checked below in the retro).
