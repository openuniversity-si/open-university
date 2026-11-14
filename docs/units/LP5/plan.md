# LP5 plan: launch reads the live plan

Premises: P-49. Decision: D-071. Critical path: commit 1 (coordinator + tests) then docs; about 40 minutes.

1. Coordinator reads the folded plan: holds, hold all, launch-hold path, priority, plan_version in launch actions, stale-launch refusal (`scripts/lib/coordinator.py`, `scripts/lib/coordinator_launch.py`, `scripts/tests/test_coordinator.py`), tested against the LP2 fixture through the `provider` seam.
2. Docs: "Live plan" section at the end of `docs/operations/coordinator.md`; this plan.
3. Retro (`docs/units/LP5/retro.md`) after the base-tip gate.

Premises: LP3's fold arrives with the documented shape (`holds`, `priority`, `brief_lines`, `version`); the hold-all key is `all` (blast radius: one constant). Known base issues: none expected; env failures named in the brief.
Targeted tests: `scripts/tests/test_coordinator.py`, `test_coordinator_launch.py`, structure-check, `scripts/program check live-planning`.
