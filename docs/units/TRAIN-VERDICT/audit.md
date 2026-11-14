# TRAIN-VERDICT: audit (the train and a PR's own verdict)

Read-only analysis of 29/10 on `80839a23` (= `mod/roadmap-integration` with #798, #800 GATE-API and #801), the base of
this unit. Line numbers are that head's. Decision: D-075 (Daniel 29/10 14:35 BRT), amends D-065 (5). Premises: P-53
(new), P-43, P-46, P-47.

**Summary.** No setting merges a PR on its own verdict today. The train never reuses a PR's proof: the key it
recomputes (`train_reuse.key`) needs `pr: null`, `tier: 2` and a *batch* `selection_digest`, while a per-PR
`gate.passed` has `pr: N`, `tier: 1` and `selection_digest` with `batch: null`, so the key never matches. P-43 only
skips tier 2 when an earlier tier 2 ran the exact same combined commit. The smallest correct change is a **verdict
admission mode** inside the train: the train stays the only merger (D-065 V3, D-A11), but for a PR whose verdict proves
exactly the tree that will land, it merges that PR alone, with no batch and no tier 2.

## 1. How the train decides today

- **Queue.** Built from events only (`scripts/lib/train.py:3-6`). `train_queue.queue_entry` accepts a PR when its latest
  `pr.ready` names the current head, rests on a `gate.passed` of that sha, and no later `pr.conflicted`, `pr.ejected`
  or `pr.merged` exists. The tier-1 `gate.passed` calls `pr_ready.ready_after_gate` (`pr_ready.py:174`); with
  `train.trigger_mode = emit_only` the train-role session (GX-06) runs `scripts/train run`.
- **Batch.** `Train.drain` takes `entries[:batch_size]` (`train.py:312-318`, `train.batch_size = 8`) in critical-path
  order. `start_batch`/`build` (`train.py:182-210`) build the combined head on the tip, one deterministic merge commit
  per member (`train_git.py:58-75`); a conflicting member leaves with `pr.conflicted`; `owned()` (`train.py:170-180`)
  runs the ownership check first (active: 112 unit manifests). `ceil(log2 B) <= train.bisection_max_runs`.
- **Tier 2.** `run_batch` → `tier2` → `judge` (`train.py:279-289`): no proof found, `LockedRole.judge` runs
  `scripts/gate-batch --tier 2 <combined>` with fresh caches, timeout 1800 s (P-15 estimates ~240 s, `to-validate`).
  Red: `train.batch.red`; `halt()` for `env`/`contract`; a proven flake quarantines; `code` bisects and ejects. Green:
  `merge()` (`train.py:366-416`) checks the tip did not move (rebuilds up to `train.rebuild_max`), merges each member
  with `--match-head-commit` (`forge_github.py:170-178`), proves `tree(tip) == tree(tested)` and emits `pr.merged`,
  `train.batch.green`, `integration.advanced`.
- **P-43 and `train_reuse`.** `Train.proof` asks `train_reuse.Reuse.find` (`train_reuse.py:80-95`); the key
  (`l.64-78`) is the combined `head_tree`, `base_sha`, `plan = dev`, the batch selection digest, the attested
  `toolchain_id` and `gate_version`, hashed by `gate_digest.input_digest`; only verified remote events count.
  `matches()` (`l.98-104`) requires `pr is None` and tier 2, so a per-PR verdict (`selection_digest({'plan':'dev',
  'batch':null})`, `gate_proof.py:91-94`) is never reused even with an identical tree.
- **`input_digest`.** sha256 of `[head_tree, base_sha, plan, selection_digest, toolchain_id, gate_version]`; the train
  never trusts the recorded digest, it recomputes it. `gate-verdict` indexes `.gate/verdicts` by it (tier 1 only).
- **`gate_carry`.** Per-PR only (`carry_over_areas = ["docs"]`): a docs-only delta carries the stages of an earlier
  proven head. The train never uses it, but it shows in `gate.passed` (`carried_from`).
- **Merge rule.** `merge.require_exact_head = true`; `exact_head()` halts otherwise. `merge.max_behind_base` and
  `regate_on_overlap` are merge-phase's; the train only prints the distance (tier 2 re-proves on the tip).

## 2. The smallest change

No config-only lever exists: `train.batch_size = 1` still runs a cold tier 2 per PR; `reuse_attested_proofs` (already
true) needs a tier-2 proof; `train.enabled = false` hands merging to merge-phase, which refuses to run in the cloud and
which AGENTS/D-A11 forbid to the PR's own session; `merge.tier1_requires_base_merge` (P-47) is a tier-1 rule.

The condition under which the PR verdict **is** the proof of the merged tree, with zero relaxation:

> If the integration tip `T` is an ancestor of the PR head `H` and the verdict was made with `base_sha == T`, the
> no-fast-forward merge of `H` into `T` has exactly `tree(H)`. The tested tree is the merged tree: P-43 holds literally.

1. `config/registry/train.json`: `train.admit_mode` (`batch|verdict`, default `batch`, x-flag) and
   `train.verdict_fallback` (`tier2|requeue`, default `tier2`).
2. `scripts/lib/train_admit.py`: pure `admissible(...) -> (ok, reason)`, fail-closed: v4, `plan == dev`, verified
   source; `sha == head`, `base_sha == tip`, tip ancestor of head; `toolchain_id` = the train's attestation,
   `gate_version` = the tip's; recomputed `head_tree` and `input_digest` with the PR formula equal the proof's;
   `cache_hits == 0` and no `carried_from` (P-43: never tier-1 box-local markers).
3. `scripts/lib/train.py`: a `verdict` branch in `drain()`: `owned` → `admissible` → `port.merge` (pinned) → tree
   proof `tree(merge) == tree(head)` → `pr.merged` + `integration.advanced` with `batch_id = v-<input_digest[:12]>`;
   otherwise the fallback (`tier2`: today's batch of one; `requeue`: one line, stays queued). Lock, `exact_head()`,
   `halt()` and quarantine unchanged.
4. Docs: `docs/operations/train.md`, `docs/process/EVENTS.md`.
5. Contract: `pr.merged` already has `batch_id`; a `v-…` id needs no contract change.

Touches D-065 (5) (an amendment, so D-075 before code; a gate/merge file, so the body cites it, D-025), D-070 (b)/P-43
(met literally; accepting cached or carried verdicts would partially refute it), D-065 V3/D-A11 (the train-role
session merges, never the PR session), D-054 (target stays `mod/roadmap-integration`), P-46 (makes `gate_version`
comparable), D-069 item 5 / GA-PG8 (the key changes through the shared store).

## 3. Risks

| Risk | Today | Verdict mode |
|---|---|---|
| Base moved after the verdict | Batch rebuilt on the new tip, tier 2 re-proves | Not admissible (`base_sha != tip`), fallback. A window between `tip()` and the `PUT merge` exists only with a concurrent merger (none: the train lock is exclusive); the tree proof after the merge halts the train anyway. |
| Head moved | `queue_entry` drops it; `--match-head-commit` refuses → `pr.conflicted` | Same pin. |
| Textual conflict | `merge-tree` → `pr.conflicted` | Impossible by construction (tip ⊆ head); a forge refusal is `pr.conflicted`. |
| Semantic conflict between disjoint paths | Tier 2 on the combined head | Every admitted PR was tested **on** everything merged before it: unchanged risk, better than merge_behind's path-only rule. |
| Box-local or carried proof | Tier 2 never caches | `cache_hits == 0`, no `carried_from`; needs a cold verdict (`gate-verdict --cold`). |
| Different gate/toolchain | Tier 2 runs the tip's gate | Equal `toolchain_id` and `gate_version` required. |
| CODEOWNERS | The train reads `train_ownership`, not CODEOWNERS; branch protection unverified | `owned()` still runs first. |
| Merge burst invalidates verdicts | One tier 2 serves up to 8 PRs | The real cost: each merge moves the tip; only the first ready PR lands at once, others pay the fallback. Scaling needs disjoint-unit (shard) admission, which relaxes P-43: TRAIN-SHARD-ADMIT. |
| Flake / env | `halt_classes`, quarantine | Nothing runs on the admitted path; a FAILED/UNOBSERVABLE verdict never emits `pr.ready`. |
| Who wakes the train | `emit_only`: the train-role session | Latency depends on that wake. |

## 4. Expected time per merge

Estimates (no tier-2 measurement in the repo; the #798+#800+#801 batch took ~21 min). Admissible PR: ~30-90 s after
`pr.ready` (event reads, fetch, `PUT merge`, fetch + tree proof, 3-5 events). Tip moved, fallback `tier2`: one tier 2
of a batch of one (P-15 ~4 min, probably more) plus the merge. Fallback `requeue`: a base merge and a new verdict
(gate-dev, ≤ 180 s target, D-064 (f)), then ~30-90 s.
