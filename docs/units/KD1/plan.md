# KD1 plan (mirrored in the PR description)

`docs/units/` is not a documented home in STRUCTURE.md; the closest documented place for per-unit working documents is
`docs/process/` and the roadmap, but A Torre's order (00:16) names `docs/units/KD1/`, so these two files live there
(decided, reported in the PR).

## Commit plan
1. CAP-012 design (docs only).
2. Audit: `docs/units/KD1/audit.md`.
3. Plan: this file.
4. Contracts: record schema, `defect.*` events, `gate.passed/failed` v3, EVENTS.md rows, unit manifest, generated outputs.
5. Registry: `defects` config keys, library and `scripts/defects` (list, show, record, resolve, check); hash-chained audit trail; dedup by (test, signature); owner from the unit map.
6. Detection in the gate: base re-run in a throwaway worktree cached per (base sha, test id), same-signature match, verdict `known_defects`, `defect.detected`.
7. Router and lifecycle: queue-impact priority, fix unit via `work.assigned`, explicit dependents; open, fixing, resolved, verified closed by the gate; `defects check` in the structure stage.
8. Seed from measured gate output (data only), ops page, D-069 rows.

## Dependency graph and parallel groups
`1 → 2 → 3 → 4 → 5 → {6, 7} → 8`. After 5, commits 6 and 7 own disjoint files and run in parallel (7 by a sub-agent,
6 by the main session); shared files (`scripts/lib/gate-script-tests.json`, `units/engine-defects/unit.json`) are
touched only at integration by the main session, one commit at a time. Each sub-agent commits and pushes its own commit
after its targeted tests pass.

| Commit | Files owned |
|---|---|
| 4 | `contracts/defects/**`, `contracts/events/defect.*`, `contracts/events/gate.{passed,failed}.v3.json`, `schemas.lock.json`, `docs/process/EVENTS.md`, generated outputs, `units/engine-defects/unit.json`, `CODEOWNERS` |
| 5 | `config/registry/defects.json` (keys of this module), `scripts/lib/defects.py`, `scripts/defects`, `scripts/tests/test_defects.py`, `scripts/tests/defects.test.sh`, `gate-script-tests.json` |
| 6 | `scripts/lib/defect_detect.py`, `scripts/lib/gate_report.py`, `scripts/tests/test_defect_detect.py` (+ its registry keys) |
| 7 | `scripts/lib/defect_router.py`, lifecycle functions, `scripts/lib/structure.py` hook, `scripts/tests/test_defect_router.py`, `scripts/tests/test_defect_lifecycle.py` (+ its registry keys) |
| 8 | `docs/**`, `docs/process/defects/*.yml` |

## Premises
Premises: none registered. Working premises, with blast radius:
- **CRITICAL**: none. No production, no money, no source-of-truth change (production is frozen, D-054; nothing deploys or migrates).
- (high) A failing script test is comparable on the base by its normalized signature (`gate_failures.normalize`). A wrong match would excuse a PR's own failure. Mitigation: exact equality; an unresolvable base, a timeout, a different signature or a stage outside `defects.stages` is the PR's own (fail closed).
- (medium) The base can be re-run in a throwaway worktree with the PR's toolchain; if not, the failure stays the PR's own.
- (medium) The unit map gives every seeded test an owner; unowned tests get `defects.unknown_owner`.
- (low) `gate.passed/failed` v3 is read by the highest version in the port; v2 readers keep working (expand, no contract).

## Targeted tests per commit, then one final gate
4: `event-contracts.test.sh`, `scripts/generate --check`. 5: `test_defects.py`, `config.test.sh`. 6: `test_defect_detect.py`, `gate-failures.test.sh`. 7: `test_defect_router.py`, `test_defect_lifecycle.py`, `structure-check.test.sh`. 8: `scripts/structure-check`. Then a single `gate-dev` (selective, per-test cache).

## Known base defects expected (not fixed here)
- `scripts/tests/premises.test.sh` (`Repository.test_repository_register_is_valid`, answered by `measurement:S1`); owner from the map.
- `scripts/tests/generate.test.sh` (`intents-doc.ts`, `ERR_MODULE_NOT_FOUND`); owner from the map.
