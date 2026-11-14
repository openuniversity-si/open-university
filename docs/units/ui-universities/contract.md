# ui-universities contract (1.0.0)

The unit is logical (S1, P-03). Its published surface is the modules below with no single entry file; adding an `index.ts` re-export would be a shim (D-029), so the manifest `contract` slot stays empty and the surface is recorded here. Importers keep `@ou/ui-universities/<path>`.

| Module | Exports other units import |
|---|---|
| `CountrySection/CountrySection.tsx` | `CountrySection` |
| `Universities/UniversitiesShowcase.tsx` | `UniversitiesShowcase`, `UniversityShowcaseGroup` |
| `Universities/UniversityRails.tsx` | `UniversityRails` |
| `Universities/Universities.module.css` | the class names `AreaGrid` and the university views use |

Every other export (`Flag`, `flags.ts`, `CountrySection.module.css`) is internal. A breaking change goes expand->contract (P-07, D-029): add the new form, move callers, remove the old. No consumer file is edited here.

Literals: no tunable (`config_check` clean, no `x-literal-sites` entry). UI text: none owned. Battery: `scripts/unit-battery ui-universities`, limit `battery.unit_time_limit`. Generated outputs: `scripts/generate --check` shows no drift.
