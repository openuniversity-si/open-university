# TRAIN-VERDICT: plan (mirrored in the PR description)

Decision: D-075 (amends D-065 (5)). Findings: [audit.md](audit.md). Premises: P-53, P-54, P-43, P-46, P-47.

Unified 29/10 14:52 BRT with TRAIN-SHARD-ADMIT ([plan](../TRAIN-SHARD-ADMIT/plan.md)): one program in #802. The
fallback default is `requeue` (the lane merges the base and asks `scripts/gate-verdict --cold` for a new verdict on the
new tip) and shard admission (`train.shard_admit`, default `shadow`) is part of the core. Daniel 15:02 BRT: updating
the base is the train's work, so under `requeue` the train itself merges the tip into the PR head, pushes it, asks
`scripts/gate-verdict --cold` and admits on PASSED; only a textual conflict or a red verdict goes back to the owner.

## Commits

- [ ] 1. Decision and premise: D-075, P-53, this unit record.
- [ ] 2. Registry: `train.admit_mode` and `train.verdict_fallback`.
- [ ] 3. `scripts/lib/train_admit.py`: pure, fail-closed `admissible()`; one test per refusal.
- [ ] 4. `scripts/gate-verdict --cold`: no record read, fresh caches, no carry-over.
- [ ] 5. D-075 amended, P-54, `docs/units/TRAIN-SHARD-ADMIT/{audit,plan}.md`.
- [ ] 6. Registry (`requeue` default, `train.shard_admit*`) and `train_admit.disjoint()` with the shard path of
  `admissible()`.
- [ ] 7. `scripts/lib/train.py`: the verdict branch of `drain()` (strict, shard shadow/on, fallback);
  `scripts/tests/train/test_verdict.py` (a)-(e) and the shard cases.
- [ ] 8. Docs: `docs/operations/train.md`, `docs/process/EVENTS.md`.

Graph: `1 -> 2 -> 3 -> 4`, `3 -> 5 -> 6 -> 7 -> 8`. One commit per push.

## Cheapest useful effort

Action: commits 4-8 on the existing 1-3, shard admission shipped in `shadow`, one gate run on the final head.
Cost: one gate run on the final head (~3-10 min wall; `scripts/lib/train*` and `scripts/gate-*` pull the script suite).
Requirement: Daniel wants a ready PR merged in about a minute when nothing it depends on moved under it, at 1,000
PRs/day where the base is always behind.
Cheaper rejected: `train.batch_size = 1` (still a cold tier 2 per PR); accepting cached verdicts (refutes P-43);
verdict-only admission without shards (only the first PR of a burst lands at once).
