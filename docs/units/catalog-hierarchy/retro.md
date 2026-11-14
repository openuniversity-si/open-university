# catalog-hierarchy retro (U4)

1. **Brief.** It asked to move the unit into `units/catalog-hierarchy/`; S1 (P-03) keeps units logical and the files share `catalog/domain/` with other units, so nothing moved and no old path needed deleting. Importers already use `@ou/catalog-hierarchy`.
2. **Result.** Audit, contract document (eleven modules, no `index.ts` shim, D-029), the manifest `battery.command` and this retro. Zero tunable literals (`config_check` clean); the D-063 census (207 offenders in the unit's files) is shared with the catalog area and left as is, like the other U4 units.
3. **Gate.** gate-dev green on the first run after merging the updated base (114 s, ceiling 180 s); battery 5.0 s.
4. **Lessons.** The contract list was computed from single-line imports; multi-line imports may add names, so the first consumer PR that finds one should extend the table by expand->contract.
