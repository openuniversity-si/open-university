# TR2b audit: lane_id in pr.ready

Read-only findings, 2026-10-27 13:46 UTC, base `mod/roadmap-integration` at `efc7f3b4`.

| # | Finding | Evidence |
|---|---|---|
| A1 | `pr_ready.emit_ready` emitted `lane_id=None` on every head. | `scripts/lib/pr_ready.py:32` at the base. TR2 audit F2 (`claude/merge-train-pr-ready-f7mxzt:docs/units/TR2/audit.md`). |
| A2 | The train judges ownership with `manifest.get('lane', manifest.get('owner')) != lane_id` over `base...head` files, manifests read at the batch base. `None` makes every touched unit foreign. | `scripts/lib/train_ownership.py` `refusals`; `scripts/lib/train.py:160`; `train_git.GitWorkspace.changed_files`. Batch b-ae8150ea8056 refused #580, #586 (ownership). |
| A3 | The manifests already exist in the base (106 `units/*/unit.json`); they carry `owner` (the lane, D-067 (2)) and optionally `lane`. | `git ls-files 'units/*/unit.json'`; TR2 audit F3. |
| A4 | `pr.ready.v1` already allows `lane_id` string or null: no contract change. | `contracts/events/pr.ready.v1.json`. |
| A5 | Every value the derivation needs is registered: `train.unit_manifests`, `plan-tick.base_ref`, `train.git_remote`, `train.git_timeout_s`. | `config/registry/train.json`, `config/registry/plan-tick.json`. |
| A6 | `pr_ready` lives in unit `engine-commit-plan`; importing `train_git`/`train_ownership` (unit `engine-train`) needs a declared `requires` (structure-check U2). | Local `scripts/structure-check --pr-body` FAIL after commit 1. |
| A7 | The existing pr_ready test asserted `lane_id` is None. | `scripts/tests/test_plan_tick.py` `test_pr_ready_cites_the_passed_gate_of_the_head`. |

Not in scope (other TR2 session): approvals never matching (F4), refused heads never re-entering (F5), nobody running the train (F6), runner, config.get memo, tier-2 cleanup.
