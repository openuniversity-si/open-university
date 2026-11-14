# TRAIN-RESYNC-TOOLCHAIN — plan

Mirrors the PR body of #807. Findings: [audit.md](audit.md). Decision: D-078 (amends D-075). Premises: P-53, P-43,
P-46.

## Commits (sequential, one per push)
1. `intake.md`.
2. `research.md`.
3. `audit.md`, `plan.md`.
4. Same-head re-verdict (F1–F4): a refused verdict of a head that already contains the tip is re-verdicted cold on
   that same sha, with no merge commit and no push, unless only its warmth differs (F3: same input digest, the one
   case that keeps #805's merge commit). Either way the train admits the fresh `gate.passed` in the same pass
   (`judge_verdict` + `merge_admitted`); a passed re-verdict that still does not admit halts the train. Tests: the
   #805 reproduction (another toolchain, unchanged sha merged, nothing pushed), another gate version, the warm case,
   the halt.
5. Guard (F5–F7): `train_verdict.conflicted` raises without at least one file and has no cause but `textual`. An
   unpushable branch takes the tier-2 batch of one; a forge refusal of a moved head leaves the queue for this run in
   silence, of a pinned head that does not merge onto the tip is a textual conflict with its files, otherwise stays
   queued for the next run (skipped for this one). Tests in `test_verdict.py` and `test_batch.py`.
6. D-078 in `docs/domain/DECISIONS.md`, D-075's text pointing to it; `docs/operations/train.md`,
   `docs/process/EVENTS.md`, the `pr.conflicted` v2 description (no new version: the emitted shape is a subset of
   v2), the `train.verdict_fallback` description, the module docstrings.
7. `retro.md`.

## Premises
- P-53 unchanged: the same-head admission is still strict (head contains the tip, tree(head) merged).
- P-43 unchanged: the admitted verdict is the train's own cold run; a warm one is never admitted.
- New, low radius, not registered: "a `gate.passed` whose input digest differs from the refused one is a new event"
  (follows from the v4 natural key; tested).

## Tests
`python3 -m unittest` on `scripts/tests/train/test_verdict.py`, `test_batch.py`, `test_bootstrap.py`,
`test_regenerate.py`, `test_queue.py`, `scripts/tests/test_event_contracts.py`; final `scripts/gate-dev --pr 807`
once on the exact head.

## After merge (not this PR)
The train-role session runs `scripts/config set train.verdict_fallback requeue --reason "D-078: same-head re-verdict
(TRAIN-RESYNC-TOOLCHAIN, #807)"`.

## Cheapest useful effort
Action: change the requeue branch of `train_verdict` in place and guard the payload builder.
Cost: about an hour of session time and one gate run.
Requirement: Daniel, who wants the train to finish ready PRs itself and an owner to get `pr.conflicted` only for a
file to resolve.
Cheaper rejected: keep #805's no-op merge commit for every head that contains the tip (F2); keep `tier2` as the
fallback (a tier-2 run for every refused verdict).
