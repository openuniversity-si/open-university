# REC-1 plan

Critical path: C2 -> C3 -> C4 (about 20 min). Edges are real (C3 needs the helper and the mirror flag); docs C5 only collides on nothing and runs in parallel.

1. audit (done).
2. plan (this file).
3. `forge_events`: `unit_of(root, commit, files)` + `emit(..., repository=True)` mirrors the envelope to the repository channel in the same publish. Tests: `scripts/tests/forge_events/test_unit_of.py`, mirror test.
4. `pr_ready.emit_ready` passes `unit_of`; `train.merge` emits `pr.merged` with `repository=True`. Tests in test_train.py / test_gate_v4_readers.py.
5. EVENTS.md row, retro.

Premises: P-43 (the record is the events), P-46 (events carry the unit). Blast radius: the event shape is unchanged, so replay and readers are unaffected. None CRITICAL.
Targeted tests per commit: the files above plus the existing train, pr-ready and forge_events suites; one pinned gate-dev at the end.
Expected base defects: claude-session, root-identity, config shell tests; KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3.
