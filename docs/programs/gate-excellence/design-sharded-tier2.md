# Sharded tier 2: design (GX-34)

Status: design, no code. Unit GX-34 of the gate-excellence program (plan.md §3.3; plan-v2 wave A). Implements B-21
(design only) and the first step of O-14; answers GA2 open question 7. G-09 stays open until the build. Decision
D-070. Premises: P-27 (thousand a day is the start, high), P-14 (combined-head failure rate, medium), P-15 (tier-2
duration, medium), P-23 (unit daily capacity, low). Simulation, input and raw numbers:
[docs/units/GX34/simulation.md](../../units/GX34/simulation.md).

## 0. Summary

- One tier-2 lock sustains **24 PRs/h** today and **25 with GX-30** at a 3 % red rate and a 600 s tier 2 (≈ 600/day).
  P-27 asks for 1k/day now and 10k–100k later.
- **Speculative batches (S)** halve the wait on the 27/10 replay, but they saturate near **90 PRs/h** however many
  executors they get, and spend **2–3.4× the tier-2 runs**: one red batch cancels the whole pipeline.
- **Lane/unit-partitioned executors (L)** cost the same 0.24 runs/PR as one train. On the 27/10 mix they are capped
  at **33–54 PRs/h** by the hottest key (engine-lane is in 55 % of PRs, plus its dependents). Once units split with
  volume (P-23) and shared files leave PR diffs, they scale nearly linearly: **L32 ≈ 472, L64 ≈ 661 PRs/h**
  (10k/day = 417/h).
- **Adaptive batch size**: a smaller fixed batch always loses (fixed 4: −24 %). Halve-on-red/double-on-green gains
  +10 % on one train, +14 % on S, 0 on L. Not built.
