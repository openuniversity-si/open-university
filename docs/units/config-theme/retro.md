# config-theme retro (U4)

1. **Brief.** It asked to move the unit into `units/config-theme/`; S1 (P-03) keeps units logical, and the generator, its test and the D-063 catalog entry name the current paths, so nothing moved and no old path needed deleting. Importers already use `@ou/config-theme`.
2. **Result.** Audit, contract document (`values.ts`, `names.ts`, no `index.ts` shim, D-029), the manifest `battery.command` and this retro. Zero tunable literals: the files are generated D-063 catalogs and the allowlist for them is already zero.
3. **Gate.** gate-dev green on the first run (129 s, ceiling 180 s); battery 2.0 s.
4. **Lessons.** The unit has no tests of its own; the generator test lives in `tooling-entrypoints`. A battery with tests here would only duplicate it.
