# engine-env retro (U4)

## 1. Brief quality
The brief asks for a physical move, an `@ou` address and a manifest contract for every unit. For a Python unit none of the three exists: S1 kept units logical and `unit_battery` resolves `contract.entry` through a TypeScript address. The brief did say "if U3a defines no address form, keep the files in place", which settled it. Missing: where the contract goes meanwhile (engine-wrappers' sibling PR chose `contract.md`; followed).

## 2. Audit and plan
P-03 held (files stay). P-05 held with six registry entries. The unplanned finding was the battery: red at 42.3 s against the 10 s limit before any change, so the unit could not meet "green within the limit" without a fix. The plan gained commit 3, and later a contract-document commit (5).

## 3. Execution
Root cause class: a function that calls `config.get` once per item. Each call replays the config store (about 50 ms), so `checksum_key` inside the `load` loop made 47 calls (2.5 s per load) and tests loaded per tool. Fixed in this unit: one read per load, `artifact(name, data)`. Result 42.3 s -> 6.6 s. The same pattern may exist in other units; the cure belongs in `config.get` (engine-config). No dead ends. Commits: audit, plan, battery, literals, merge of the base, contract, retro.

## 4. Gate
One run on 874a2ba2 + base merge: PASSED in 360 s on 4 vCPU (script tests 250 s, structure check 48 s); the ceiling warning (180 s) is the base's, not this PR's. `generate.test.sh` reports a node `ERR_MODULE_NOT_FOUND` for `apps/web/scripts/intents-doc.ts` (no `node_modules` in this cloud checkout); the gate classified the run as passed, and the failure is independent of these files (known environment defect, owner engine-generate).

## 5. Lessons
- engine-config: `config.get` should cache the store replay per process (it is the reason several unit batteries risk the 10 s limit). Owner engine-config.
- Brief template: say how to record a contract for a unit with no address form. Owner coordinator (CO1).
- Gate check: flag a unit battery above 70% of `battery.unit_time_limit` before it goes red. Owner engine-battery.