- **Recommendation**: L keyed by unit + dependents, first in shadow mode, with parallel bisection. L needs a D-NNN
  (a shard's proof covers a merged tree that differs only outside its key, confirmed by tier 3), so shadow mode runs
  before any shard merges. Build units SH-1 … SH-6 (§8), re-planned at C3 with the measures of §9.

## 1. The problem: one tier-2 lock (G-09)

Tier 2 is the batch gate the train runs on the combined head before it merges (D-065 (5)). Today it is one
`LockedRole` behind one forge lock (`train.lock_ref`), so the whole engine merges through one executor:

- a batch of `train.batch_size = 8` costs one tier-2 run of D (GA2 Q1: 614 s cold, ≈ 420 s warm; P-15 estimates 240 s);
- a red batch costs up to `ceil(log2 8) = 3` more runs of serial bisection, and today merges **nothing**
  (`train.run_batch` returns `[]`); GX-30 merges the bisection's proven prefix;
- the all-green ceiling is 8 × 3600 / D ≈ 48 PRs/h at 600 s. At f = 3 % a batch of 8 is red 22 % of the time; the
  measured saturation is **24 PRs/h** today and **25 PRs/h** with GX-30 (§5.2), i.e. ≈ 600 PRs/day. P-27 says
  1 000/day is the start and 10k–100k the aim.

Nothing about one lock is fixed by making D shorter alone: at D = 240 s GX-30 reaches 63 PRs/h (≈ 1 500/day), still
one order below 10k/day. The train needs more than one executor.

## 2. Constraints every design must keep

| Constraint | Source | What it means here |
|---|---|---|
| Tier 2 runs the full dev plan on the combined head and blocks the merge; tiers 2 and 3 never use cached results | D-065 (5) | an executor proves a tree by running it, not by reading a cache |
| Tier 2 reuses a proof only for the exact merged tree and toolchain (attested) | D-070 (b), P-43 (GA-P02 strict) | a proof made on tree X does not cover a merged tree Y ≠ X unless a decision says so |
| The verdict comes from the pinned gate on the base tip | D-070 (e), P-46 | every executor runs the pinned gate (GX-05), never a member's own gate code |
| The lane is the unit of parallelism; PRs of a unit are serial; lanes run in parallel | D-065 (4) | the repository already partitions work by lane; `train_ownership` refuses foreign units |
| Merge commits only, no rebase; the train is the only merger | D-070 (f), D-065 (4) | a shard merges with `--match-head-commit` merge commits, through one merge point |
| The tip after a merge has the tree that was tested | `train.merge` tree proof | the cheap final check exists; a design must say which tree it compares |
| Events, never a clock | D-065, EVENTS.md | executors start on `pr.ready` / `train.batch.*`, never on a poll |
| No literals | D-068 | executor count, shard keys, depth, batch bounds are registry keys |
| Aggregates are not written by PRs | `aggregates-not-written-by-prs` premise | the train may write `CODEOWNERS` and generated modules (`train.publish_aggregates`) |
| Nothing paid without Daniel's OK | D-070 (d), P-45 | an executor is a cloud session on the existing plan; more sessions are a quota question, not a purchase |

## 3. What the 27/10 merge log says (audit)

71 first-parent merges on 27/10 BRT, all by hand (`train.enabled = false`), carrying 110 forced base merges. Mapped
to today's 106 unit manifests:

- **engine-lane is in 39 of 71 PRs (55 %)**; tooling-lane 19; every other lane ≤ 7. A pure lane partition on this mix
  is capped near 1 / 0.55 ≈ 1.8× one train.
- With the units each touched unit's dependents (`requires`, transitively) added, engine-lane is in 53 PRs and
  app-lane in 26: a safe key is wider than the lane alone.
- **Every PR touches a file no manifest claims.** `CODEOWNERS` (25 PRs) and `apps/web/tsconfig.json` (16, its `@ou`
  paths) are generated aggregates; `scripts/lib/gate-script-tests.json` (15), `config/registry/l10n.json` (7),
  `docs/process/EVENTS.md` (5) are hand-edited shared files. Each shared file is a lock every shard would take.

## 4. The designs

### 4.1 L: lane-partitioned executors

k tier-2 executors, each a train of its own over a **shard key**. A batch in flight holds the keys of its members;
two batches in flight never share a key, so their changes are disjoint by construction.

- **Shard key of a PR** = the units it touches (or, coarser, their lanes; §5 compares both) ∪ every unit that
  `requires` one of them (transitively, from `units/*/unit.json`) ∪ every changed path no manifest claims, minus generated aggregates (the
  train regenerates those on its own commit, `train.publish_aggregates`). Computed at the tip the batch is built on,
  like `train_ownership.refusals`.
- **Scheduling**: on `pr.ready` or a batch end, a free executor takes the oldest ready PR whose key is free, then
  adds ready PRs in order whose keys do not meet another in-flight batch, up to the batch size. A PR whose key is held
  waits; it is never reordered past an older PR of the same key (the PRs of a unit stay serial, D-065 (4)).
- **Tier 2 per shard**: the executor builds its combined head on the tip at build time and runs the pinned dev plan
  on it (GX-30's union plan once it exists). Red: bisection on that shard only; GX-30's proven prefix merges.
- **Merge point**: one serial merge step (the existing `train.lock_ref`, now held for seconds, not a tier-2 run).
  At merge time the tip has moved by other shards' merges. The **final tree check** proves that the merged tree
  equals the tested tree plus exactly the other shards' merged changes: `git merge-tree --write-tree <tip> <tested>`
  is clean and every path where the result differs from the tested tree lies outside this shard's key. Then the
  members merge as merge commits and the tree proof of `train.merge` runs against that computed tree.
- **What the check does not prove**: a semantic interaction between two disjoint shards that no import edge in the
  manifests records (e.g. two lanes writing the same database row shape, a runtime registry read). Tier 3 already
  runs the full battery on `integration.advanced`, coalescing to the newest tip (D-065 (5)); in L it is the
  **confirm run** for every merged set of shards, and a red confirm bisects over the batches merged since the last
  green confirm (the batches are the units of revert, `git revert -m 1`).
- **Contract gap (must be decided before the build)**: under P-43 strict, the shard's proof is on tree X (tip at
  build + batch) while the merged tree is Y (X plus other shards' disjoint changes). L therefore needs a decision
  amending D-065 (5) / D-070 (b): *a tier-2 proof covers a merged tree that differs from the tested tree only in paths
  outside the shard's key, provided the next tier-3 confirm on that tip is green before release*. Until that D-NNN
  exists, L can run in **shadow mode** (shards prove and report, the single train still merges), which also measures
  the cross-shard failure rate the decision needs.

### 4.2 S: speculative batches on predicted tips

k executors run batches 1..k at once; batch i is built on the **predicted tip** = tip + batches 1..i-1 (assumed
green). Batch i merges when it is green and every batch ahead of it has merged; the merged tree is exactly the tested
one, so the existing tree proof and P-43 hold **without any amendment**.

- A red batch i cancels every batch behind it (their combined heads were built on a tip that will not exist); they
  are rebuilt on the new prediction (tip + i's proven prefix). The executor time spent on them is the price of
  speculation.
- Bisection of a red batch uses the executors the cancellation just freed: with k ≥ n − 1 every prefix runs at once
  (one round of D instead of `ceil(log2 n)`).
- Needs GX-30 first: rebuild on base move, proven-prefix merge, queue index.
- Independent of the lane mix: S does not care that 55 % of PRs are engine-lane.

### 4.3 Adaptive batch size under red streaks (GA2 open question 7)

The batch size halves after a red batch and doubles after a green one, between `train.batch_min` and
`train.batch_size`. The question is whether a smaller batch during red streaks pays for its extra tier-2 runs. It
applies to B1, L and S alike; §5.4 answers it.

### 4.4 Hybrid: S inside L

Each shard runs its own speculative depth s; L gives the scale across lanes, S hides D inside one hot lane. It only
pays when one shard key holds more ready PRs than one executor drains, which is what lanes splitting (P-23) is meant
to prevent; §6 keeps it as a later option, not a build unit.

## 5. Simulation on the 27/10 merge log

Model, input and every raw table: [simulation.md](../../units/GX34/simulation.md). Short version: the 71 PRs arrive
at their last work commit + 7 min (one tier-1 wall); D = 600 s unless stated; a PR is bad with f = 3 % (P-14); an
ejected PR returns fixed 30 min later; 300 seeds per replay row, 40 per saturation row. "Runs/PR" is tier-2 runs per
merged PR, the executor cost.

### 5.1 Replay of the day

| Design | mean wait (min) | p90 (min) | tier-2 runs | at D = 240 s: mean wait | at f = 10 %: mean wait |
|---|---|---|---|---|---|
| B0 today | 42.6 | 74.1 | 31 | 10.4 | 122.1 |
| B1 GX-30 (proven prefix) | 39.5 | 67.9 | 30 | 9.8 | 109.5 |
| L4 by lane | 18.6 | 35.7 | 49 | 6.7 | 33.6 |
| L4 by unit | 17.3 | 32.8 | 50 | 6.4 | 31.2 |
| L4 by unit + dependents | 30.6 | 56.4 | 39 | 8.8 | 80.3 |
| S4 | 18.3 | 30.8 | 53 | 5.6 | 58.2 |
| S8 | 14.1 | 21.2 | 67 | 5.2 | 35.0 |

On the real day, either design halves the wait of one train. Raising k does nothing for L on this mix (L8 = L4:
engine-lane is the cap), and the safe dependents key costs L most of its gain. S keeps improving with k but pays in
runs. The hand path's 6.7 min median came with 110 forced base merges, each a re-gate (≈ 13 h of tier-1 gate time
that day). The train removes that cost in every design.

### 5.2 Saturation: how many PRs/h each design sustains

A backlog of 994 PRs (14 copies of the day, ≈ 1 000/day) at t = 0, f = 3 %.

| Design | 27/10 lane mix | lanes split with volume (P-23) | lanes split, D = 240 s | runs/PR |
|---|---|---|---|---|
| B0 today | 24 | 24 | 60 | 0.25 |
| B1 GX-30 | 25 | 25 | 63 | 0.24 |
| L4 by lane | 44 | 88 | 209 | 0.24 |
| L8 by lane | 44 | 108 | 254 | 0.25 |
| L4 by unit | 54 | 88 | 208 | 0.24 |
| L4 by unit + dependents | 33 | 89 | 210 | 0.24 |
| L8 by unit + dependents | 33 | 146 | 329 | 0.24 |
| L4, aggregates still in PRs | 39 | 65 | 158 | 0.24 |
| L16 by lane, hand-edited shared files still keys | — | 111 | — | 0.25 |
| L16 by lane, shared files split | — | 216 | — | 0.25 |
| L32 by lane, shared files split | — | 265 | — | 0.25 |
| S2 | 42 | 42 | 102 | 0.30 |
| S4 | 53 | 53 | 127 | 0.49 |
| S8 | 86 | 86 | 202 | 0.58 |
| S16 | — | 91 | — | 0.82 |

With a 2 982-PR backlog (lanes split, shared files split): **L16 310, L32 472, L64 661 PRs/h** at 0.24 runs/PR.
10k PRs/day is 417 PRs/h.

Readings:

1. **S saturates near 90 PRs/h at f = 3 % whatever k is** (S8 86, S16 91). With k batches in flight, the chance that
   one of them is red grows with k, and a red batch cancels everything behind it. Its cost per PR rises from 0.24 to
   0.82 runs. S cannot reach 10k/day at today's red rate.
2. **L scales with k only when the keys are fine enough.** On the 27/10 mix it stops at 44–54 PRs/h (engine-lane,
   or with dependents ≈ 33). Once units split with volume (P-23), it grows nearly linearly (L4 88 → L8 146 by unit
   with dependents) at the same 0.24 runs/PR as one train. Speed comes from parallelism, not from extra runs.
3. **Shared files are L's real ceiling.** Generated aggregates left in PR diffs cost 25 % at k = 4 (88 → 65). The
   hand-edited shared files (`gate-script-tests.json`, `l10n.json`, `EVENTS.md`, …) halve L16 (216 → 111).
4. **D matters as much as k**: D = 240 s (P-15) multiplies every design by ≈ 2.4. Shorter tier 2 (GX-30's union
   plan, GX-11 tiers) and sharding compound.

### 5.3 Adaptive batch size under red streaks (open question 7)

Red streaks: a two-state chain, calm 1 %, streak 35 %, mean streak 8 PRs (≈ 5 % average).

| Design | replay mean wait (min) | saturation PRs/h | runs (saturation) |
|---|---|---|---|
| B1 fixed 8 | 53.1 | 21 | 287 |
| B1 fixed 4 | 65.7 | 16 | 367 |
| B1 fixed 2 | 114.9 | 10 | 576 |
| B1 adaptive 1–8 | 49.0 | 23 | 271 |
| B0 fixed 8 / adaptive | 57.8 / 56.1 | 21 / 21 | 299 / 297 |
| S4 fixed 8 / adaptive | 29.5 / 23.4 | 42 / 48 | 635 / 508 |
| L4 fixed 8 / adaptive | 21.5 / 20.9 | 38 / 38 | 289 / 291 |

Answer: **a smaller fixed batch is always worse** (fixed 4 loses 24 %, fixed 2 loses 52 % of B1's throughput):
bisection already isolates the culprit in `log2 n` runs, and a smaller batch only adds runs. The adaptive rule gains
+10 % on one train (B1), +14 % on S4 and nothing on L4, because L already keeps a red shard from stalling the others.
It is not worth building before sharding. In the recommended design (L) it is not worth building at all. It returns
to the table only if S is built (§7).

## 6. L against S

| | L: lane/unit-partitioned | S: speculative on predicted tips |
|---|---|---|
| Throughput at 1k/day, today's mix | 33–54 PRs/h (capped by the hottest key) | 53 (S4) – 86 (S8) PRs/h |
| Scaling with executors | ≈ linear once units split and shared files go (L64 661/h) | flat near 90/h at f = 3 % |
| Executor cost | 0.24 runs/PR, same as one train | 0.49–0.82 runs/PR (2–3.4×) |
| Red batch | stalls one shard | cancels the whole pipeline |
| Contract | needs a D-NNN: proof on tree X covers merged Y when Y − X is outside the shard key; tier 3 confirms (§4.1) | keeps P-43 strict: merged tree = tested tree |
| Prerequisites | shard key, aggregates written by the train, shared registries split, units splitting when hot | GX-30 (rebuild on base move, proven prefix) |
| Residual risk | cross-shard semantic failures not visible to imports (caught by the tier-3 confirm, before release) | none new; quota burnt on cancelled runs |
| Fits the repository's model | D-065 (4) already makes the lane/unit the unit of parallelism | orthogonal to it |

## 7. Recommendation

**Build L, keyed by unit with dependents, run first in shadow mode. Bisect in parallel on idle executors. Keep the
batch size fixed at 8. Do not build S now.**

- L is the only design that reaches P-27's 10k/day without multiplying tier-2 cost. S tops out near 90 PRs/h at the
  measured red rate and pays 2–3× the runs.
- The key starts at *units + dependents*, the safe reading of D-065 (4). It costs L its gain on today's mix (33 PRs/h,
  still above one train's 25). The lever that returns the gain is narrowing the dependents to changes that touch a
  unit's `contract` (the expand-contract premise). That is a decision for the build, after shadow data (§9).
- L's lever is the repository's own growth model: units split when hot (P-23), aggregates are written by the train,
  shared registries become per-unit files (D-B8, GX-08's sidecars). Each of these is already planned or premised.
  The build adds the one missing piece, the shard key.
- The contract gap (§4.1) is real and is not this unit's to close. Shadow mode runs the shards without merging
  through them, which keeps P-43 intact until a D-NNN says otherwise, and measures the cross-shard failure rate that
  decision needs.
- S stays a later option *inside* one shard (§4.4), and only if one key's queue outgrows one executor after units
  split. Adaptive batch size comes back only with it.

## 8. Build units (re-planned at C3)

Names are provisional; C3 re-plans them with the measurements of §9. All are engine-train work unless stated. Every
verdict-changing unit ships a registry switch, default off, so the first rollback is one key (GA-PG8).

| Unit | What | Files (indicative) | Depends on | Registry keys | Tier / effort |
|---|---|---|---|---|---|
| **SH-1 shard key + shadow** | `train_shard.key(tip, files)` = touched units ∪ their dependents ∪ unclaimed non-generated paths, from the manifests at the tip; each batch emits the shards it *would* form (a new event contract) and the key collisions; the single train still merges | `scripts/lib/train_shard.py`, `train.py` (one call), `config/registry/train.json`, `test_train_shard.py`, one event contract | GX-30 | `train.shard_key` (`"units+dependents"`), `train.shard_shadow` (true) | sonnet · 1.5 h |
| **SH-2 shared files out of PR diffs** | the train writes generated aggregates on its merge commit (`train.publish_aggregates` on, structure check refuses them in PR diffs); remaining hand-edited shared registries split per unit (after GX-08) | `train_aggregates.py`, `structure.py`, the registry files named by SH-1's collision report | SH-1 (which files), GX-08 | `train.publish_aggregates` (true) | opus · 2 h; touches the aggregates' source of truth → CRITICAL check with Daniel before it merges |
| **SH-3 decision: disjoint-shard proof** | a D-NNN amending D-065 (5) / D-070 (b): a shard's tier-2 proof covers a merged tree that differs only outside its key; the tier-3 confirm on that tip must be green before release | `docs/domain/DECISIONS.md` | SH-1 shadow data (≥ 20 real batches) | — | decision (A Torre / Daniel) |
| **SH-4 executor pool + merge point** | k executor slots (`train/lock/<n>`), one merge lock held only for the final tree check and the merges; scheduling by free key (§4.1); the final tree check | `train.py`, `engine_role.py`, `train_git.py`, `config/registry/train.json`, `test_train.py` | SH-1, SH-3, GX-30, GX-31 | `train.sharded` (false), `train.executors` (1), `train.merge_lock_ref` | opus · 3 h |
| **SH-5 tier-3 confirm over shards** | the `integration.advanced` battery is the cross-shard confirm; red → bisect over the batches merged since the last green confirm and open a revert PR (`git revert -m 1`) for the culprit batch | battery role, `quarantine` / `defect_detect` readers | SH-4 | `train.confirm_required` (true) | opus · 2 h |
| **SH-6 parallel bisection** | `engine_role.first_red` probes up to the idle executors at once (one round of D for a batch of 8 with 7 idle) | `engine_role.py`, `test_train_role.py` | SH-4 | `train.bisect_parallel` (true) | sonnet · 1 h |

Not built: adaptive batch size (§5.3), S and S-inside-L (§4.4). Both come back at C3 only if a key's queue
outgrows one executor.

Premises to register when the build starts (`scripts/premises propose`): *cross-shard semantic failure rate*
(to-validate, medium; SH-1 measures it); *one cloud session per executor* (high: L32 for 10k/day means ≈ 32 tier-2
sessions beside the lanes, against `coordinator.max_sessions = 15`. More sessions are a quota/plan question, and money
is Daniel's, P-45).

## 9. What C3 must measure before re-planning

| Measure | Source | Changes |
|---|---|---|
| D, the real tier-2 wall | P-15; `engine.step.measured` `train:tier2` | every throughput row scales with 1/D |
| f, the red rate on combined heads, and the streak length | P-14; `train.batch.red` per PR in the first 20 batches | §5.3; whether S ever pays |
| key collision rate and the hottest key's share | SH-1 shadow events | k worth running; whether dependents must narrow to contract changes |
| shared files left in PR diffs | SH-1 collision report after GX-08 | SH-2's file list |
| cross-shard semantic failures | tier-3 confirm reds attributed to two disjoint shards | SH-3's decision |

If the measured f is ≥ 10 %, every design's wait at least doubles (§5.1). The first unit is then GX-13/GX-32's base
health and contract work, not more executors.
