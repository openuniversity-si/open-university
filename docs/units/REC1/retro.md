# REC-1 retro

1. Brief: clear. One ambiguity: the brief says `unit_of(root, commit, files)`; the unit-dependency check (D-067 U2) refuses forge_events importing train_git/train_ownership/gate_areas, so the helper takes the `UnitOwnership` object and reuses its `refusals()` (every touched manifest). The brief said to reuse those loaders; this keeps that without a new import edge. The harness also named branch claude/rec1-merge-record-vbg632; the brief's mod/rec1 was used.
2. Audit and plan: premise held that `Train.subject` already forwards `entry.unit`, so only `pr.ready` needed the unit.
3. Execution: two pre-push refusals, both mine and both of one class "a check of the gate that I did not run before pushing": unit_check (import edge) and literal_census (PR numbers 7/8 in a new test). Fixed in the unpushed commit; tests take PR numbers from the shared fixture.
4. Gate: see PR comments.
5. Lessons: a brief that names a helper in an engine unit should say its imports are constrained by units/*/unit.json requires (owner: brief template).
