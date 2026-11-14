# ui-universities retro (U4)

1. **Brief.** It asked to move the unit into `units/ui-universities/`; S1 (P-03) keeps units logical, so nothing moved and no old path needed deleting. Importers already use `@ou/ui-universities`.
2. **Result.** Audit, contract document (3 modules plus the stylesheet, no `index.ts` shim, D-029) and the manifest `battery.command`. Zero tunable literals (`config_check` clean) and no owned UI text: all sentences already come from `@ou/site-domain` and `@ou/ui-showcase`. The unit is far below `units.size_ceiling`.
3. **Gate.** The battery passes in about 5.5 s; the gate-dev stage table is in the PR comment.
4. **Lessons.** Units whose literals and text were already externalised by earlier U3b work need only documents and a battery command; check the import graph first to avoid empty churn.
