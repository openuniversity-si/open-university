# Plan
Critical path: fix (1 file, ~2 min) -> targeted vitest -> gate-dev. No parallel work: one file.
1. audit.md (done)
2. plan.md
3. no-github-actions.test.ts asserts "event log" (title unchanged). Targeted: vitest run on the file (fails before, passes after).
4. retro.md after the gate.
Premises: P-46. Expected base defects (not ours): known env failures, KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3, gate-graph and sync.test.ts timing flakes.
