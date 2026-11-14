# TRAIN-SHARD-ADMIT: plan (the core of the unified TRAIN-VERDICT program, PR #802)

Findings: [audit.md](audit.md). Decision: D-075 as amended 29/10 14:51/14:52 BRT (Daniel: shard admission is the core,
in the same PR as TRAIN-VERDICT). Premises: P-54 (new, high radius, confirmed; partially refutes P-43 for this path
only), P-53 (the strict rule it extends), P-43, P-46 (gate pinned on the tip). The first version of this plan, in the
closed #803, waited for shadow data before any decision; Daniel's 14:52 direction takes the decision now and keeps the
measurement as the gate for switching it **on**.

## 1. The premise (P-54, proposed and answered in #802)

`docs/process/premises/train-shard-disjoint-admits.yml`. Statement: a cold, verified v4 verdict on an older tip `B`
(every D-075 condition except base = tip) also proves the PR on the current tip `T` when `B` is an ancestor of both
`H` and `T`, `T` is at most `train.shard_admit_max_behind` merges past `B`, no `train.shard_admit_never` path is
touched on either side, and the `units+dependents` keys of `B..H` and `B..T` (manifests at `T`, generated outputs
counted) are disjoint. If wrong: an admitted PR lands a tree no gate judged; `train.shard_admit` back to `shadow` (one
key) and revert the `s-` merges since the last green tier-3 confirm. Validation: the shadow measurement of §4, then
every admitted PR's next tier-3 confirm green.

P-43 is **not** answered `superseded`: it stays confirmed for batch reuse and D-075's strict path. P-54 names it in
its reasons, and D-075's text says which clause (the exact merged tree) it narrows.

## 2. The switch

`train.shard_admit`: `off` (never computed), `shadow` (default: computed on every verdict-mode PR whose verdict base
is not the tip; a would-admit is measured, `engine.step.measured` step `train:shard-admit`, result `ok` for
would-admit and `blocked` for a refusal, and the PR takes `train.verdict_fallback` as if the rule did not exist),
`on` (a disjoint PR merges with `batch_id` `s-<input_digest[:12]>`). Only meaningful with
`train.admit_mode = verdict`. Changed through the shared store (`scripts/config set train.shard_admit on --reason …`).

`train.shard_admit_max_behind` (integer, default 5) and `train.shard_admit_never` (globs: lockfiles, root
`package.json`, `config/registry/**`, `scripts/gate-*`, `scripts/lib/gate*`, `units/*/unit.json`).

## 3. Implementation (inside #802's plan; one commit per push)

- #802 item 5: this plan, the audit, P-54 and the D-075 amendment, before code.
- #802 item 6: the registry keys above and `train.verdict_fallback` default `requeue`; `train_admit.disjoint()`
  (pure: never paths, distance, overlap; generated outputs are not skipped) and the shard path of `admissible()`
  (`Shard`: the verdict base is in the head and in the tip, and `disjoint()` found nothing; the digest is recomputed
  with `B`). One test per refusal and the disjoint case.
- #802 item 7: `train.py`'s verdict branch: for a PR whose verdict base is not the tip, compute the shard inputs from
  git (ancestry, `rev-list --first-parent --count B..T`, `changed_files` of both sides, the manifests at `T`) and call
  `admissible()` with them; `shadow` measures and falls back, `on` merges and proves `tree(merge) == merge-tree(T, H)`
  (the computed merge, `train_git.combine`), halting on a difference. Harness tests: shadow measures and merges
  nothing, on admits with zero tier-2 runs, collision requeues.
- #802 item 8: `docs/operations/train.md`, `docs/process/EVENTS.md`.

Not in this PR: the revert of an admitted culprit on a red tier-3 confirm (SH-5 of
`docs/programs/gate-excellence/design-sharded-tier2.md`). While `train.shard_admit` is `shadow` nothing is admitted
behind the tip, so nothing can need it; it is the prerequisite for setting `on` (§4, condition 4).

## 4. Shadow measurement before `on`

Every shadow decision is one `engine.step.measured` `train:shard-admit` on the repository log, with the PR, its head
and the tip; the printed line names `B`, the distance and either `would admit` or the refusal (`overlap on …`,
`never path …`, `… merges behind`). The outcome is joined later from events that already exist: the PR's real path
(the train's resync and re-verdict, `train:reverdict`, then its strict admission; or its tier-2 batch of one), and the next
`battery.green`/`battery.red` on a tip that contains the PR's merge. A **false disjoint** is a would-admit whose PR,
merged by the strict path, is followed by a red tier 2 or tier 3 attributed to an interaction with `B..T`.

A Torre proposes `train.shard_admit on` only when all hold:

1. at least 7 days and 50 would-admit decisions, whichever comes later;
2. **zero** false disjoints (any one is investigated first: a missing `requires` edge is fixed in the manifests and
   the window restarts; two for different causes stop the plan, and the next step is narrower keys or SH-2);
3. a would-admit rate of at least 20 % of the base-moved refusals (below that the rule is not worth its risk);
4. the SH-5 revert path exists (a red confirm reverts the admitted `s-` merge, never a later PR).

## Cheapest useful effort

Action: ship the rule in `shadow` inside #802 (pure check, one branch in the train, measured), so it measures from the
first verdict-mode drain without merging anything on it.
Cost: two of #802's commits and their tests; no extra gate run.
Requirement: Daniel's 14:51 question: the base is always behind at 1,000 PRs/day, so the strict rule alone sends
almost every PR back for a re-verdict.
Cheaper rejected: planning only (#803, no data until another PR); `merge_behind`'s "≤ N behind, no path overlap"
(paths only, misses dependents); `on` by default (unmeasured semantic-conflict risk).
