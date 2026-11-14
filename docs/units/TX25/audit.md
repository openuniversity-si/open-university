# TX25 audit: orphan tests and hand-listed wrappers

Base: `origin/mod/roadmap-integration` 891b835ae (2026-10-28). Every line below was re-read on that base.

## What runs a Python test

The script suite runs `scripts/tests/*.test.sh` (`scripts/lib/gate_script_tests.py:24` `discover`, one covers manifest
each under `scripts/tests/covers/`). Nothing else runs a `scripts/tests/test_*.py`: a test file runs only when a
wrapper names it (a path, a `for` list, a `unittest discover -p` pattern or a glob) on a non-comment line.

Census on the base: 90 wrappers, 106 `scripts/tests/test_*.py`, no `scripts/tests/<dir>/test_*.py` yet.
A prototype of the derived check (every non-comment `test_*.py` token of every wrapper, matched as a glob) finds:

| File | Run by | Finding |
|---|---|---|
| `scripts/tests/test_gate_gc.py` (10 tests) | no wrapper | orphan (brief evidence holds) |
| `scripts/tests/test_text_check.py` (21 tests) | no wrapper | orphan (brief evidence holds) |
| `scripts/tests/test_neon_migrate.py` | `cloud-tail.test.sh:4` and `neon.test.sh:4` | **new**: run twice per full suite |

All other 103 files are run by exactly one wrapper. Mentions inside comments (`gate-local.test.sh:164`,
`gate-local.test.sh:167` name `test_gate_report_v4.py` and `test_gate_carry.py`) are not runs.

`units/engine-gate-run/unit.json:32` lists `scripts/tests/gate-gc.test.sh`, which does not exist (structure-check:
"path scripts/tests/gate-gc.test.sh matches no tracked file").

First local run of the orphans on the base (no wrapper, run by hand):

```
test_gate_gc.py     Ran 10 tests in 1.510s  OK
test_text_check.py  Ran 21 tests in 9.549s  OK
```

Both are green: the lost coverage is real but hides no defect today.

## Hand-listed wrappers (more than one Python file named by hand)

| Wrapper:line | Files |
|---|---|
| `structure-check.test.sh:5` | test_structure, test_postmortem_check, test_decision_premises, test_threshold_check |
| `program.test.sh:6-8` | test_program, test_plan_live, test_plan_triage |
| `plan-tick.test.sh:5-7` | test_plan_tick, test_gate_v4_readers, test_pr_ready |
| `coordinator.test.sh:5-7` | test_coordinator, test_coordinator_launch, test_program_gate |
| `hermetic.test.sh:5` | test_hermetic, test_hermetic_check |
| `generate.test.sh:5-6` | test_generate, test_aggregates |
| `gate-report-skips.test.sh:4-5` | test_gate_report_skips, test_gate_report_v4 |
| `gate-areas.test.sh:3-4` | test_gate_areas, test_gate_plan |
| `cloud-tail.test.sh:3-4` | test_cloud_tail, test_neon_migrate (the double) |
| `forge-events.test.sh:5` | TX24 owns it; not touched here |

Single-file wrappers (`python3 .../test_x.py`) are not lists; the derived check reads them as they are.

## Glob hazards found

A per-module glob `test_<m>*.py` can capture another wrapper's file: `test_program*.py` would also match
`test_program_gate.py` (coordinator). The derived check is what keeps globs disjoint; `program.test.sh` keeps
`test_program.py` exact.

## No existing check

`scripts/lib/gate_script_tests.py` checks that each wrapper has a covers manifest; nothing checks that each
`test_*.py` is run. That is the gap TX25 closes (T1/T10).
