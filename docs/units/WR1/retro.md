# WR1 retro

## 1. Brief quality
Clear scope. Missing: the branch name `mod/motor-wr1-worktree-resources` already existed on the remote with the closed #529 work, so the push was refused; the brief should say "use a fresh name" (used `mod/motor-wr1-v2`).

## 2. Audit and plan
Premise P-41 held (all four new values are `gate.worktree_*` registry entries). The audit found two more users of the e2e lock than the brief named (`gate-fixed.sh`, `gate_suite.py`) and a fourth in the frozen `ship_verify.py`, left alone (D-054). The plan held; one commit was added for a CODEOWNERS regeneration.

## 3. Execution (UTC clock of the session)
- Audit, plan, registry + helpers, wiring, concurrency test + docs: five commits, pushed one per commit.
- Failure 1 (class: derived file not regenerated): a new path in `units/engine-gate-run/unit.json` made CODEOWNERS drift; the generated-drift stage caught it. Fix: `scripts/generate codeowners`.
- Failure 2 (class: base moved during a gate): a merge of the base into the branch conflicted in `scripts/gate-local` while a gate ran on the merge-pending tree; the gate died in 7 s on a syntax error. Resolved by taking the base's new inventory-skip logic with `env TMPDIR=...` in place of the lock.
- Dead ends: none. `ou_flock` and `ou_free_port` lost their last callers and were removed instead of left as a second mechanism.

## 4. Gate
Three runs of gate-dev on #582: run 1 red (CODEOWNERS drift, plus the premises register test on base), run 2 void (conflict), run 3 green on c7a08c93 in 752 s on 4 vCPU (script tests 587 s). Known base defects hit: `scripts/tests/gate-isolation.test.sh` and `gate-local.test.sh` alt-registry cases fail without `OU_CONFIG_STORE=file` (the copied registry lacks `contracts/`); `test_premises` P-01..P-07 answer check; `generate.test.sh` intents render. None touch this change.

## 5. Lessons
- Pushing a branch name from the brief should fall back to a fresh name automatically: brief template (A Torre).
- Do not run `git merge` of the base while a gate runs in the same tree: the coordinator rule "merge before gating, never during" (CO1 docs).
- Adding a file under a unit manifest requires `scripts/generate codeowners`: `local-checks` could run the drift check for manifest edits (G1 owner).
- Script tests that copy the registry into a temp tree should copy `contracts/` too (engine-config owner).
