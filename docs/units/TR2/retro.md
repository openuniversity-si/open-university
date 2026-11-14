# TR2 retro

PR #690, branch `claude/merge-train-pr-ready-f7mxzt`, base `mod/roadmap-integration`. Times UTC, 2026-10-27.

## 1. Brief quality
- The brief asked for six goals (A–F) within 150 minutes. Four coordinator messages then cut the scope during the first 15 minutes:
  - 10:36 BRT: minimum scope, tier-2 cleanup dropped;
  - 10:42 BRT: lane first, and the PR to be ready rather than draft;
  - 10:45 BRT: lane moved to TR2b, so TR2 keeps three pieces only;
  - 10:40 BRT: four parallel agents.

  Each cut came after work for the previous scope had started. The PR body was rewritten three times before it was first posted, and audit time went into the lane and approval model that left TR2.
- The brief names the branch `mod/<unit>` while the session harness binds `claude/merge-train-pr-ready-f7mxzt`. I followed the harness, as recorded in the first STATUS comment.
- The brief cites `config.store_cache_ttl_s` (it exists). It calls goal D's measurement "under 30 s on the box", but box credentials are not on this session, so only per-call numbers were taken.
- Missing from the brief: GitHub reviewer logins can never equal lane ids (`engine-lane`). Even with a correct lane, a cross-lane PR can therefore never be approved (audit F4). This is now a TR3 item.

## 2. Audit and plan
- Premises held:
  - the manifest `owner` is the lane: all 105 manifests have no `lane` field;
  - `config.store_cache_ttl_s` exists (60 s);
  - `emit_ready` stays untouched, so TR2b and TR2 edit different functions of `pr_ready.py`.
- Plan changes: the commit plan went from 8 to 6 items. The lane and recorded approvals went to TR2b/TR3, and tier-2 cleanup plus the queue target went to TR3. `plan.md` was rewritten to the final scope in the retro commit, because a separate plan commit would have been a second `Plan: 2` commit.

## 3. Execution (timeline)
- 13:34 audit (Plan 1), 13:35 plan (Plan 2), 13:40 PR #690 opened (ready).
- Two sub-agents ran in parallel, each owning its own files: the config memo (`config.py`, `test_config.py`) and the pr.ready hook (`pr_ready.py`, `gate_report.py`, `test_pr_ready.py`). The main session wrote `train_trigger.py`, the registry key, the trigger tests and the runbook.
- 13:55 Plan 3 (hook), 13:57 Plan 5 (trigger and runbook), 14:02 Plan 4 (memo). Then the gate.
- Failures:
  1. **Literal and unit-dependency class (LT1/U2).** The new code wrote numeric literals (`sha[:8]`, `parents[2]`, `argv[4]`, fixture numbers) and imported across units without declaring them. The push hook's `structure_fast` passed. Only the full `scripts/structure-check` found them: first in commit 3's files, after commit 3 was pushed, then in `train_trigger.py` and two manifests, after commit 5 was pushed. That second hit is an incident: the first class fix covered only the files that check listed then, not every new file. The full fix:
     - a shared `pr_ready.short()` reading `plan-tick.short_sha_chars`;
     - the pr.ready tests import the plan-tick fixtures instead of copying them;
     - the memo tests derive values from one constant;
     - `ROOT` comes from `engine_role`;
     - the `requires` entries were added.
  2. **Queue-reuse race.** The sub-agent's change made `pending()` keep the queue for the next `drain()`, which could drive a batch from a queue read before the lock was taken again. I rejected it, since the memo already makes the second read cheap.
- A sub-agent reported `config/registry/train.json` briefly empty mid-benchmark, because I was rewriting it at the same moment. The two "owned files" lists overlapped on the registry read path. Harmless: a failed parse is never cached.

## 4. Gate
- Run 1 on `8d6b52b4`: PASSED in 146 s (script tests 107 s, structure 15 s), with no known defects hit. The new hook printed `pr.ready: not emitted (plan: items not ticked by a commit: 6)`: correct, because the retro was not committed yet. That was the live proof of the refusal path.
- Run 2 on the retro head: the head whose STATUS and MERGE-READY comments carry it. On that head the hook is expected to emit pr.ready and start the train (off unless `train.enabled`).

## 5. Lessons
| Problem | Change that prevents it | Owner |
|---|---|---|
| Literal and unit-dependency findings surfaced only after the push | Run full `scripts/structure-check` (not just `structure_fast`) before each push that adds a `.py` file or an import of another unit, or move the literal and units checks into `local-checks.json` within budget | engine-lane (push guard) |
| Scope churned four times in 15 min | The coordinator fixes the scope before launch; a cut arrives as one message carrying the final list | coordinator |
| Cross-lane approval cannot exist (review logins against lane ids) | TR3: a `pr.approved` event recorded on the PR log, folded into `approvals()`, with a test that an unapproved foreign change is still refused | engine-lane (TR3) |
| A refused head never re-enters | TR3: a later `pr.approved` on the same head lifts `pr.refused`; until then the lane re-announces with a new head (runbook) | engine-lane (TR3) |
| Tier-2 worktree, cache and refs grow per batch (box at 94% inodes) | TR3: `train.cleanup_after_batch` and a measured tier-2 time | engine-lane (TR3) |
