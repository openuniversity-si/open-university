# U4 engine-delivery: retro (D-067, D-069)

## 1. Brief
Missing: the definition of done assumes a physical move and a contract entry; for a Python/shell unit neither is possible
(no `@ou` address, S1/U3a; a `contract` slot is a red battery step without an address). Resolved as the sibling
`engine-architecture-check` did: files stay, contract slot empty, recorded in audit.md. The brief did not say the battery's
steps run a unit's script tests one after another, which made the 10 s limit the real work of this unit.

## 2. Audit and plan
Held: P-03 (logical form), P-04 (1,326 lines, no oversize), P-05, P-07 (no exported surface changed). Plan changed once:
the registry file moved from commit 3 to commit 2 (the test needs two entries), and commit 4 grew a release_policy CLI
after `scripts/config get` proved to cost 0.23 s per call.

## 3. Execution
- Battery was 24 s (merge-phase.test.sh, 45 serial processes). Cases now run side by side with their own fake; fixtures built once.
- Class "config read in a hot path": `config.get` reloads the registry (19 ms). Wiring the tail through it made delivery_test 1 s -> 7 s and battery 16 s. Fixed by a per-process `delivery.setting` cache and a cheap `release_policy.py` CLI for merge-phase, so every reader uses one of two mechanisms.
- Class "unhermetic fixture": the git stub answered env.sh's hooksPath query from the fixture, so every run reinstalled push-guard hooks in the real checkout (0.2 s each). Fixture sets core.hooksPath.
- Commit 3 was green by tests but over the battery limit (16 s); commit 4 restored it. Dead end: setting OU_SUBJECT_ROOT saved little (manifest load is not the dominant cost).
Timeline: audit/plan ~06:45, test rewrite 06:55, literals 07:00, cache and merge-phase 07:12, manifest 07:17, gate 07:18-07:24.

## 4. Gate
One run on the merged head ebde2e73: PASSED in 318 s (script tests 228 s, structure check 35 s; ceiling 180 s exceeded, not this unit's cost). `generate.test.sh` reported FAIL inside script tests (node ERR_MODULE_NOT_FOUND from apps/web/scripts/intents-doc.ts: no node_modules in this sandbox, same error from `scripts/generate all` before my changes); the gate verdict was PASSED. Known base defects: `invoker-tooling.test.sh` and `gate-db.test.sh` fail on base (`gate_select` missing from their copied file lists; after that fix they will also need `config/registry`, because delivery.py now reads settings).

## 5. Lessons
- Brief template: for non-TypeScript units state the S1 form and that `contract` stays empty (owner: coordinator/U3a).
- `config.get` per-call cost and `scripts/config get` 0.23 s: cache or index the registry (owner: engine-config, C0).
- `units.manifests()` 0.42 s per process (owner: engine-units).
- `unit_battery` script-tests step is serial; running files concurrently would remove this class (owner: engine-battery).
- gate-script-tests.json `covers` lacks config/registry/*.json for tests that read it (owner: engine-gate-plan).
- Test fixtures copying lib files must use a shared list (owner: engine-test-support).
