# GX-31 RETRO

Unit: tier-2 reuse of exactly-matching attested proofs (PR #741, branch `mod/gx31`). Times UTC, 28/10.

## 1. Brief quality
- The brief assumed tier-2 verdicts already reach a verified forge channel. They do not: `gate_report.main` publishes
  only with a PR (`gate_report.py:211-213`); the repository-channel rule of GX-12 (`gate_publish.repository_run`) has no
  caller (GX-12 retro lesson (c), handed to the `gate_report.py` owner). So the acceptance "rebuilding an unchanged
  batch costs no stage run" is proven by tests with the real producer functions (`gate_proof.bind` + `proof_payload`),
  but cannot be observed in production until that wiring lands. Missing from the brief: the producer side's state.
- The brief fixed the switch key (`train-reuse.reuse_attested_proofs`) but not where the tier-2 plan name comes from;
  `gate-batch` hard-codes `gate-local --dev`. Added `train-reuse.tier2_plan` (a wrong value only makes lookups miss).
- The session harness named branch `claude/gx31-…`; the brief named `mod/gx31`. Used the brief's (one branch, one PR).
- Later messages conflicted (one said merge with `gh pr merge`, the next two said do not merge); followed the latest
  and the unit's hard rule: never merge.

## 2. Audit and plan
- Premise P-43 (GA-P02 strict) held and shaped the design: the train recomputes `input_digest` itself from git,
  `gate_batch.plan`, `gate_proof.gate_version` and the GX-28 attestation; a proof's own digest is never trusted.
- Finding: `engine.step.measured` (the train's flake evidence) is file-routed, i.e. box-local
  (`forge-events.file_kinds`); it is never a reuse source. Only a remote adapter with trusted author associations is.
- Plan held: 6 items. Item 3 had to carry the reader stub because the registry refuses a key whose `x-readers` file
  does not exist (structure check), so the switch and its reader landed together.

## 3. Execution (timeline)
- 03:52 launch; 03:53 skeleton + draft PR #741 + STATUS; 03:55 audit; 03:56 plan; 03:57 switch (Plan 3);
  04:00 lookup (Plan 4) pushed on Daniel's PAUSE (00:57 BRT); paused ~7 h for the test-excellence program.
- 11:2x RESUME: base merge (`da1ac7f5`, conflict in `units/engine-train/unit.json`: TX24 split `test_train.py` into
  `scripts/tests/train/`; resolved by keeping both path sets and rerunning `scripts/generate`).
- 11:26 judge path + tests (Plan 5).
- Failures, each with its class:
  - LT1 numeric literal `parents[2]` and `[:12]` (structure check, twice in two files): class "index literal in new
    code". Fixed with `.parent.parent.parent` and by printing the full digest.
  - Missing `requires` for `engine-gate-run` (new `gate_batch` import): own dependency, declared.
  - Fixture repository had no registry, so `gate_batch.plan` failed: the fixture now carries this checkout's registry
    and unit manifests (as the existing UnionPlan test does).
  - Hermetic rule `wall_clock` in a unit test: used the injected clock.
- Every failure was caught by local checks before a push; no push was refused.

## 4. Gate
One pinned `scripts/gate-dev --pr 741` on the final head; result in the PR's MERGE-READY/STATUS comment.

## 5. Lessons
- Brief template (coordinator): for a consumer unit, state whether the producer of the evidence it reads exists on
  the base, with the caller line. GX-31 depends on GX-12's caller wiring in `gate_report.py`, which is not on the base.
- Follow-up (owner of `gate_report.py`): wire `gate_publish.publishes` / `change_number` / `tier` into
  `gate_report.main` so tier-2 runs publish their v4 verdict on the repository channel; then GX-31's saving is real.
  First real run after that: rebuild a batch whose tier 2 already passed; the train prints `tier 2 on <sha> reuses
  <event_id>` and runs nothing.
- Unit pack hint (coordinator): run `scripts/structure-check` before the first commit of any new `.py` (LT1 index
  literals, `x-readers` existence, unit `requires`, hermetic clock). Already GX-12's lesson (b); it recurred here.
- Coordinator messages: one instruction per state; "merge it" and "never merge" in consecutive messages cost a re-read.
