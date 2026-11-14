# U4 tooling-literals: audit and plan

Premises: P-03 (high: units stay logical, S1; if wrong the move is a later mechanical PR), P-04, P-05 (see Literals), P-07 (the contract is new,
so nothing breaks).

- **Physical form.** S1 answered P-03: logical units, the address `@ou/tooling-literals` -> `apps/web/scripts/*` is the seam. No file moves; the
  manifest paths stay valid and no old path is left behind (D-029).
- **Consumers.** `scripts/lib/architecture/tree.mjs` (`engine-architecture-check`) imports `CENSUS_FILES`; the four rule tests
  `domain-literals.{kernel,site,ui}.test.ts` and `absolute-literals.heavy.test.ts` import the domain readers and the census. They have no unit owner in
  U0's manifests, so they are not edited here; their imports define the surface. `pnpm literals:census` runs `literals-census.ts` directly (an
  executable, not contract).
- **Contract.** `lib/literals-contract.ts`, version 1.0.0, exports exactly those 29 names; `lib/literals-contract.test.ts` fails when one is added or
  removed.
- **Battery.** `scripts/unit-battery tooling-literals`: contract, types and unit tests green in 4.5 s of `battery.unit_time_limit`.
- **Literals (not delivered here).** `scripts/lib/absolute-literals-baseline/scripts.json` lists 223 occurrences in this unit's files
  (domain-literals.ts 116, absolute-literals.ts 80, literal-catalogs.ts 27): the bare `0`/`1`/`true`/`false`, the detector's own regexes and the
  catalog key words. They are the census's own vocabulary, and no TypeScript reader of the config registry exists (`config.get` is Python), so
  zeroing them would invent a second reader (D-069 item 1). The list only shrinks (D-063 ratchet); this PR adds no literal. Owner of the follow-up:
  tooling-lane with the TypeScript config reader of the CW/L1 line.
- **Size.** 1,218 production lines (`scripts/units measure`), below `units.size_ceiling` (1500): not oversize.

D-069 items: 5 (addresses and CODEOWNERS generated), 8 (ownership by manifest), 14 (battery 4.5 s, limit untouched), 3 (no literal added; remaining count recorded).
