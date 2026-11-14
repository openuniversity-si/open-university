# U4 engine-delivery: plan (D-067, D-069)

## Commits and the graph

| # | Commit | Owns | Depends on |
|---|---|---|---|
| 1 | audit.md, plan.md | docs/units/engine-delivery/{audit,plan}.md | none |
| 2 | merge-phase.test.sh runs its cases concurrently, each with its own fake server and directory | scripts/tests/merge-phase.test.sh | 1 |
| 3 | registry `delivery.json`; delivery.py, ship_tail.py, ship_verify.py read it | config/registry/delivery.json, scripts/lib/{delivery,ship_tail,ship_verify}.py | 1 |
| 4 | merge-phase reads its bases, `--closes` pattern and repository from the registry | scripts/merge-phase | 3 (names) |
| 5 | manifest `battery.command`, generated CODEOWNERS and aggregates | units/engine-delivery/unit.json, generated outputs | 2, 3, 4 |
| 6 | retro.md | docs/units/engine-delivery/retro.md | final gate |

2 and 3 are independent (different files) and run in parallel; 4 follows 3 (it names registry entries). Files stay in
place: no `@ou` address exists for Python or shell units (S1, U3a), and the executables' paths are the public contract.

## Premises

- P-03 (physical form logical for non-TypeScript units): medium. If wrong, a move is a later expand->contract.
- P-04 (units.size_ceiling): low; the unit is 1,326 lines.
- P-05 (literals migrate with the unit): medium. A missed literal stays visible to `config_check` later.
- P-07 (contract changes go expand->contract): medium; nothing exported changes, so no consumer is touched.
- CRITICAL: none. Nothing here deploys, merges, migrates or touches a secret; production stays frozen (D-054). The
  behaviour of ship-tail/ship-verify/merge-phase is unchanged: every moved value keeps its current number.

## Tests and gate

Per commit: `bash scripts/tests/merge-phase.test.sh` (2), the three unit tests plus `scripts/tests/test_cloud_tail.py`,
`delivery_test.py` (3, 4). Then `scripts/unit-battery engine-delivery` within `battery.unit_time_limit`, and one
`scripts/gate-dev --pr N`.

## Known base defects

`units.manifests()` / `config.get` cost (engine-units, engine-config) makes every `main`-base merge-phase case 0.5 s.
Not fixed here (not this unit's files); the concurrency in commit 2 keeps the unit inside its limit without it.

## Retired helpers cleanup (2026-11-02)

Premises: none

## Alternativas

- A1: Retain the unused helpers and baseline exceptions; preserves dead dependencies.
- A2: Remove only the measured dead surface, test, catalog sites and timeout key.
- A3: Also relocate subject_root; expands the live import boundary without useful gain.

## Escolha

- R1 → A2: remove the unused surface while preserving the live function exactly.

Five commits: measurement and plan; helper/test/catalog removal; catalog classification expectation; registry removal
with generated Python types; and the classification test pinned to the presence of nature and reason instead of a fixed
set of natures, which broke on the first retirement and would break on every later one. Run the requested offline suites
manually; the D-151 gate bypass is not battery evidence.
