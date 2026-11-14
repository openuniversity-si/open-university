# catalog-release-server retro (U4)

1. **Brief.** It asked to move the unit into `units/catalog-release-server/`; S1 (P-03) keeps units logical, and the seven files share `catalog/server/` with five other units, so nothing moved and no old path needed deleting. It said every importer already uses `@ou/catalog-release-server`; only one does, the others import by relative path from sibling units, which are consumer files this PR does not edit.
2. **Result.** Deliverables are the audit, the contract document (seven modules, no `index.ts` shim, D-029), the manifest `battery.command` and this retro. Zero tunable literals (`config_check` clean); the D-063 prose census (232 offenders in the unit's files) is shared with the catalog area and left as is, the same call the other U4 units made.
3. **Gate.** The first gate-dev failed in `structure check` on github baseline lines that came from a stale base, not from this change; merging the updated base cleared it.
4. **Lessons.** The `intents` on-demand generator target fails on this machine with `ERR_MODULE_NOT_FOUND`; the committed targets show no drift.
