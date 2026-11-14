# GX-FIX-forge-rate-3 — audit

Coordinator order (A Torre, 28/10): base 7224e361 is red on `scripts/tests/gate-db.test.sh` "each stage measured" (line 92). Decision D-070.

## Cause
#718 and #720 store `engine.step.measured` in the local file log (`forge-events.file_kinds`) and publish the verdict once. gate-db.test.sh:92 still read the fake forge's comment store (`$work/api/comments-7.json`) for the stage step `gate:Neon PR migrations`. Reproduced on a clean 7224e361: `gate-db tests: 21 passed, 1 failed`.

## Why #720's gate did not show it
gate-db.test.sh ran in #720's gate (run 2 on 24cb1819) and failed. In the pinned (e7d8bfdb) tooling it crashed first, on `ModuleNotFoundError: No module named 'forge_events'` (the hermetic class, fixed by #716). That is the same signature as on the base, so KD1 adjudication (`gate_report.adjudicate_known_defects` → `defect_detect.apply_to_report`) reported it as KD-335a14a4, and the assertion after the crash never ran. Once #716 removed the crash, the hidden assertion surfaced. Class: a known defect matched on one signature masks every later check in the same test file. Follow-up for the defects owner: the match only holds while the base still fails, and a resolved KD re-runs its test on the head.

## Consumer sweep (every reader of `engine.step.measured` and the gate stage steps)
- Readers through the port (merged with the file log, so correct): train `green_runs` (train.py:210-215), slo `step_stats` (slo.py:78-86), quarantine, battery, unit_map, unit_addresses, `gate_test_cache.measured_durations`, and their unit tests (memory/file adapters).
- Readers of the forge's comment store: only `gate-db.test.sh:91-97` (`grep ... comments-7.json`). Line 92 is fixed. Lines 91 and 97 read `gate.passed`/`gate.failed`, which correctly stay on the forge.
- Guard: `forge_comment_readers` in `test_gate_forge_budget.py` fails any test that positively reads a file-log kind or a gate step from a comment store. It flags 7224e361:gate-db.test.sh:92.

## Same class, owned here (coordinator add-on): #716's d4822d3a in test_forge_events.py
`test_working_tree_gate_records_no_evidence` failed inside a gate run because the child `gate_report` inherited the run's count file (#720) and printed `forge: ...`. #716 scrubbed the env in that one test. The class: any gate_report started by a script test or an inner gate prints the OUTER run's cost. Replaced by an ownership rule in `gate_report.forge_cost(logs)`: a count file is reported only when it sits in the run's own logs dir, where gate-local creates it. The scrub is removed. The test now sets an outer count file explicitly and asserts no output, and a second test asserts that the owning run prints its cost.
