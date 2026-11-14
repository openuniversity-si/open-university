# catalog-hierarchy audit (U4)

Read-only findings, base `mod/roadmap-integration` c9e8f890.

- Unit: 34 listed files plus `config/**` and `generated/**` under `apps/web/src/catalog/domain/`, 1,937 lines in the listed files, under `units.size_ceiling` (1500 applies per unit; the listed files are above `units.size_target` only through their tests, no `unit.oversize` raised, nothing split here). Owner `catalog-lane`.
- Physical form: S1 keeps units logical (P-03 `validated`). The files keep their paths and share `catalog/domain/` with other catalog units, so nothing moves and nothing is deleted (D-029). `units/<id>/` holds only the manifest; `@ou/catalog-hierarchy/*` is generated into `apps/web/tsconfig.json`.
- Importers (consumer units, not edited): 26 files in `release-lane` (11), `catalog-lane` (6), `media-lane` (4), `ui-lane` (2), `factory-lane` (2) and `tooling-lane` (1), all already through `@ou/catalog-hierarchy/<file>`.
- Imported surface (the contract) is in `contract.md`.
- Tunables: `config_check.literal_findings` reports none and no `x-literal-sites` entry names these files. The D-063 absolute census (`absolute-literals-baseline/catalog.json`) lists 207 prose and vocabulary offenders in them; it is shared with the whole catalog area and shrinks only through the D-063 catalogs, as in the other U4 units.
- UI text: none owned here.
- Battery: `scripts/unit-battery catalog-hierarchy` green in 5.0 s (types 35 files, unit 13 files) against `battery.unit_time_limit`. Tests are hermetic: no network.
