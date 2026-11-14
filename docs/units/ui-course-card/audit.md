# U4 ui-course-card audit (read-only; cheap evidence only)

Brief: migrate unit `ui-course-card` (plan v3 §9.2 row U4, v3.1 §3): physical form, explicit versioned contract, zero literals, battery, generated outputs, UI text in `text.*`. Base `mod/roadmap-integration` @ 76cc5f2d.

| Area | Evidence | Consequence |
|---|---|---|
| Physical form | S1 (P-03): units stay logical, "U4 moves nothing physically"; `app-home` (#603) migrated that way. | No file moves, no old path to delete, no shim (D-029). `@ou/ui-course-card/*` already maps to `./src/ui/*`. |
| Size | `scripts/units measure`: 1013 production lines, ceiling `units.size_ceiling` 1500. | Not oversize; no `unit.oversize`. |
| Importers | `rg "@ou/ui-course-card"`: `app-*`, `ui-billboard`, `ui-lesson-row`, `showcase`, `Universities` import 14 names (see contract.ts) plus `EditionSelector.module.css`. `CoverPlayButton` and the internals (`nextTab`, `urlWithEdition`, `EDITION_PARAM`, ...) have no outside importer. | The surface is exactly those names; the CSS module is not re-exportable and stays an address-path import. |
| Literals | No `x-literal-sites` entry names a file of the unit; copy of `EmptyCatalog` is already in `text.*`. | Allowlist already zero; nothing to shrink. |
| UI text | The L1 lexical check over the unit's `.tsx` finds no visible string once they join `l10n.scoped_files`. | No text moves; the files join the scope so the gate keeps them at zero. |
| Battery | `scripts/unit-battery ui-course-card` green (~5 s), limit `battery.unit_time_limit`. | Gains a `contract` step through the manifest entry. |
