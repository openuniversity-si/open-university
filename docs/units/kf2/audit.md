# KF2 audit

Evidence (read-only, base 76cc5f2d):

1. `apps/web/src/release/domain/countries.test.ts:123` asserts `from "@/catalog/domain/config"`; `CountrySection.tsx` imports `OTHER_COUNTRIES_TITLE` from `@ou/catalog-hierarchy/config`. Only occurrence of a hard-coded `toContain('from "@/…')` import assertion in `*.test.ts(x)` (grep over apps/web/src).
2. `node apps/web/scripts/intents-doc.ts` fails with `ERR_MODULE_NOT_FOUND @ou/kernel-tables` (imported by `src/progress/domain/intents.ts`). Node has no resolver for the `@ou/` keys that only tsc, Next and vitest read. `scripts/generate_intents.py` runs it as plain `node <script>`.
3. The single source of the addresses: `apps/web/tsconfig.json` `compilerOptions.paths` (`@ou/` keys, generated from unit manifests), scope `units.address_scope` in `config/registry/units.json`. vitest already derives aliases from it (`vitest.config.ts:27-45`).

Class: any consumer of an address needs the tsconfig paths, not a copy. Fix: one shared Node module `apps/web/scripts/lib/ou-addresses.mjs` (tsconfig paths reader + resolve hook) used by the Node-run generator and the test.
