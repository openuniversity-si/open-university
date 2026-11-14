# engine-neon audit (U4)

Base: `mod/roadmap-integration` at a2c09043 (LR1 #575, CO1 #576 merged). Evidence is read-only.

## Unit
`units/engine-neon/unit.json`: cell engine, owner engine-lane, six paths (`scripts/lib/{migration_order,neon_migrate,neon_pr}.py`, `scripts/{neon-migrate,neon-pr}`, `scripts/tests/test_neon_migrate.py`), 1,011 lines in all, well under `units.size_ceiling`, so no `unit.oversize`.

## Physical form
`docs/architecture/UNITS.md`: S1 kept units logical. `scripts/lib/unit_addresses.py` only gives an address to a unit whose home sits inside the TypeScript project; `scripts/units addresses` prints `engine-neon  -  -  0  False`. There is no address form for Python or shell, so the files stay in place (brief: "keep the files in place and deliver the rest"). The executables `scripts/neon-migrate` and `scripts/neon-pr` are public entry points and keep their paths in any case. Nothing imports `@ou/engine-neon`.

## Contract
Importers of the unit's modules (by `rg`): `scripts/merge-phase` (calls `migration_order.py merge-ready`, `neon-pr delete`), `scripts/tests/test_invoker_tooling.py` (imports `neon_migrate`, `neon_pr`), shell tests with stubs. The published surface is therefore the two executables plus `migration_order.merge-ready` and the module functions `neon_pr.{eligibility,hook_plan,hooks,branch_env,Neon}` and `neon_migrate.main`.
A manifest `contract` slot needs `unit_addresses.addresses()[unit]`: `unit_battery.plan` adds a `contract` step that errors ("the contract entry ... is not a file of the unit") when the unit has no address. Filling the slot for a Python unit would turn its battery red. That mechanism belongs to engine-units (`scripts/lib/unit_battery.py`, `unit_addresses.py`), not to this PR.

## Literals
Tunables spelled inline: `neon_migrate.py` (pnpm timeout 180 twice, log tail 30 lines, `TARGETS`/`VARIABLES` names, database and role names), `neon_pr.py` (HTTP timeouts 30/10/45, branch age 86400 s, branch limits 3 and 10, compute 0.25 CU, suspend 300 s, health attempts 80 and poll 0.1 s, build restore 600 s, redacted run 90 s, hook timeout 600 s per mode, pipe read 16384, subprocess 30 s). No x-literal-sites entry exists for these files, so the shrink-only allowlist is already empty for them. The goal is to register the values anyway (D-063/D-068).

## Battery and tests
`scripts/unit-battery engine-neon --json` is `ok` with `steps: []`: the battery's steps cover TypeScript tests and `scripts/tests/*.test.sh` only, and `test_neon_migrate.py` is run by `cloud-tail.test.sh` (engine-test-support), so the unit's own tests are in no battery step. `test_neon_migrate.py` runs 16 tests in 0.009 s, offline. `neon_pr` and `migration_order` internals are tested by other units' files.

## Lessons / defects
`scripts/lessons for-area scripts/lib/neon_migrate.py`: none applied.

## Decisions taken
- Keep files in place; record the address-form gap.
- Do not fill `contract` (would break the battery); record it as a follow-up for engine-units.
- Register the literals in `config/registry/neon.json`, add `scripts/tests/neon.test.sh` so the battery runs the unit's Python tests.
