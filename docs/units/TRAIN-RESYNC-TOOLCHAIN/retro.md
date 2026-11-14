# TRAIN-RESYNC-TOOLCHAIN retro

Unit: TRAIN-RESYNC-TOOLCHAIN, PR #807, branch `claude/train-resync-toolchain-verdict-1tr8u6`, base
`mod/roadmap-integration` at `798ce595` (#805 and #806 merged). Times BRT. Facts from the commits, #805's comments and
the audit.

## 1. Brief quality

- **Stale against the base.** The brief described the 19:27Z code path ("does not produce a new head sha"). #805's
  item 8, merged at 17:15 BRT, had already changed it: a head that contains the tip got a no-op merge commit pushed
  into the owner's branch. Reading #805's 19:49Z comment before the code found it in minutes; the unit then replaced
  that commit rather than adding a second mechanism.
- **Clear on the two outcomes** (same-head cold re-verdict; never an empty `pr.conflicted`), which made the plan
  direct. Not said: what the non-textual causes should become. Decided in the audit (F6) under D-072, with no
  question to Daniel.
- **The config restore** was correctly kept out of the PR; it is in the PR body and D-078.

## 2. Audit and plan

| Premise | Held? | Evidence |
|---|---|---|
| A cold re-verdict with the train's toolchain is a new `gate.passed` event | held | `gate.passed` v4 natural key includes `input_digest`, which includes `toolchain_id`; #805 test merges the same sha |
| Warmth alone gives the same event | held | existing `test_a_cold_rerun_of_an_unchanged_input_is_the_same_event`; the warm test still takes the merge commit |
| Admitting in the same pass removes the `pr.ready` dedup trap | held | the #805 test asserts `pr.merged` on the unchanged sha |
| A silent refusal cannot loop the drain | held | `Train.skipped` per run; the clean-refusal test drains, the next train merges |

Plan changes: none in scope. Item 6 dropped a planned `pr.conflicted` v3 contract: the code guard already makes an
empty conflict impossible and the emitted shape is a subset of v2, so a new version would only cost generated files.

## 3. Execution

- **A red test was pushed on item 5.** The literal census refused the first push (the number of #805 written in the
  guard test). The fix switched the test to a helper that lived only in the `Resync` class, and my shell line pushed
  after `unittest` failed (`;` instead of `&&`). Item 6 moved the helper to the shared fixture and says so in its
  message. Lesson: chain the push on the test's exit code, always.
- Commit 1's `Claude-Session` trailer names another session's URL (copied from #805's trailers); history is not
  rewritten (FP1). Later commits carry this session's.
- The overlap warning with #804 (GATE-FAST) on `train.py`, `train_verdict.py` and `test_verdict.py` is real: whichever
  lands second merges the other in. Neither changes the same functions except `Verdicts.verdict_settings`' neighbours.

## 4. After merge

The train-role session runs `scripts/config set train.verdict_fallback requeue --reason "D-078: same-head re-verdict
(TRAIN-RESYNC-TOOLCHAIN, #807)"` and the next `scripts/train run` takes the tier-2 workaround out of the path.
