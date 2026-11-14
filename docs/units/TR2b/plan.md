# TR2b plan

Commits in order (each owns its files; no parallel writers on one file):

- [ ] 1. `pr_ready.lane_of` derives the lane from `base...HEAD` against the manifests at the merge base, via `train_ownership.UnitOwnership.lane_of` (same rule as `refusals()`); targeted tests (single lane, multi-lane -> None so still refused, unknown file, a head-added manifest does not choose its lane) and the updated pr_ready test. Files: `scripts/lib/pr_ready.py`, `scripts/lib/train_ownership.py`, `scripts/tests/test_plan_tick.py`.
- [ ] 2. `units/engine-commit-plan/unit.json` declares `engine-train` in `requires` (pr_ready now imports train_git/train_ownership; structure-check U2).
- [ ] 3. Audit: `docs/units/TR2b/audit.md`.
- [ ] 4. Plan: `docs/units/TR2b/plan.md` (mirrors this section).
- [ ] 5. Retro after the gate: `docs/units/TR2b/retro.md`.

Values: manifest glob `train.unit_manifests`, base `plan-tick.base_ref`, git remote/timeout `train.git_*` — all registered; no new literals.
Out of scope (other session): train runner, config.get memo, tier-2 cleanup, approvals (F4), re-entry of refused heads (F5).
Premises: P-13 (one lane per unit; radius medium — if a unit had two lanes the derivation would still yield one lane per manifest, the ownership rule is unchanged). No CRITICAL premise: no production, money or source-of-truth change.
Targeted tests: `python3 -m unittest scripts/tests/test_plan_tick.py scripts/tests/test_train.py`. Final gate: `scripts/gate-dev --pr <n>` once.

Premises: P-13
Capability: none
Instances: TR2 F2, F3
Fit-Review: not structural
Claude-Session: https://claude.ai/code/<session>

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/<session>

Known base defects: structure-check warnings only (35, none from this PR); owners per the warning's unit.
Order note: commit 1 landed before the audit/plan files to meet the 5-minute first-commit deadline in the brief; recorded in the retro.
