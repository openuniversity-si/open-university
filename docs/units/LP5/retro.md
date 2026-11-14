# LP5 retro

- Brief: clear. Ambiguous only on how `hold all` appears in the folded `holds` (chose key `all`, one constant) and on `plan_version` in `work.assigned` (contract has no field; CANDIDATE posted).
- Estimate 1.5 h sonnet, actual about 40 min wall: one code commit, one literal-census fix, one retro.
- Plan change: the first commit bundled code, docs and plan, so the 3-item plan reads: 1 all of that, 2 census fix, 3 retro. Item "verify against the real fold" is not done: LP3 had not merged at the final gate (plan_live.fold still a stub); the `provider` seam and the `NotImplementedError` fallback keep launches working until it lands.
- Failure class: a blanket `sed` on a test rewrote two pre-existing lines; the registry literal census (structure-check) caught it. Lesson: edit by anchored patterns, and run structure-check before the first push (it is cheap), not after.
- Staleness is judged per unit view (entry, hold, priority, brief lines), not by a version bump, as design 4 asks.
- Gate: 1 run, `scripts/gate-dev --pr 710`, PASSED in 69 s on the merged base; no known defects hit.
- Open for the planner: after LP3 merges, rerun test_coordinator.py against the real `plan_live.fold` once.
