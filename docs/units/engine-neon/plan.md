# engine-neon plan (mirrored in the PR description)

## Commit plan
1. Audit (`docs/units/engine-neon/audit.md`).
2. Plan (this file).
3. Register the tunables: `config/registry/neon.json`, and `neon_migrate.py`, `neon_pr.py`, `migration_order.py` read them through `config.get`.
4. Battery: `scripts/tests/neon.test.sh` runs the unit's Python tests, tests for the registry reads, manifest and script-test mapping updated.
5. Generated outputs (`scripts/generate`) and retro.

## Dependency graph and owned files
`3 → 4 → 5`, serial: 3 and 4 share the unit's test file and the manifest.
| Commit | Files owned |
|---|---|
| 3 | `config/registry/neon.json`, `scripts/lib/{neon_migrate,neon_pr,migration_order}.py` |
| 4 | `scripts/tests/neon.test.sh`, `scripts/tests/test_neon_migrate.py`, `units/engine-neon/unit.json`, `scripts/lib/gate-script-tests.json` |
| 5 | generated outputs, `docs/units/engine-neon/retro.md` |

## Premises (Premises: P-03, P-04, P-05, P-07)
- P-03 (radius medium): units stay logical; no Python address exists. If wrong, files would move to `units/engine-neon/`; the manifest edit is reversible.
- P-05 (high): literals migrate with the unit. Wrong: values stay inline and the no-literals check keeps passing; nothing breaks.
- P-07 (medium): contract changes go expand→contract. The slot stays empty (it would fail the battery), so no consumer changes.
- CRITICAL: none. No production, money or source of truth is touched; Neon code is edited, never run.

## Tests
Per commit: `python3 scripts/tests/test_neon_migrate.py`, `scripts/unit-battery engine-neon`, `scripts/structure-check`. One final `gate-dev`.

## Known base defects
Timing-sensitive tests (tower-catalog cover concurrency, read-latency) on 4 vCPU: not touched, owned by the catalog lane.
