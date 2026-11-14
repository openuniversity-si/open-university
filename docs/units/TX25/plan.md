# TX25 plan: orphan tests run; wrappers glob

Lane: engine-lane. Branch `mod/tx-orphans`, PR #748, base `mod/roadmap-integration`. Decision: D-070.

## Commits (dependency graph)

```
1 audit + plan ──> 2 orphan wrappers ──> 3 wrappers glob ──> 4 derived check ──> 5 structure-check call ──> 6 retro
```

2 and 3 are independent of each other; 4 needs both (it is red on the base until the orphans and the double are
gone); 5 needs 4.

| # | Commit | Files | Targeted tests |
|---|---|---|---|
| 1 | Audit and plan | `docs/units/TX25/{audit,plan}.md` | none |
| 2 | Wrappers for the two orphans | `scripts/tests/gate-gc.test.sh` (already listed by `units/engine-gate-run`), `scripts/tests/text-check.test.sh` + `units/engine-config/unit.json`, `scripts/tests/covers/{gate-gc,text-check}.json`, CODEOWNERS regenerated | both wrappers, `gate_script_tests.py check` |
| 3 | Hand-listed wrappers glob `test_<module>*.py`; `test_neon_migrate.py` runs once (neon only) | `structure-check`, `program`, `plan-tick`, `coordinator`, `hermetic`, `generate`, `gate-report-skips`, `gate-areas`, `cloud-tail`, `neon` `.test.sh`; their covers gain the glob | each converted wrapper, before/after file lists |
| 4 | Derived check `scripts/lib/test_orphans.py` (`check(root)` + CLI) with its keys in `config/registry/test-orphans.json` | + `scripts/tests/test_test_orphans.py`, `scripts/tests/test-orphans.test.sh`, `scripts/tests/covers/test-orphans.json`, `units/engine-gate-plan/unit.json` | `test-orphans.test.sh` |
| 5 | structure-check runs it (one call, plus its import) | `scripts/lib/structure.py`, `units/engine-structure/unit.json` `requires` if unit_check asks | `structure-check.test.sh` |
| 6 | Retro | `docs/units/TX25/retro.md` | none |

Single final gate: the pinned gate (`OU_CONFIG_STORE=file`) on the exact head, once, after 6.

## Glob form

A wrapper names a module, never a file: `"$root"/scripts/tests/test_<module>*.py` (picks up a later split
`test_<module>_<feature>.py`, the TX24 form). An unmatched glob stays literal and python fails on it: loud, never
skipped. Where a module glob would capture another wrapper's file the wrapper keeps the exact name
(`program.test.sh`: `test_program.py`, because `test_program_gate.py` is coordinator's). Order inside each wrapper is
unchanged.

## Derived check

Tests: `scripts/tests/test_*.py` and `scripts/tests/<module>/test_*.py` (TX24 directory form; the fixture and covers
directories are not test directories, registry key). A wrapper runs a file when a non-comment line holds a
`test_*.py` token that matches it as a glob (with `<module>/` when the token carries it, or a `discover -s` of that
directory). Errors:
- `<file>: run by no wrapper; extend the glob of the wrapper of its module (scripts/tests/<module>.test.sh) or add one`
- `<file>: run by N wrappers (a, b); narrow the glob of all but one`

## Premises

| Premise | Radius | Holds? |
|---|---|---|
| P-46 the verdict comes from the pinned gate on the base tip | program | cited by the brief |
| Only `.test.sh` wrappers run `scripts/tests/test_*.py` (no stage runs a test file directly) | **CRITICAL** (a false orphan error would block every PR) | checked: `gate_script_tests.py` is the only runner of `scripts/tests/` |
| Comment lines never run a test | low | `gate-local.test.sh:164,167` are the only comment mentions |
| Removing `test_neon_migrate.py` from `cloud-tail.test.sh` loses no assertion | low | the same file still runs in `neon.test.sh`, unchanged |

The inventory is derived, never weakened: the same failing fixture (an orphan, a double) fails the check in its tests.

## Pending PRs

- #662 N1 edits `scripts/tests/structure-check.test.sh` (one listed file). After this merges the wrapper globs
  `test_<module>*.py`: N1 drops its line (its new file is either matched by a glob or gets its module's glob).
- TX24 (`mod/tx-pysplit`) owns `train`, `forge-events`, `gate-status`, `planner-role`; the check accepts its
  `scripts/tests/<module>/test_*.py` form.
