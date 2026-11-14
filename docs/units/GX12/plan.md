# GX-12 plan

Critical path: item 3 -> item 4 (~25 min); item 5 after the gate. Edges are real (the test needs the functions).

1. audit.md (done).
2. plan.md (this file).
3. `gate_publish.py`: add `repository_run`, `publishes`, `change_number`, `tier`; `should_publish` unchanged.
4. `scripts/tests/test_gate_publish.py` + covers sidecar + `scripts/tests/gate-publish.test.sh`; unit manifest; `scripts/generate`.
5. RETRO.

Premises: P-22 (GitHub write rate, low). Known base defects expected: KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3 (not mine).
Targeted tests: `scripts/run test gate-publish`, `gate-report-skips`. One pinned gate at the end.
