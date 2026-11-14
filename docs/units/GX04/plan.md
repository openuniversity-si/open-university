# GX-04 plan

## Commit plan
- [ ] 1. Audit: docs/units/GX04/audit.md.
- [ ] 2. Plan: docs/units/GX04/plan.md.
- [ ] 3. Recorded base: `plan_tick.commit_messages` takes the head; `pr_ready.recorded_base` reads `baseRefOid` once from the forge port and falls back to `plan-tick.base_ref`, reported (files: plan_tick.py, pr_ready.py, test_pr_ready.py).
- [ ] 4. Gated sha and subject root: `ready_after_gate` and the `pr-ready` CLI decide from the sha and `OU_SUBJECT_ROOT`, plan ticks over `baseRefOid..sha`, `lane_id` at its merge base (files: pr_ready.py, test_pr_ready.py).
- [ ] 5. RETRO: docs/units/GX04/retro.md.

## Graph
1 -> 2 -> 3 -> 4 -> 5, sequential: 3 and 4 share `pr_ready.py` and `test_pr_ready.py`; the unit is small enough that sub-agents add no parallelism.

## Premises
- P-02 github source of truth (high, confirmed): `baseRefOid` is read from the forge.
- P-42 (GA-P01) and P-46 (GA-PG1): proof bound to exact head/base; verdict from a checkout that is not the head.
- `OU_SUBJECT_ROOT` exported by `gate-local:168`: verified at audit. Failure would not change scope (not CRITICAL).

## Tests
Per commit 3 and 4: `scripts/run test plan-tick` (runs `test_pr_ready.py`, `test_plan_tick.py`). Final: `scripts/gate-dev --pr <n>` from a clean base-tip checkout (verdict of record, D-A3), plus the report-only own-checkout run.

## Known base defects
None expected; any env abort is recorded verbatim.

Decision: D-070
Premises: P-02, P-42, P-46
Fit-Review: not reviewed (Daniel 2026-10-25: no review step)
