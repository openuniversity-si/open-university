# GATE-VERDICT-API: judge the merge, not the head (brief step 4)

Measured before any code, 28/10 19:35-19:50 BRT, on the local clone; no gate was run. The brief asked: what the merged
tree changes per stage, and whether the train accepts a proof of a tree that is not a commit. The answer needs a design
change, so this step stops at a proposal and invents no schema.

## How the train judges today

- `train_git.combine` builds each member onto the fetched tip with `git merge-tree --write-tree --name-only
  --no-messages onto head` (`train_git.py:65`). Exit 1 means a conflict and the PR leaves with `pr.conflicted`
  (`train.py:188-191`). Otherwise it runs `git commit-tree <tree> -p onto -p head`, dated from the parents, so the same
  inputs always give the same sha (`train_git.py:71-74`). Nothing is checked out.
- Tier 2 judges the last combined commit: the reuse lookup first (`train.py:291-298`), then `scripts/gate-batch --tier 2`,
  which merges the members again, refuses a tree that differs from the train's (`gate_batch.py:111-118`), and runs
  `gate-local --dev --sha <commit> --plan-file`.
- A proof binds `sha`, `head_tree`, `base_sha`, `plan`, `selection_digest`, `toolchain_id` and `gate_version`;
  `input_digest` covers all but `sha` (`gate_proof.py:135-157`, `gate_digest.py`).
- The train's reuse check (`train_reuse.py:101-104`) accepts a v4 proof only when `pr` is null, the tier is
  `gate-tier.batch`, every key field but `sha` matches, and the union selection digest matches.

## Measurement: what the merged tree changes

The last 30 first-parent merges of `mod/roadmap-integration`. For each, `git merge-tree --write-tree <base parent> <PR
head>` was compared with the merge commit's tree. For each head behind its base, the paths between the head tree and the
merged tree were passed to the gate's own selection, `gate_policy.select_dev_plan`.

| Result | Count |
|---|---|
| `merge-tree` tree equals the merge commit's tree | 30 of 30 |
| head 0 behind: the head tree already is the merged tree | 21 of 30 |
| head behind (5 to 47 commits; 5 of the 9 past `merge.max_behind_base` 20) | 9 of 30 |

| PR | Behind | Paths head to merged | Selection | Stages after the prerequisites whose input differs |
|---|---|---|---|---|
| #777 | 5 | 5 | scoped | 3 |
| #771 | 27 | 75 | full | 15 |
| #724 | 16 | 66 | scoped | 15 |
| #765 | 10 | 16 | scoped | 3 |
| #740 | 29 | 37 | scoped | 3 |
| #763 | 23 | 31 | scoped | 3 |
| #741 | 14 | 19 | scoped | 3 |
| #742 | 33 | 37 | scoped | 3 |
| #751 | 47 | 94 | scoped | 14 |

Per stage, over the 9 behind heads: `install (frozen lockfile)`, `unit tests` and `script tests` saw a different input in
9 of 9 (unit tests declares `**`). `suite union`, `lint`, `typecheck`, `integration tests`, both builds,
`smoke database`, the Chromium e2e run, `browser inventory`, `e2e smoke` and `performance tests` saw one in 3 of 9
(#771, #724, #751: 41 web-test and 22 web-e2e files each for the first two). `gate-db` saw one in 2 of 9. The
prerequisites rerun on every run anyway.

What this means: for 7 of 10 heads the head is the merge, and the verdict is unchanged. For the other 3 of 10, the
tier-1 verdict judged a tree the train will never merge, and in 1 of 10 the whole web battery's inputs differ. #724 is
the blind spot: `merge_behind.decide` accepted it ("16 behind, limit 20, no overlapping changes"), although its proof
never saw the 63 `apps/web` files that #586 had merged 3 s earlier.

## Does the train accept a proof of a tree that is not a commit?

- **Tier 2: yes, with no schema change.** The reuse check ignores `sha` and keys on the merged tree, base, selection,
  toolchain and gate version. A tier-2 proof of a merged tree would be accepted.
- **Tier 1: no.** The per-PR proof fails four of the check's conditions:
  - it is read from the PR's channel, not the repository channel (`train_reuse.py:90`);
  - `pr` is set;
  - its tier is 1;
  - its selection digest is computed with no batch.
- **The train needs a commit.** It recomputes the key from a commit (`gate_batch.py:48-52`, `resolve ^{commit}`). Queue
  admission needs `payload.sha == head` (`train_queue.py:44-46`), and carry-over needs ancestry (`gate_carry.py:82`).
- **No producer exists.** `gate_report.main` publishes only with a PR (`gate_report.py:211-213`), and
  `gate_publish.repository_run` is called only from tests. So the tier-2 reuse lookup cannot hit today, and every
  tier 2 runs.

## Proposal (needs a design decision; not implemented here)

1. **Merge, then judge.** When the head is behind, the PR gate (tier 1) builds `merge(head, base)` exactly as
   `train_git.combine` does: `merge-tree`, then a parent-dated `commit-tree`, which is deterministic. It judges that
   commit. A conflict ends the run as the train's `pr.conflicted` does. When the head is 0 behind (21 of 30), nothing
   changes.
2. **Keep the head as the subject.** The verdict keeps `sha` = the PR head, so queue admission and merge-phase still
   work. `head_tree` becomes the merged tree. That changes what a locked contract field means, so it is a new
   `gate.passed` version under the contract rule (`gate_digest.py`: "a new input is a new gate.passed version"). This
   proposal does not write it.
3. **Give the train a producer.** Wire the repository-channel producer into `gate_report.main` for tier-2 runs, so
   `train_reuse` can hit at all.
4. **One selection recipe.** Tier 1 and tier 2 share one selection-digest recipe.
5. **Only then, reuse across tiers.** A one-member batch on an unchanged base may reuse the tier-1 merged-tree proof.
   That needs an amendment of D-070 (b) / P-43, which today forbid tier 2 to reuse a tier-1 proof. Multi-member batches
   still need tier 2.

Risks to carry into that design:
- `merge-tree` exit 1 needs a tier-1 path for conflicts.
- Rename detection differs: the selection diffs use `--no-renames` (`gate_batch.py:60`, `gate_carry.py:46`), while
  `train_git.changed_files` does not (`train_git.py:79`).
- The merged object needs a ref, or `git gc` prunes it.
- A base-bound proof goes stale as the tip moves (9 of 30 heads were 5-47 behind).

## What this unit ships toward it

The verdict query (step 3) keys on the bound `input_digest`, which already contains `base_sha`. Once proposal 1 lands,
the same query answers for the merged tree with no change to the query: only `head_tree` changes meaning.

Measurement script: `git merge-tree --write-tree` per merge plus `gate_policy.select_dev_plan` over the head-to-merged
paths. It was kept in the session scratchpad and is not committed: it reads only the local clone.
