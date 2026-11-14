# release-domain retro (U4)

1. **Brief.** It asked to move the unit into `units/release-domain/`; S1 (P-03) keeps units logical, so nothing moved and no old path needed deleting. Importers already use `@ou/release-domain`.
2. **Result.** Audit, contract document (15 modules, no `index.ts` shim, D-029), the manifest `battery.command`, and a fix for a stale import assertion in `countries.test.ts` that kept the battery red. Zero tunable literals (`config_check` clean).
3. **Gate.** gate-dev passed on the merged head (510 s on this 4 vCPU cloud, above the 180 s ceiling, which only warns); battery 5.7 s.
4. **Lessons.** A unit test that greps a consumer file for an import path breaks silently when importers migrate to `@ou/*`; the contract table was computed from single-line imports.
