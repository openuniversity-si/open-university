# U4 engine-delivery: audit (read-only findings, D-067, D-069)

Base: `origin/mod/roadmap-integration` at a2c09043 (includes LR1 #575 and CO1 #576). `scripts/lessons for-area` finds no
lesson for these paths.

## The unit today

12 paths, 1,326 lines: `scripts/lib/{delivery,release_policy,ship_tail,ship_verify}.py`, `scripts/{merge-phase,ship-tail,ship-verify}`,
`scripts/release-policy.json`, and three script tests. Far under `units.size_ceiling` (1500 production lines): no `unit.oversize`.

## Physical form (S1, P-03, U3a)

Units stay logical (docs/architecture/UNITS.md). `unit_addresses` gives an `@ou/<id>` only to units inside the
TypeScript project; this unit is Python and shell, so it has no address, no importer uses one, and Node cannot resolve
one. The sibling `engine-architecture-check` (a65a0e10) kept its files in place for the same reason. Moving the files
would also break the executables' paths, which are the public entry contract (and `production.invocation_allowed_paths`).
Decision: files stay in place, nothing is moved or shimmed.

## Contract slot

`unit_battery.plan` turns a manifest `contract` into a step that fails unless the entry is a file under the unit's
address home. With no address that step is always red, so filling `contract` here would make the battery unfillable.
Decision: no `contract` entry; the public surface is the three executables (`scripts/ship-tail`, `scripts/ship-verify`,
`scripts/merge-phase`) whose paths, arguments and exit codes are pinned by their tests. The `battery.command` slot is filled.

## Battery (measured)

`scripts/unit-battery engine-delivery`: red, 24.3 s against `battery.unit_time_limit` (10 s). Per file: delivery 1.0 s,
release-policy 0.2 s, merge-phase 24.0 s. The script-tests step runs a unit's files one after the other, so the unit's
tests must fit the limit together.

Why merge-phase is slow: 45 `expect` calls, one `merge-phase` process each. Cases on a `main` base call
`gate_policy.py classify`, and `gate_select.select` loads the 85 unit manifests (0.42 s, 0.23 s of it `config.get`
re-reading the registry 80 times). Cases are strictly serial because they share one fake server and one `current` symlink.
The manifest loading cost belongs to engine-units/engine-config (`units._cached`, `config.get`): not this unit's files,
recorded as a known base defect with an owner, not touched here.

## Literals (D-068, D-063)

`config_check` finds no registered-name literal today (the production.json readers are x-readers, not literal sites). The
unit still spells unregistered tunables inline:

| File | Literals |
|---|---|
| delivery.py | run timeout 90, repository `openuniversity-si/open-university` |
| ship_tail.py | repository (x3), 40-line log tail, 600 s step timeout, 120 s production wait, `main` base, sha regex |
| ship_verify.py | repository (x4), `MIN_ROLLBACK_COMMIT`, deployment listing limit 20, compare file limit 300, health URL and 12 s, timeouts 180/120/15/30/60/300/0, sha regex |
| merge-phase | `ALLOWED_BASES`, `--closes` pattern, default repository |
| release-policy.json | already the data file of the freeze (D-054); stays |

The repository name is already `forge-events.repo`; one value, one name (D-069 item 1), so it is read from there.

## Tests that cover the unit but are owned elsewhere

`delivery.test.sh` runs `scripts/tests/delivery_test.py` (engine-test-support). `rest_fake.py` is engine-test-support. Not touched.

## Known base defects

- `units.manifests()` costs 0.42 s per process (engine-units, engine-config).
- `scripts/units` and `scripts/unit-battery` are shell wrappers; they cannot be run with `python3`.

## Retired helpers measurement (2026-11-02, base 32054bff9)

The module has five public functions (the brief says four but lists five), in 61 lines.
Repository searches find one production importer: `gate_policy.py` imports `subject_root`.
Only `test_github_cli.py::test_invalid_json_fails_closed` calls `delivery.gh`.
`run` is called only by `gh` and `quota`; `setting` only by `run` and `gh`.
No repository exporter sets `DELIVERY_QUOTA_SCRIPT`. The consumers `ship_tail.py`,
`ship_verify.py` and `neon_pr.py` are absent. The timeout key has only delivery.py
as reader; the remaining delivery keys retain their readers and stay untouched.

The GitHub catalog has nine baseline entries, including the dead `delivery.py:gh`
and `delivery.py:github_cli` sites and their two classifications.
`units.unit_of` resolves delivery.py to engine-delivery, the catalog to engine-vendors,
and test_github_cli.py to engine-github. The registry owner is delivery (`x-owner`),
while its unit is engine-delivery. Every touched production path already has a unit.

### Base verification

Structure reports two errors: R1/plan.md names a machine in Requirement, and
FORGE-PORT/audit.md R2 has only two whys. It reports 15 warnings, saved outside
tracked files for an exact before/after comparison. These unrelated findings stay.

## Causas raiz

### R1 — Retired helper surface (bug local)

1. Why do two dead GitHub sites remain in the baseline? Their helper and import remain.
2. Why do those helpers have no production consumers? The delivery tail left in D-111.
3. Why is the unused timeout still registered? Its sole reader is that retained helper;
   the retirement boundary left this module's unused command surface behind.

### Scope and retained behavior

Remove setting, run, gh and quota, their exclusive imports, the isolated gh test,
the two catalog sites and their classifications, and the sole-reader timeout key.
Keep subject_root byte-for-byte, including its docstring: gate_policy still uses it.
Moving a single-function module is not worthwhile here: it changes a live import
without removing another dependency or improving the requested behavior.

### Final measured result

- delivery.py: 61 → 21 lines; four dead helpers removed, subject_root and its
  docstring preserved byte-for-byte. The only delivery importer is gate_policy.
- GitHub baseline: 9 → 7. A JSON comparison against 32054bff9 proves all other
  entries, ordering and classifications are identical. vendor_check: 0 errors,
  0 warnings. vendor-ports: 49 tests pass after removing the obsolete shim-import
  expectation in test_vendor_classification.py (the last such site was removed).
- Registry: remove delivery.command_timeout_s from its per-key source, regenerate
  the delivery.json aggregate, then run generate python-types. No other delivery
  parameter changes. generate --check passes; local commit_check: 0 refusals.
- gate-split: 11 tests pass. Direct gate_policy.subject_root checks cover the
  default checkout, an explicit directory and refusal of a missing directory.
- github-cli: 19 tests before, 18 after. Both runs fail only
  ConditionalReadTests.test_the_cache_keeps_at_most_its_entries (page 2 was evicted).
  A follow-up run using TMPDIR=/dev/shm reproduces the same failure. No cache code
  or unrelated test was changed; this requested green proof remains unavailable.
- structure-check: the same two base errors remain. All 15 WARN lines match
  before/after item by item, including order, using a direct list equality check.
  The requested zero-error proof remains unavailable without unrelated fixes.
- rg over scripts and config finds no removed helper calls, quota variable or
  timeout key, and only gate_policy's preserved subject_root import.

The brief's count of four public symbols actually names five. The registry's
schema owner (delivery) differs from its owning unit (engine-delivery). No live
reader contradicts removal. The changes intentionally do not move subject_root,
repair base failures, run production actions or mark the PR ready.
