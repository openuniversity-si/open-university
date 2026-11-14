# TR2 plan (mirrored in the PR description)

Deadline: gate green on the head by 11:05 BRT 2026-10-27 (coordinator 10:36). Scope cut twice: 10:42 and 10:45 BRT (the lane_id derivation went to TR2b).

## Commit plan (scope: coordinator 10:45 BRT; lane_id derivation is TR2b's separate PR; tier-2 cleanup, queue target and recorded approvals go to TR3)
- [ ] 1. Audit (`docs/units/TR2/audit.md`).
- [ ] 2. Plan (`docs/units/TR2/plan.md`).
- [ ] 3. Automatic pr.ready: `gate_report` (pr.ready hook only) calls `pr_ready.ready_after_gate` on a dev `gate.passed` of the exact head with a ticked plan (idempotent per head); a refusal never changes the gate result.
- [ ] 4. Config memo: `config.get` memoizes the registry per process (mtime-invalidated), store override replay memoized within `config.store_cache_ttl_s`; one `queue()` per drain iteration.
- [ ] 5. Transport v0 runner and runbook: after emitting pr.ready the producer starts `scripts/train run` in the background when `train.enabled` (a taken lock is fine); `docs/operations/train.md` and EVENTS.md "The merge train" (box command, pr.refused / pr.ejected / pr.conflicted, re-announce).
- [ ] 6. Retro (`docs/units/TR2/retro.md`).
- [ ] 7. A class-env tier-2 failure halts the train and ejects nobody (found live: the box's first batch ejected #690 on `missing toolchain: postgres`); runbook row.

## Dependency graph and owned files
`1 → 2 → {3, 4, 5 docs} → 5 runner (calls 3's hook) → gate → 6`. 3: `scripts/lib/pr_ready.py` (new function only), `scripts/lib/gate_report.py` (hook), `scripts/tests/test_pr_ready.py`. 4: `scripts/lib/config.py`, `scripts/lib/train.py` (drain only), `scripts/tests/test_config.py`. 5: `scripts/lib/train_trigger.py`, `docs/operations/train.md`, `docs/process/EVENTS.md` (train section).

## Premises
Premises: none

Working premises (not registered):
- **CRITICAL**: none. No production, money or source of truth: the train only merges through the forge with `--match-head-commit` and stays behind `train.enabled`.
- (high) TR2b lands the lane_id derivation in `emit_ready`; this PR only calls `emit_ready`, so the two PRs touch different functions of `pr_ready.py`.
- (medium) `config.get` callers do not mutate returned containers (the memo returns deep copies to be safe).
- (medium) A pr.ready hook failure never fails the gate: the gate.passed already stands and `scripts/pr-ready` stays the manual entry.

## Targeted tests, then one final gate
3: `test_pr_ready.py`, `test_plan_tick.py`, `test_gate_report_skips.py`. 4: `test_config.py`, `config.test.sh`, `test_train.py`, `test_train_role.py`. 5: `train.test.sh`, `train-role.test.sh`, `test_coordinator.py`. Structure check before each push. Then one `gate-dev`.

## Known base defects expected
Owned by BD1 (gate lane); none expected in the files above.
