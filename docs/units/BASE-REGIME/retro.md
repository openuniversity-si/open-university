# BASE-REGIME — retro

Written after the merge (#1026), late: the padrão asks for it before the merge (retro-before-merge.md). Times are BRT, from the
container clock and the train log.

## 1. Brief and intake
- The brief was short and right: "if either says BASE BROKEN, fix the base first in its own PR". The intake named the real
  problem (the whole script suite red since 10:52 BRT) and the metric of "resolved" (suite exit 0, shadow green, regime
  unchanged). That held to the end.
- What was missing: the brief did not say which commit broke the base. Finding it took a diff of the registry defaults
  against the first red shadow, and the cause (the regime default) came out of that diff, not out of the brief.

## 2. Research, audit and plan
- Research pointed at the hermetic judges as the place to pin ambient state. That was the right reading: the hook already
  pinned the store kind for the same reason, so the fix was one more pin in the same hook.
- The audit's root R1 held. The check was a probe: a child under the hook reads `regime.lifted('structure') = False`, a child
  without it reads the registry's `True`. No later failure came from the same cause.
- R2 (the description says "Off by default" while the default is true) was classed as a structural root and handled as the
  text only (alternative A1). Which copy holds the truth stays Daniel's decision; the audit names it as the follow-up, so this
  unit does not claim it is closed.
- The plan carried two alternatives per structural root and a choice for each, as the structure check needs. Premises: none.

## 3. Execution (timeline, BRT)
- 13:55 relaunch. The container train was not running; the train lock was held by the runner VM's train with an empty
  expiry (written 13:54). This session started `scripts/train-loop --shadow` and took the lock (about 14:00).
- 14:00 the first shadow of `3d641027` failed in 0.7 s: exit 2 from preflight, because the train worktree had no `.toolchain/`.
  `scripts/cloud/setup.sh` in that worktree fixed it. Lesson: a new checkout is not a base; check its preflight before reading
  a red shadow as a red base.
- 14:05 the real shadow failed in "script tests" (35.5 s). The full suite in the main checkout showed seven files failing with
  the same names, so this was not a path artifact.
- 14:1x lap #1014, first pass: lane-ship stopped on three generated brief files (E1, RN1, W1) with its own instruction to commit
  them with a `Plan:` trailer. Committed (`c5a21e70`), second pass passed (70 s), merged.
- 14:2x root cause: `9c41dc836` (10:52 BRT) set the regime default to true; every lock lifts through `regime.lifted()`; the
  seven files assert refusals. A throwaway worktree with the default false passed the seven modules. The fix commits came
  next (five commits, one push each).
- Two refusals on the way: the local check wanted a six-cell DECISIONS row and a linked `.test.sh` proof. Both were fixed in the
  same commit before the push; the failed commit left the branch untouched.
- 14:4x lap PR #1026: real gate passed (49.8 s), merged; base `015512cf3`; shadow on that tip passed (45.3 s).
- Laps for the seven PRs: #936 passed (45 s) and merged; #933 passed (67 s) and merged; #1006, #980, #962 and #932 stopped on
  conflicts beyond DECISIONS.md (RC-006). Each stop was aborted by hand, and the branch stayed at its pushed head.
- Operational incidents: (a) the stop hook fired three times during a running lap, because the lap merges the base first and
  the hook counts base history as unpushed; the lap pushes after its structure check, so the hook's push was a no-op (the
  branch was already up to date). (b) The container train was stopped by the background-task limit (30 minutes when no timeout
  is given) at about 14:2x; restarted with the 2-hour maximum.

## 4. Gate
- Real gate runs by this unit: #1026 once (passed, 49.8 s); the shadow on `3d641027` (failed, 35.5 s) and on `015512cf3`
  (passed, 45.3 s); the full suite of `c5a21e700` (failed) and of the new head (exit 0, 141 run, 0 failed, 107 s).
- Known defects hit: none new. KD-3ec4be1f (`config.test.sh`) was not reproduced: the wrapper passes alone.

## 5. Lessons, each with its owner and a concrete change
1. A new piece of ambient state (the regime, D-260) must enter the judges' pins in the same change. Change: a test that fails
   when a lock reads a registry key with no judge pin. Owner: the hermetic harness (engine-gate-tests).
2. The scoped gate did not select the lock tests when the regime key changed, because the locks read it indirectly. Change:
   the readers declared by `x-readers` and the covers include the indirect readers. Owner: engine-gate-tests (lane 9, D-209).
3. A PR that changed the regime merged under the bypass, so no test ran (RC-005). Owner: Daniel (the bypass is his regime).
4. lane-ship stops on append-only manifests that both sides extended (RC-006). Owner: engine-flow (lane 1, this lane).
5. The train runs as a background task of a session, so it stops at the task's time limit. Change: run it as a service on the
   runner (`scripts/service runner`), or write the restart in `docs/process/lane.md`. Owner: Daniel (the runner is his).
6. The stop hook counts base history as unpushed while a lap runs. Change: the hook counts the branch's own commits, or a lap
   ends with its push. Owner: the hook's owner.
7. The description of `regime.exception_active` and its default disagree in meaning (R2). Owner: Daniel, who decides where
   the grant lives; the follow-up is named in D-272.
