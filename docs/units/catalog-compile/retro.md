# catalog-compile retro (U4)

1. **Brief.** It asked to move the unit into `units/catalog-compile/`; S1 (P-03) keeps units logical and the four files share `catalog/domain/` with other units, so nothing moved and no old path needed deleting. Every importer already uses `@ou/catalog-compile`; none changed.
2. **Result.** Deliverables are the audit, the contract document (three modules, no `index.ts` shim, D-029), the manifest `battery.command` and this retro. Zero tunable literals (`config_check` clean); the D-063 prose census is shared with the catalog area and left as is.
3. **Gate.** The first gate-dev failed only in `structure check` because the head was behind the base without a merge commit; merging the base fixed it.
4. **Lessons.** `pkill -f` on a gate name also kills the calling shell; wait on the process instead.
