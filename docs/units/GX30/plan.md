# GX-30 plan (mirrored in the PR description)

## Plan
- [ ] 1. `docs/units/GX30/audit.md`: findings and evidence.
- [ ] 2. `docs/units/GX30/plan.md`: this plan.
- [ ] 3. Union plan: `train.tier2_command` = `["scripts/gate-batch", "--tier", "2"]`; `scripts/gate-batch --tier 2 <combined>` reads the base and members from `GATE_BATCH_BASE` / `GATE_BATCH_MEMBERS` (ignored by the rollback `gate-dev --sha`); `gate_batch.plan(..., head=)` verifies the given combined commit has the union's tree and gates that sha; `engine_role.CommandGate.run(commit, env=)` and `LockedRole.gate_env`; the train passes each prefix's members (combined head and bisection probes). Tests: an app-only batch's plan has no `script tests` stage; a train run hands the members to the command. `scripts/run test train`, `gate-batch`.
- [ ] 4. Rebuild and proven prefix: `train.rebuild_max` (2). A base move between build and merge rebuilds the batch on the new tip (at most `train.rebuild_max`, then the old halt); a forge refusal merges the proven prefix, the refused member leaves (`pr.conflicted`) and the rest is rebuilt on the new tip and judged once more, inside the same budget. Tests: refusal merges the rest; base move rebuilds; the bound halts. `scripts/run test train`.
- [ ] 5. Queue index `scripts/lib/train_queue.py` + `train.queue_since_last_batch` (true): the first build is the full replay (unchanged); later builds in the same run read only the events since the last build (adapter capability `events_since`), and the logs and heads of the PRs those events name; without the capability or with the switch off, the full build. Claimed in `units/engine-train/unit.json`, `CODEOWNERS` regenerated (`scripts/generate`), covers sidecar. Test: REST calls per rebuild = 2 + 2 × new ready PRs in a fixture with many open PRs.
- [ ] 6. Critical-path member order (MQ1 harvest: most transitive dependents in the unit graph first, then FIFO) inside each batch, so prefixes and bisection follow it; the batch's tier-2 verdict `event_id` is computed, returned and printed with the batch line (the payload field waits for a v2 contract, GX-37's files). Tests in `test_train.py`.
- [ ] 7. `docs/units/GX30/retro.md`.
- [ ] 8. The train reads the merge rule from `config/registry/merge.json` (GX-22 keys `merge.require_exact_head`, `merge.require_mergeable`, `merge.max_behind_base`, `merge.tier1_requires_base_merge`) through the config module, with a test. Was blocked on GX-22 (REAL-merge edge); done after GX-22 (#722, d889e6a1) merged: `merge.require_exact_head` off halts the train (the merge-phase refusal), each member gets `merge_behind.limit_line`; `require_mergeable` is met by the combined build and `tier1_requires_base_merge` is commit_check's rule.

## Graph and critical path
1 → 2 → 3 → 4 → 5 → 6 → 7 (→ 8 after GX-22). Edges 3 → 4 → 6 are file collisions on `train.py` / `test_train.py` / `train.json` (one writer); 5 is a new module but its call site and keys are in the same files. No split pays for itself at this size (≈ 2 h of serial edits vs. a prep split of the train files that plan-v2 §2 already rejected), so the commits run in sequence in one writer; the gate runs once at the end. Critical path ≈ 2.25 h + one gate run (≈ 5–8 min).

## Premises
- P-14 combined-head failure rate (medium): a rebuild costs one more tier-2 run; bounded by `train.rebuild_max`.
- P-15 tier-2 cloud duration (medium): the union plan is what shrinks it.
- P-42 (GA-P01), P-43 (GA-P02 strict: no reuse here, GX-31), P-46 (GA-PG1 pinned gate verdict), P-47 (GA-PG3, merge rule; item 8).
- No CRITICAL premise: no money, production or source of truth. Rollback: `train.tier2_command` back to `["scripts/gate-dev","--sha"]`, `train.rebuild_max` 0, `train.queue_since_last_batch` false (one key each).

## Tests and final gate
Per commit: `scripts/run test train`, `scripts/run test gate-batch`, `scripts/run test train-role` when `engine_role.py` changes. Final: the pinned `scripts/gate-dev --pr <n>` once.

## Known base defects expected
GX-ENV: `claude-session.test.sh`, `root-identity.test.sh`, `config.test.sh`, uid-65534 fs-encoding crash. Gate KDs: KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3 (FIX-modules #712).

## Decisions taken here (reversible)
- Branch `mod/gx30` as the brief names it (the harness default `claude/gx-30-…` is not used: one branch, one PR).
- `scripts/gate-batch` (unit engine-gate-run) is edited: the tier-2 command must accept `--tier 2`; no other file of that unit changes.
- Members travel to tier 2 in the environment, so the rollback command needs no train change.
