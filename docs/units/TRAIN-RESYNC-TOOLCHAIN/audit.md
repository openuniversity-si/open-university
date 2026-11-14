# TRAIN-RESYNC-TOOLCHAIN — audit

Read-only, 29/10 ~17:40 BRT, on `mod/roadmap-integration` @ `798ce595` (#805 merged). Decision: D-075. Premises:
P-53, P-43, P-46.

## Entradas
- [intake.md](intake.md): the real problem (a refusal that is not about the base ends in a false `pr.conflicted` or a
  redundant push) and its metric.
- [research.md](research.md): the state of the art (the queue owns its proofs; a proof it cannot trust is a miss it
  re-runs itself on the same input; the author hears only about a real conflict).

## Findings

- **F1. The 19:27Z event, replayed.** `#805` head `05fc438a` contained the tip `13ba2b0e`; `train_admit.admissible`
  refused its `gate.passed` with `toolchain … is not the attested …` (`train_admit.py` toolchain check). Before #805,
  `resync` re-verdicted the same sha; the re-verdict's `pr.ready` has the natural key (repo, pr, sha)
  (`contracts/events/pr.ready.v1.json`), so the forge kept the refused one; the next queue read refused again, the sha
  was in `reverdicted`, and `hand_back` emitted `pr.conflicted` with `files: []` (#805 comment 19:49Z).
- **F2. #805's fix pushes a no-op merge commit.** `train_verdict.resync` now always builds `combine_regenerated(head,
  tip)` and pushes it, also when the head already contains the tip (`train_verdict.py`, comment "a head that already
  contains the tip still gets the merge commit"). The commit has the head's tree and exists only to get a new sha for
  a new `pr.ready`. It moves the owner's branch under the owner session for nothing, and it fails for a fork (the
  hand-back `unpushable`, again with no file).
- **F3. The fresh verdict is already distinguishable without a new sha, except when only warmth differs.**
  `gate.passed` v4's natural key is (repo, pr, sha, plan, input_digest), and `input_digest` includes `base_sha`,
  `toolchain_id` and `gate_version` (`gate_digest.input_digest`). A cold re-verdict on the train's machine of a head
  refused for its toolchain, its gate version or an older base therefore is a **new** `gate.passed` event. Only a
  verdict refused for warmth alone (same base, toolchain and gate) has the same input digest, so the cold re-run is
  the same event (`test_verdict.py::test_a_cold_rerun_of_an_unchanged_input_is_the_same_event`). Only that case
  needs a new sha.
- **F4. The train waits for a `pr.ready` it does not need.** After a PASSED re-verdict, `judge_again` returns and the
  next queue read must admit the PR from its `pr.ready`. The train already knows the head and can read the fresh
  `gate.passed` from the verified source (`Verdicts.evidence`) and admit it in the same pass through the same
  `judge_verdict` and `merge_admitted`: no `pr.ready` dependency, so no dedup trap.
- **F5. Four emit sites can produce `pr.conflicted` with no file.** `hand_back` (`not-admitted`, `unpushable`),
  `merge_admitted` (`forge-refused`) and `Train.merge` (`forge-refused`). `conflicted()` blanks `files` for every
  cause but `textual` and never checks that `textual` has one. The v2 contract allows all of it.
- **F6. What the non-textual causes really are.** `not-admitted` disappears with F4 (a passed re-verdict that still
  does not admit is the machine's or the rules' failure: halt, as an UNOBSERVABLE re-verdict already does).
  `unpushable` is a branch the train cannot write: the tier-2 batch of one merges it without pushing to it
  (`Train.run_batch`, `port.merge` pinned). `forge-refused` is a moved head (the queue's own rule already drops a head
  pushed after `pr.ready`, `train_queue.queue_entry`) or a refusal of a head that is still pinned: a real conflict
  with the tip has files (`train_git.combine`), anything else is not the PR's fault.
- **F7. A skipped PR must not loop the drain.** With the incremental queue index, a PR with no new event keeps its
  entry (`QueueIndex.build`), and without `events_since` every build is the full replay: a PR that leaves silently
  must be excluded for the rest of the run, else `drain` takes it again.

## Distância do estado da arte
We have the input key (F3) and the runner the train controls (`gate-verdict --cold`), so we are one rung short:
the train still routes its own proof through the owner's `pr.ready` (F4) and still reports non-conflicts as
conflicts (F5). This unit reaches the research's "now" rung; typed removal events stay the next one.

## Base defects expected
- `train.verdict_fallback` is `tier2` in the store (workaround); it stays until this merges (outside this PR).
- #804 (GATE-FAST, D-076) changes `--cold`'s meaning to "no result of another tree"; the same-head path keys on the
  input digest, not on how `--cold` is implemented, so it holds either way.
