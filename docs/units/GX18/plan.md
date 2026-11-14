# GX-18 plan

Critical path: 1 -> 2 -> 3 (about 20 min); no real parallelism, items share gate_areas.py/test file (collision edges, not data edges).

1. audit.md (done).
2. This plan.
3. Seam + data: `Area.covered_groups` (key `coveredGroups`, validated against groups) in `gate_areas.py`; `plan_for` adds those groups' stages for a path only when `_covered(path)` (lazy `gate_script_tests.load()`, any error = covered, fail closed); `gate-areas.json` docs area gets `"coveredGroups": ["script-tests"]`.
4. Tests in `test_gate_areas.py`: EVENTS.md selects exactly event-contracts via `gate_script_tests.select`; retro.md, docs/programs/**, DECISIONS.md, premises yml fixtures select the covering tests; uncovered doc keeps `picked(SECRETS)`; unreadable covers still selects `script tests`; update docs-only table expectations.
5. RETRO (`docs/units/GX18/retro.md`) after the gate.

Premises: P-42 (GA-P01, CRITICAL, decided), P-10 narrowing fails closed. Tests: `scripts/run test gate-areas`, `gate-test-cache`. Known defects expected: KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3 (not mine).

Commit plan: 1 audit, 2 plan, 3 seam+data+tests, 4 evidence, 5 retro.
