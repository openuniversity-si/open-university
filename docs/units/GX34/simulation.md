# GX-34 simulation: tier 2 on the 27/10 merge log

The simulator behind `docs/programs/gate-excellence/design-sharded-tier2.md` §5, in full, with its input and its raw
output. It is kept here as a fenced block so the unit stays docs-only (no `.py` file enters the engine's literal,
structure and script-test scans); to rerun it, copy the block to a scratch file and run, from a checkout of the base:

```bash
python3 sim.py extract in.json   # reads git and units/*/unit.json; deterministic for a given base
python3 sim.py run in.json       # ≈ 30 s on one vCPU; prints the tables below
```

## Input

Source: `git log --merges --first-parent origin/mod/roadmap-integration` for 27/10 BRT (03:00Z 27/10 to 03:00Z 28/10),
base 4bc4dd04: **71 merges**. Per merge: the files it brought (`git diff <first parent> <merge>`), the lanes of
today's 106 unit manifests that claim them (first manifest whose `paths` match, as `train_ownership` does), the files
no manifest claims (split into generated aggregates — `CODEOWNERS`, the `@ou` paths of `apps/web/tsconfig.json`,
`scripts/lib/generated/`, `contracts/generated/`, `apps/web/src/generated/` — and hand-edited shared files), and the
time of the PR's last non-merge commit. The repository event log was not replayed: the train was off on 27/10
(`train.enabled = false`), so it holds no `train.batch.*` event, and git already has the arrival and file data.

Limits of the input, stated once: today's manifests are applied to yesterday's diffs (several units were created
on 27/10 itself); the ready time is a proxy (last work commit + one tier-1 wall), not a recorded `pr.ready`; the
coordinator merged by hand, so the real waits (head → merge median 6.7 min, p90 19.5 min) came with **110 forced base
merges** inside the 71 PRs, a cost the replay does not charge to the hand path.

| PR | last work commit (BRT) | merged (BRT) | lanes | units / incl. dependents | lanes incl. dependents | shared files: generated / hand-edited |
|---|---|---|---|---|---|---|
| #550 | 26/10 23:49 | 27/10 00:04 | engine | 8 / 30 | 1 | 1 / 6 |
| #572 | 27/10 00:56 | 27/10 01:00 | engine | 7 / 30 | 1 | 11 / 17 |
| #574 | 27/10 01:25 | 27/10 01:27 | engine | 5 / 30 | 1 | 1 / 6 |
| #575 | 27/10 03:07 | 27/10 03:08 | engine | 5 / 30 | 1 | 7 / 10 |
| #576 | 27/10 03:36 | 27/10 03:40 | engine | 4 / 30 | 1 | 2 / 6 |
| #597 | 27/10 03:50 | 27/10 03:52 | engine | 1 / 1 | 1 | 0 / 4 |
| #601 | 27/10 03:56 | 27/10 03:59 | engine | 1 / 30 | 1 | 0 / 4 |
| #583 | 27/10 03:50 | 27/10 04:00 | identity | 1 / 77 | 13 | 0 / 3 |
| #599 | 27/10 03:55 | 27/10 04:01 | tooling | 10 / 12 | 2 | 0 / 2 |
| #602 | 27/10 03:56 | 27/10 04:02 | fidelity | 2 / 10 | 3 | 0 / 3 |
| #577 | 27/10 03:43 | 27/10 04:03 | engine | 3 / 30 | 1 | 1 / 4 |
| #614 | 27/10 04:01 | 27/10 04:04 | engine | 1 / 30 | 1 | 0 / 4 |
| #617 | 27/10 04:02 | 27/10 04:05 | engine | 1 / 30 | 1 | 0 / 4 |
| #611 | 27/10 04:03 | 27/10 04:06 | engine | 2 / 30 | 1 | 0 / 3 |
| #609 | 27/10 04:05 | 27/10 04:08 | engine | 2 / 30 | 1 | 0 / 5 |
| #589 | 27/10 04:02 | 27/10 04:08 | media | 3 / 87 | 15 | 0 / 3 |
| #613 | 27/10 04:02 | 27/10 04:08 | engine | 1 / 1 | 1 | 0 / 4 |
| #585 | 27/10 04:04 | 27/10 04:08 | engine | 2 / 30 | 1 | 0 / 5 |
| #593 | 27/10 04:03 | 27/10 04:09 | platform | 6 / 87 | 16 | 0 / 3 |
| #619 | 27/10 04:10 | 27/10 04:11 | – | 0 / 0 | 0 | 0 / 4 |
| #581 | 27/10 04:00 | 27/10 04:12 | site | 2 / 91 | 16 | 0 / 3 |
| #590 | 27/10 03:59 | 27/10 04:16 | progress | 1 / 77 | 13 | 0 / 3 |
| #579 | 27/10 04:11 | 27/10 04:17 | catalog | 8 / 77 | 13 | 0 / 4 |
| #623 | 27/10 04:10 | 27/10 04:18 | fidelity, tooling | 2 / 7 | 3 | 1 / 2 |
| #624 | 27/10 04:11 | 27/10 04:19 | factory, tooling | 2 / 16 | 4 | 0 / 4 |
| #629 | 27/10 04:18 | 27/10 04:21 | – | 0 / 0 | 0 | 0 / 5 |
| #606 | 27/10 04:19 | 27/10 04:21 | engine | 2 / 30 | 1 | 1 / 4 |
| #621 | 27/10 04:09 | 27/10 04:23 | tooling | 2 / 13 | 3 | 1 / 4 |
| #587 | 27/10 04:12 | 27/10 04:23 | engine | 3 / 30 | 1 | 1 / 5 |
| #628 | 27/10 04:18 | 27/10 04:26 | tooling | 1 / 6 | 2 | 0 / 5 |
| #608 | 27/10 03:55 | 27/10 04:26 | engine | 1 / 30 | 1 | 0 / 3 |
| #582 | 27/10 04:24 | 27/10 04:29 | engine | 6 / 30 | 1 | 1 / 9 |
| #636 | 27/10 04:26 | 27/10 04:29 | – | 0 / 0 | 0 | 0 / 5 |
| #631 | 27/10 04:22 | 27/10 04:30 | tooling | 2 / 13 | 3 | 1 / 3 |
| #584 | 27/10 04:22 | 27/10 04:30 | engine | 3 / 30 | 1 | 1 / 4 |
| #616 | 27/10 04:24 | 27/10 04:31 | ui | 10 / 16 | 3 | 0 / 4 |
| #627 | 27/10 04:26 | 27/10 04:32 | engine, media, tooling | 3 / 82 | 15 | 0 / 5 |
| #638 | 27/10 04:30 | 27/10 04:32 | – | 0 / 0 | 0 | 0 / 4 |
| #578 | 27/10 04:19 | 27/10 04:34 | engine | 5 / 32 | 2 | 1 / 5 |
| #612 | 27/10 04:23 | 27/10 04:37 | engine | 2 / 30 | 1 | 0 / 4 |
| #630 | 27/10 04:30 | 27/10 04:38 | platform | 1 / 77 | 13 | 0 / 5 |
| #640 | 27/10 04:36 | 27/10 04:39 | – | 0 / 0 | 0 | 0 / 5 |
| #603 | 27/10 04:22 | 27/10 04:41 | app, tooling | 2 / 6 | 2 | 1 / 5 |
| #639 | 27/10 04:40 | 27/10 04:45 | – | 0 / 0 | 0 | 0 / 5 |
| #595 | 27/10 04:28 | 27/10 04:45 | engine | 4 / 30 | 1 | 1 / 4 |
| #648 | 27/10 04:44 | 27/10 04:47 | – | 0 / 0 | 0 | 0 / 5 |
| #598 | 27/10 04:22 | 27/10 04:49 | engine | 4 / 30 | 1 | 2 / 6 |
| #594 | 27/10 04:25 | 27/10 04:56 | engine | 3 / 30 | 1 | 1 / 1 |
| #650 | 27/10 04:55 | 27/10 05:03 | – | 0 / 0 | 0 | 0 / 5 |
| #604 | 27/10 04:54 | 27/10 05:10 | engine | 6 / 30 | 1 | 1 / 11 |
| #654 | 27/10 05:05 | 27/10 05:13 | release | 1 / 22 | 5 | 0 / 5 |
| #647 | 27/10 06:06 | 27/10 06:29 | engine | 2 / 30 | 1 | 0 / 5 |
| #661 | 27/10 05:17 | 27/10 06:35 | – | 0 / 0 | 0 | 0 / 5 |
| #664 | 27/10 05:59 | 27/10 06:37 | engine, tooling | 2 / 36 | 2 | 1 / 2 |
| #660 | 27/10 05:25 | 27/10 06:40 | tooling, ui | 2 / 13 | 3 | 0 / 6 |
| #646 | 27/10 04:56 | 27/10 06:42 | catalog, engine, tooling | 4 / 77 | 13 | 1 / 5 |
| #652 | 27/10 05:11 | 27/10 06:42 | tooling, ui | 2 / 16 | 3 | 1 / 5 |
| #655 | 27/10 04:57 | 27/10 06:59 | tooling, ui | 2 / 8 | 3 | 0 / 3 |
| #651 | 27/10 04:54 | 27/10 07:03 | tooling, ui | 2 / 8 | 3 | 0 / 5 |
| #658 | 27/10 06:47 | 27/10 07:21 | engine, site, tooling, ui | 4 / 44 | 5 | 0 / 6 |
| #634 | 27/10 04:36 | 27/10 08:01 | tooling | 2 / 9 | 3 | 1 / 3 |
| #657 | 27/10 06:34 | 27/10 08:22 | engine, release, tooling | 5 / 52 | 5 | 1 / 4 |
| #665 | 27/10 08:57 | 27/10 10:01 | engine | 6 / 30 | 1 | 0 / 6 |
| #637 | 27/10 05:08 | 27/10 10:24 | engine, tooling | 4 / 37 | 3 | 1 / 6 |
| #653 | 27/10 04:53 | 27/10 10:26 | tooling, ui | 2 / 13 | 3 | 0 / 4 |
| #691 | 27/10 11:03 | 27/10 11:07 | engine | 2 / 30 | 1 | 0 / 4 |
| #690 | 27/10 11:05 | 27/10 11:19 | engine | 5 / 30 | 1 | 1 / 10 |
| #692 | 27/10 14:02 | 27/10 14:13 | engine | 3 / 30 | 1 | 0 / 10 |
| #693 | 27/10 14:26 | 27/10 14:30 | engine | 1 / 30 | 1 | 0 / 3 |
| #694 | 27/10 14:42 | 27/10 14:48 | engine | 6 / 30 | 1 | 0 / 5 |
| #677 | 27/10 14:39 | 27/10 14:54 | engine | 6 / 30 | 1 | 0 / 5 |

## Model

| Parameter | Value | Source |
|---|---|---|
| T1 (tier-1 wall added to the last work commit) | 420 s | GA2 Q1 warm dev plan ≈ 7 min |
| D (tier-2 wall) | 600 s, and 240 s | GA2 Q1 cold 614 s; P-15 estimate 240 s |
| f (bad PR on the combined head) | 3 %, and 10 % | P-14 (3 % today); GA2 counts 3 ejections in 71 PRs on 27/10 |
| red streaks | two-state chain over ready order: calm 1 %, streak 35 %, mean streak 8 PRs (≈ 5 % average) | open Q7's question; no measured streak length exists |
| batch | 8 (`train.batch_size`), bisection ≤ `ceil(log2 n)` runs | `config/registry/train.json`, `train.bisection_runs` |
| fix delay of an ejected PR | 1800 s, then it comes back good | assumption |
| final tree check at the merge point (L) | 30 s per batch, serial | `train.merge` tree proof is two `git` reads |
| seeds | 300 per replay row, 40 per saturation row, 5 for the 2 982-PR rows | — |

Designs: **B0** today (one lock, serial bisection, a red batch merges nothing); **B1** GX-30 (the bisection's proven
prefix merges); **L(k)** lane-partitioned, k executors, batches in flight hold disjoint keys; **S(k)** speculative,
k batches in flight on predicted tips, a red batch cancels every batch behind it, bisection parallel over the k
executors; **adaptive**: the batch size halves after a red batch and doubles after a green one, between 1 and 8.

Key variants for L (keyed by **lane** unless the row says *by unit*, where the key is the unit ids instead): *aggregates in PRs* (every unclaimed file is a key: today), the default *generated* (generated
aggregates leave the PR diff, the train writes them: `train.publish_aggregates`; hand-edited shared files stay keys),
*lanes only* (hand-edited shared registries are also split per unit, D-B8 / GX-08 sidecars), *lanes only + dependents* (a PR also holds the lanes of every unit that `requires` a unit it touches, transitively: the safe key, since a change can break a dependent; under *lanes split* the dependents are taken inside the same copy, which is optimistic for kernel units every copy would share). *Lanes split with
volume*: a backlog of 14 copies of the day, each copy with its own lanes (P-23: a unit splits when hot), shared
files staying one file each.

Not modelled: flakes (the quarantine, M7, owns them), cross-lane semantic failures that no shard sees (the design's
confirm run, §4.3, owns them), forge refusals at merge, GitHub rate limits.

## Output (raw, as printed)

Makespan in the replay rows is set by the last arrival (the last PR became ready 14.9 h after the first) and barely
moves; wait and tier-2 runs are the replay's signal. PRs/h is the saturation throughput (backlog at t = 0).


#### 27/10 replay, D = 600 s, f = 3 %

| case | makespan h | mean wait min | p90 wait min | tier-2 runs | PRs/h |
|---|---|---|---|---|---|
| B0 today (batch 8) | 15.31 | 42.6 | 74.1 | 31 | – |
| B1 GX-30 prefix | 15.31 | 39.5 | 67.9 | 30 | – |
| L2 | 15.32 | 22.4 | 43.7 | 39 | – |
| L4 | 15.32 | 18.6 | 35.7 | 49 | – |
| L8 | 15.32 | 18.1 | 35.2 | 54 | – |
| L4, aggregates in PRs | 15.32 | 20.1 | 39.9 | 48 | – |
| L4, lanes only | 15.32 | 18.6 | 35.7 | 49 | – |
| L4, lanes only + dependents | 15.32 | 30.7 | 56.5 | 39 | – |
| L4, by unit | 15.32 | 17.3 | 32.8 | 50 | – |
| L4, by unit + dependents | 15.32 | 30.6 | 56.4 | 39 | – |
| L8, by unit + dependents | 15.32 | 30.6 | 56.4 | 39 | – |
| S2 | 15.20 | 23.5 | 40.7 | 40 | – |
| S4 | 15.20 | 18.3 | 30.8 | 53 | – |
| S8 | 15.20 | 14.1 | 21.2 | 67 | – |

#### 27/10 replay, D = 240 s, f = 3 %

| case | makespan h | mean wait min | p90 wait min | tier-2 runs | PRs/h |
|---|---|---|---|---|---|
| B0 today (batch 8) | 15.11 | 10.4 | 19.3 | 41 | – |
| B1 GX-30 prefix | 15.11 | 9.8 | 17.8 | 41 | – |
| L2 | 15.12 | 7.3 | 11.7 | 53 | – |
| L4 | 15.12 | 6.7 | 9.5 | 62 | – |
| L8 | 15.12 | 6.7 | 9.5 | 62 | – |
| L4, aggregates in PRs | 15.12 | 7.0 | 11.0 | 59 | – |
| L4, lanes only | 15.12 | 6.7 | 9.5 | 62 | – |
| L4, lanes only + dependents | 15.12 | 8.9 | 15.2 | 50 | – |
| L4, by unit | 15.12 | 6.4 | 8.8 | 64 | – |
| L4, by unit + dependents | 15.12 | 8.8 | 15.0 | 50 | – |
| L8, by unit + dependents | 15.12 | 8.8 | 15.0 | 50 | – |
| S2 | 15.09 | 6.8 | 11.0 | 52 | – |
| S4 | 15.09 | 5.6 | 7.2 | 65 | – |
| S8 | 15.09 | 5.2 | 5.3 | 75 | – |

#### 27/10 replay, D = 600 s, f = 10 %

| case | makespan h | mean wait min | p90 wait min | tier-2 runs | PRs/h |
|---|---|---|---|---|---|
| B0 today (batch 8) | 15.41 | 122.1 | 224.7 | 45 | – |
| B1 GX-30 prefix | 15.41 | 109.5 | 201.4 | 43 | – |
| L2 | 15.42 | 53.4 | 112.1 | 48 | – |
| L4 | 15.42 | 33.6 | 80.0 | 56 | – |
| L8 | 15.42 | 31.7 | 77.2 | 61 | – |
| L4, aggregates in PRs | 15.42 | 39.3 | 93.6 | 56 | – |
| L4, lanes only | 15.42 | 33.6 | 80.0 | 56 | – |
| L4, lanes only + dependents | 15.42 | 80.3 | 160.5 | 49 | – |
| L4, by unit | 15.42 | 31.2 | 73.6 | 57 | – |
| L4, by unit + dependents | 15.42 | 80.3 | 160.5 | 49 | – |
| L8, by unit + dependents | 15.42 | 80.3 | 160.5 | 49 | – |
| S2 | 15.32 | 67.9 | 124.3 | 57 | – |
| S4 | 15.31 | 58.2 | 109.7 | 85 | – |
| S8 | 15.31 | 35.0 | 65.7 | 94 | – |

#### Red streaks (calm 1 %, streak 35 %, mean 8 PRs), D = 600 s, 27/10 replay

| case | makespan h | mean wait min | p90 wait min | tier-2 runs | PRs/h |
|---|---|---|---|---|---|
| B1 fixed 8 | 15.34 | 53.1 | 96.7 | 33 | – |
| B1 fixed 4 | 15.33 | 65.7 | 118.8 | 35 | – |
| B1 fixed 2 | 15.33 | 114.9 | 215.0 | 46 | – |
| B1 adaptive 1-8 | 15.33 | 49.0 | 88.9 | 32 | – |
| B0 fixed 8 | 15.34 | 57.8 | 103.8 | 33 | – |
| B0 adaptive 1-8 | 15.34 | 56.1 | 102.1 | 33 | – |
| S4 fixed 8 | 15.22 | 29.5 | 54.5 | 61 | – |
| S4 adaptive 1-8 | 15.22 | 23.4 | 41.2 | 56 | – |
| L4 fixed 8 | 15.34 | 21.5 | 44.2 | 50 | – |
| L4 adaptive 1-8 | 15.34 | 20.9 | 41.6 | 50 | – |

#### Red streaks, saturation (backlog 14 x 27/10 = 994 PRs at t = 0), D = 600 s

| case | makespan h | mean wait min | p90 wait min | tier-2 runs | PRs/h |
|---|---|---|---|---|---|
| B1 fixed 8 | 47.81 | 1492.2 | 2684.2 | 287 | 21 |
| B1 fixed 4 | 61.21 | 1879.8 | 3381.2 | 367 | 16 |
| B1 fixed 2 | 95.93 | 2907.7 | 5230.5 | 576 | 10 |
| B1 adaptive 1-8 | 45.14 | 1395.5 | 2523.0 | 271 | 23 |
| B0 fixed 8 | 49.77 | 1555.6 | 2787.0 | 299 | 21 |
| B0 adaptive 1-8 | 49.48 | 1535.9 | 2775.8 | 297 | 21 |
| S4 fixed 8 | 25.61 | 808.5 | 1451.2 | 635 | 42 |
| S4 adaptive 1-8 | 21.51 | 672.4 | 1214.8 | 508 | 48 |
| L4 fixed 8 | 27.05 | 619.0 | 1389.5 | 289 | 38 |
| L4 adaptive 1-8 | 26.63 | 609.5 | 1367.2 | 291 | 38 |

#### Saturation, backlog 994 PRs (1k/day), f = 3 %, D = 600 s, 27/10 lane mix

| case | makespan h | mean wait min | p90 wait min | tier-2 runs | PRs/h |
|---|---|---|---|---|---|
| B0 today (batch 8) | 41.60 | 1271.3 | 2278.0 | 250 | 24 |
| B1 GX-30 prefix | 39.45 | 1205.1 | 2166.8 | 237 | 25 |
| L2 | 23.67 | 632.3 | 1201.0 | 239 | 42 |
| L4 | 22.97 | 517.6 | 1152.0 | 241 | 44 |
| L8 | 22.96 | 513.8 | 1151.8 | 242 | 44 |
| L4, aggregates in PRs | 25.55 | 575.4 | 1311.8 | 241 | 39 |
| L4, lanes only | 22.87 | 511.9 | 1145.0 | 240 | 44 |
| L4, lanes only + dependents | 31.09 | 825.1 | 1655.5 | 239 | 32 |
| L4, by unit | 18.47 | 401.8 | 898.6 | 242 | 54 |
| L4, by unit + dependents | 30.76 | 819.0 | 1639.8 | 239 | 33 |
| L8, by unit + dependents | 30.76 | 815.7 | 1639.8 | 239 | 33 |
| S2 | 23.94 | 732.3 | 1315.8 | 299 | 42 |
| S4 | 19.13 | 582.4 | 1046.0 | 487 | 53 |
| S8 | 11.78 | 353.3 | 631.8 | 579 | 86 |

#### Saturation, backlog 994 PRs (1k/day), f = 3 %, D = 600 s, lanes split with volume (P-23)

| case | makespan h | mean wait min | p90 wait min | tier-2 runs | PRs/h |
|---|---|---|---|---|---|
| B0 today (batch 8) | 41.60 | 1271.3 | 2278.0 | 250 | 24 |
| B1 GX-30 prefix | 39.45 | 1205.1 | 2166.8 | 237 | 25 |
| L2 | 20.24 | 603.7 | 1084.2 | 238 | 49 |
| L4 | 11.37 | 304.5 | 539.9 | 241 | 88 |
| L8 | 9.39 | 179.4 | 370.7 | 246 | 108 |
| L4, aggregates in PRs | 15.46 | 337.2 | 704.3 | 241 | 65 |
| L4, lanes only | 11.03 | 303.7 | 539.2 | 239 | 91 |
| L4, lanes only + dependents | 11.25 | 305.2 | 541.1 | 240 | 89 |
| L4, by unit | 11.32 | 304.2 | 541.0 | 240 | 88 |
| L4, by unit + dependents | 11.25 | 305.2 | 541.4 | 240 | 89 |
| L8, by unit + dependents | 6.91 | 157.3 | 286.7 | 242 | 146 |
| S2 | 23.94 | 732.3 | 1315.8 | 299 | 42 |
| S4 | 19.13 | 582.4 | 1046.0 | 487 | 53 |
| S8 | 11.78 | 353.3 | 631.8 | 579 | 86 |

#### Saturation, backlog 994 PRs, f = 3 %, D = 600 s, lanes split, S x L

| case | makespan h | mean wait min | p90 wait min | tier-2 runs | PRs/h |
|---|---|---|---|---|---|
| S8 | 11.78 | 353.3 | 631.8 | 579 | 86 |
| S16 | 11.12 | 333.6 | 594.0 | 814 | 91 |
| L16 | 9.18 | 174.8 | 363.7 | 248 | 111 |
| L16, lanes only | 4.70 | 86.0 | 164.1 | 245 | 216 |
| L32, lanes only | 3.84 | 60.7 | 124.2 | 244 | 265 |
| L16, lanes only + dependents | 4.81 | 89.7 | 174.0 | 245 | 210 |

#### Saturation, backlog 2982 PRs (42 x 27/10), f = 3 %, D = 600 s, lanes split, shared files split

| case | makespan h | mean wait min | p90 wait min | tier-2 runs | PRs/h |
|---|---|---|---|---|---|
| L16, lanes only | 9.68 | 229.9 | 404.2 | 717 | 310 |
| L32, lanes only | 6.34 | 124.2 | 217.8 | 719 | 472 |
| L64, lanes only | 4.58 | 112.9 | 199.0 | 718 | 661 |

#### Saturation, backlog 994 PRs, f = 3 %, D = 240 s (P-15), lanes split

| case | makespan h | mean wait min | p90 wait min | tier-2 runs | PRs/h |
|---|---|---|---|---|---|
| B0 today (batch 8) | 16.73 | 508.5 | 911.2 | 250 | 60 |
| B1 GX-30 prefix | 15.89 | 482.1 | 866.7 | 237 | 63 |
| L2 | 8.37 | 241.9 | 434.1 | 239 | 120 |
| L4 | 4.81 | 122.4 | 216.6 | 243 | 209 |
| L8 | 4.00 | 72.8 | 149.4 | 251 | 254 |
| L4, aggregates in PRs | 6.39 | 135.5 | 282.0 | 243 | 158 |
| L4, lanes only | 4.70 | 122.1 | 216.2 | 242 | 213 |
| L4, lanes only + dependents | 4.78 | 122.7 | 217.1 | 242 | 210 |
| L4, by unit | 4.81 | 122.3 | 217.0 | 243 | 208 |
| L4, by unit + dependents | 4.78 | 122.7 | 217.1 | 242 | 210 |
| L8, by unit + dependents | 3.06 | 64.0 | 115.9 | 247 | 329 |
| S2 | 9.84 | 292.9 | 526.3 | 300 | 102 |
| S4 | 7.95 | 233.0 | 418.4 | 488 | 127 |
| S8 | 5.01 | 141.4 | 252.7 | 581 | 202 |

## Source

```python
"""GX-34 tier-2 simulator: today's train, GX-30, lane-partitioned (L) and speculative (S) executors, adaptive batch.

    python3 sim.py extract merges.json   # from a checkout of the-tower (reads git and units/*/unit.json)
    python3 sim.py run merges.json       # prints every table of the design doc

Model (one line each; the design doc states why):
- A PR is ready at its last non-merge commit + T1 (a tier-1 gate wall). It is bad with probability f (i.i.d.) or
  from a two-state red-streak chain over ready order. A bad PR is ejected and comes back good FIX_S later.
- A tier-2 run takes D seconds; a batch is red iff it holds a bad PR (flakes are left to the quarantine).
- Bisection finds the first bad member: serial ceil(log2 n) runs (today), or parallel over free executors.
- B0 today: nothing merges from a red batch. B1 (GX-30): the proven prefix before the culprit merges.
- L(k): k executors; batches in flight hold disjoint partition keys; a green batch merges through one merge point
  after a cheap final tree check (CHECK_S). S(k): up to k batches in flight, each on the predicted tip of those ahead;
  a red batch cancels every batch behind it.
"""
import heapq, json, math, random, statistics, subprocess, sys

T1, FIX_S, CHECK_S, SEEDS = 420, 1800, 30, 300
GENERATED = ('CODEOWNERS', 'apps/web/tsconfig.json', 'scripts/lib/generated/', 'contracts/generated/',
             'apps/web/src/generated/')


def extract(out):
    sys.path.insert(0, 'scripts/lib')
    import glob
    from gate_areas import glob_match

    def git(*a):
        return subprocess.run(['git', *a], capture_output=True, text=True, check=True).stdout

    manifests = [json.load(open(p)) for p in sorted(glob.glob('units/*/unit.json'))]
    log = git('log', '--merges', '--first-parent', 'origin/mod/roadmap-integration', '--since=2026-10-27T03:00:00Z',
              '--until=2026-10-28T03:00:00Z', '--format=%H %ct %s').splitlines()
    rows = []
    for line in reversed(log):
        sha, ct, subject = line.split(' ', 2)
        base, head = git('rev-list', '--parents', '-n1', sha).split()[1:3]
        files = [f for f in git('diff', '--no-renames', '--name-only', base, sha).splitlines() if f]
        lanes, shared, units = set(), set(), set()
        for f in files:
            hit = next((m for m in manifests if any(glob_match(f, g) for g in m.get('paths', []))), None)
            if hit:
                lanes.add(hit.get('lane', hit.get('owner')))
                units.add(hit['id'])
            else:
                shared.add(f)
        dependents, frontier = set(), set(units)  # every unit that requires a touched unit, transitively
        while frontier:
            frontier = {m['id'] for m in manifests if set(m.get('requires') or {}) & frontier} - dependents - units
            dependents |= frontier
        closure = lanes | {m.get('lane', m.get('owner')) for m in manifests if m['id'] in dependents}
        work = git('log', '-1', '--no-merges', '--format=%ct', f'{base}..{head}').strip() or git('log', '-1', '--format=%ct', head)
        rows.append(dict(pr=int(subject.split('#')[1].split()[0].rstrip(')')), merged_at=int(ct), work_at=int(work),
                         lanes=sorted(lanes), closure=sorted(closure), units=sorted(units),
                         unit_closure=sorted(units | dependents), shared=sorted(shared)))
    json.dump(rows, open(out, 'w'), indent=0)


def keys(row, variant, copy=0, split=False, by='lanes'):
    field = {'lanes': 'lanes', 'closure': 'closure', 'units': 'units', 'unit_closure': 'unit_closure'}[
        by if variant != 'closure' else ('closure' if by == 'lanes' else 'unit_closure')]
    lanes = {f'{key}#{copy}' if split else key for key in row[field]}
    shared = {f for f in row['shared'] if variant == 'today' or not f.startswith(GENERATED)}
    if variant in ('lanes', 'closure'):
        shared = set()
    return frozenset(lanes | shared)  # a shared file is one file at any volume; only units split (P-23)


def badness(n, rng, f, streak):
    if not streak:
        return [rng.random() < f for _ in range(n)]
    out, hot = [], False  # calm 1 %, streak 35 %, mean streak 8 PRs, enter so the average is about 5 %
    for _ in range(n):
        hot = rng.random() < (1 - 1 / 8) if hot else rng.random() < 0.0125
        out.append(rng.random() < (0.35 if hot else 0.01))
    return out


class PR:
    __slots__ = ('id', 'ready', 'keys', 'bad', 'first_ready', 'merged')

    def __init__(self, i, ready, keys, bad):
        self.id, self.ready, self.first_ready, self.keys, self.bad, self.merged = i, ready, ready, keys, bad, None


def bisect_rounds(n, parallel):
    """Tier-2 runs on the critical path and runs spent to find the first bad member of a red batch of n."""
    if n <= 1:
        return 0, 0
    if parallel >= n - 1:
        return 1, n - 1
    rounds = math.ceil(math.log(n) / math.log(parallel + 1))
    return rounds, rounds * parallel


class Sim:
    def __init__(self, prs, D, batch, adaptive=False, prefix=True):
        self.prs, self.D, self.batch, self.adaptive, self.prefix = prs, D, batch, adaptive, prefix
        self.size, self.runs, self.t = batch, 0, 0.0
        self.waiting = sorted(prs, key=lambda p: (p.ready, p.id))

    def ready_now(self, t, exclude=()):
        return [p for p in self.waiting if p.ready <= t and p not in exclude]

    def next_arrival(self, t):
        return min((p.ready for p in self.waiting if p.ready > t), default=None)

    def resolve(self, members, t_end, parallel, timed=True):
        """Outcome of a finished tier-2 run on members: (merged, end time). Bad members leave and come back fixed.
        timed=False: the caller already put the bisection in t_end."""
        culprit = next((i for i, p in enumerate(members) if p.bad), None)
        if culprit is None:
            self.grow()
            return members, t_end
        self.shrink()
        rounds, spent = bisect_rounds(len(members), parallel)
        self.runs += spent
        t_end += rounds * self.D if timed else 0
        bad = members[culprit]
        self.waiting.remove(bad)
        bad.bad, bad.ready = False, t_end + FIX_S
        self.waiting.append(bad)
        self.waiting.sort(key=lambda p: (p.ready, p.id))
        return (members[:culprit] if self.prefix else []), t_end

    def grow(self):
        if self.adaptive:
            self.size = min(self.batch, self.size * 2)

    def shrink(self):
        if self.adaptive:
            self.size = max(1, self.size // 2)

    def done(self, members, t):
        for p in members:
            p.merged = t
            self.waiting.remove(p)

    def single(self):
        """B0/B1: one lock, one executor, serial bisection (train.py today; B1 is GX-30's proven prefix)."""
        t = 0.0
        while self.waiting:
            ready = self.ready_now(t)
            if not ready:
                t = self.next_arrival(t)
                continue
            members = ready[:self.size]
            self.runs += 1
            merged, t = self.resolve(members, t + self.D, parallel=1)
            self.done(merged, t)
        return t

    def lanes(self, k):
        """L(k): k executors, disjoint keys in flight, one merge point with a cheap final tree check."""
        t, free, inflight, merge_free = 0.0, k, [], 0.0  # inflight: heap of (end, seq, members, keys)
        seq, locked = 0, set()
        while self.waiting or inflight:
            while inflight and inflight[0][0] <= t:
                end, _, members, held = heapq.heappop(inflight)
                merged, end = self.resolve(members, end, parallel=1, timed=False)
                if merged:
                    merge_free = max(end, merge_free) + CHECK_S
                    self.done(merged, merge_free)
                locked -= held
                free += 1
            busy = {p for _, _, members, _ in inflight for p in members}
            while free:
                members, held = [], set()
                for p in self.ready_now(t, busy):
                    if len(members) == self.size:
                        break
                    if not (p.keys & locked):
                        members.append(p)
                        held |= p.keys
                if not members:
                    break
                self.runs += 1
                seq += 1
                locked |= held
                busy |= set(members)
                # the end includes bisection: the outcome is drawn up front, so the executor stays busy for it
                culprit = next((i for i, p in enumerate(members) if p.bad), None)
                extra = bisect_rounds(len(members), 1)[0] * self.D if culprit is not None else 0
                heapq.heappush(inflight, (t + self.D + extra, seq, members, frozenset(held)))
                free -= 1
            nexts = [x for x in (inflight[0][0] if inflight else None, self.next_arrival(t)) if x is not None]
            if not nexts:
                if self.waiting:  # every waiting PR is ready but blocked by nothing: impossible; guard
                    raise RuntimeError('stuck')
                break
            t = min(nexts)
        return max([p.merged for p in self.prs])

    def speculative(self, k):
        """S(k): up to k batches in flight on predicted tips; a red batch cancels those behind it; bisection is
        parallel over the k executors."""
        t, inflight = 0.0, []  # inflight: list of (end, members), in merge order
        while self.waiting:
            busy = {p for _, members in inflight for p in members}
            while len(inflight) < k:
                ready = self.ready_now(t, busy)
                if not ready:
                    break
                members = ready[:self.size]
                inflight.append((t + self.D, members))
                busy |= set(members)
                self.runs += 1
            if not inflight:
                t = self.next_arrival(t)
                continue
            arrival = self.next_arrival(t) if len(inflight) < k else None
            head_end = inflight[0][0]
            if arrival is not None and arrival < head_end:
                t = arrival
                continue
            t = head_end
            end, members = inflight.pop(0)
            if any(p.bad for p in members):
                inflight.clear()  # every batch behind a red one was built on a tip that will not exist
                # runs already spent on cancelled batches stay counted: that is the speculation's waste
            merged, t = self.resolve(members, t, parallel=k)
            self.done(merged, t)
        return t


def scenario(rows, design, k=1, D=600, batch=8, f=0.03, streak=False, variant='generated', adaptive=False,
             backlog=None, split=False, by='lanes', seeds=SEEDS):
    out = []
    for seed in range(seeds):
        rng = random.Random(seed)
        copies = backlog or 1
        n = len(rows) * copies
        bad = badness(n, rng, f, streak)
        prs = []
        start = min(r['work_at'] for r in rows)
        for c in range(copies):
            for i, r in enumerate(rows):
                ready = 0.0 if backlog else r['work_at'] - start + T1
                prs.append(PR(c * len(rows) + i, ready, keys(r, variant, c, split, by), False))
        prs.sort(key=lambda p: (p.ready, p.id))
        for p, b in zip(prs, bad):
            p.bad = b
        sim = Sim(prs, D, batch, adaptive=adaptive, prefix=(design != 'B0'))
        if design in ('B0', 'B1'):
            span = sim.single()
        elif design == 'L':
            span = sim.lanes(k)
        else:
            span = sim.speculative(k)
        waits = [p.merged - p.first_ready for p in prs]
        out.append(dict(span=span, wait=statistics.mean(waits), p90=sorted(waits)[int(0.9 * len(waits))],
                        runs=sim.runs, rate=len(prs) / (span / 3600) if backlog else None))
    avg = {key: statistics.mean(o[key] for o in out) for key in ('span', 'wait', 'p90', 'runs')}
    if backlog:
        avg['rate'] = statistics.mean(o['rate'] for o in out)
    return avg


def table(title, rows, cases):
    print(f'\n### {title}\n')
    print('| case | makespan h | mean wait min | p90 wait min | tier-2 runs | PRs/h |')
    print('|---|---|---|---|---|---|')
    for name, kw in cases:
        r = scenario(rows, **kw)
        rate = f"{r['rate']:.0f}" if 'rate' in r else '–'
        print(f"| {name} | {r['span'] / 3600:.2f} | {r['wait'] / 60:.1f} | {r['p90'] / 60:.1f} | {r['runs']:.0f} | {rate} |")


def run(path):
    rows = json.load(open(path))
    first = min(r['work_at'] for r in rows)
    print(f'{len(rows)} PRs; first ready at work_at+T1; span of work_at {(max(r["work_at"] for r in rows) - first) / 3600:.1f} h')
    designs = [('B0 today (batch 8)', dict(design='B0')), ('B1 GX-30 prefix', dict(design='B1')),
               ('L2', dict(design='L', k=2)), ('L4', dict(design='L', k=4)), ('L8', dict(design='L', k=8)),
               ('L4, aggregates in PRs', dict(design='L', k=4, variant='today')),
               ('L4, lanes only', dict(design='L', k=4, variant='lanes')),
               ('L4, lanes only + dependents', dict(design='L', k=4, variant='closure')),
               ('L4, by unit', dict(design='L', k=4, by='units')),
               ('L4, by unit + dependents', dict(design='L', k=4, by='units', variant='closure')),
               ('L8, by unit + dependents', dict(design='L', k=8, by='units', variant='closure')),
               ('S2', dict(design='S', k=2)), ('S4', dict(design='S', k=4)), ('S8', dict(design='S', k=8))]
    for D in (600, 240):
        table(f'27/10 replay, D = {D} s, f = 3 %', rows, [(n, dict(kw, D=D)) for n, kw in designs])
    table('27/10 replay, D = 600 s, f = 10 %', rows, [(n, dict(kw, f=0.10)) for n, kw in designs])
    sizes = [('B1 fixed 8', dict(design='B1')), ('B1 fixed 4', dict(design='B1', batch=4)),
             ('B1 fixed 2', dict(design='B1', batch=2)), ('B1 adaptive 1-8', dict(design='B1', adaptive=True)),
             ('B0 fixed 8', dict(design='B0')), ('B0 adaptive 1-8', dict(design='B0', adaptive=True)),
             ('S4 fixed 8', dict(design='S', k=4)), ('S4 adaptive 1-8', dict(design='S', k=4, adaptive=True)),
             ('L4 fixed 8', dict(design='L', k=4)), ('L4 adaptive 1-8', dict(design='L', k=4, adaptive=True))]
    table('Red streaks (calm 1 %, streak 35 %, mean 8 PRs), D = 600 s, 27/10 replay', rows,
          [(n, dict(kw, streak=True)) for n, kw in sizes])
    table('Red streaks, saturation (backlog 14 x 27/10 = 994 PRs at t = 0), D = 600 s', rows,
          [(n, dict(kw, streak=True, backlog=14, seeds=40)) for n, kw in sizes])
    for split in (False, True):
        scale = 'lanes split with volume (P-23)' if split else '27/10 lane mix'
        table(f'Saturation, backlog 994 PRs (1k/day), f = 3 %, D = 600 s, {scale}', rows,
              [(n, dict(kw, backlog=14, split=split, seeds=40)) for n, kw in designs])
    table('Saturation, backlog 994 PRs, f = 3 %, D = 600 s, lanes split, S x L', rows,
          [('S8', dict(design='S', k=8, backlog=14, split=True, seeds=40)),
           ('S16', dict(design='S', k=16, backlog=14, split=True, seeds=40)),
           ('L16', dict(design='L', k=16, backlog=14, split=True, seeds=40)),
           ('L16, lanes only', dict(design='L', k=16, backlog=14, split=True, variant='lanes', seeds=40)),
           ('L32, lanes only', dict(design='L', k=32, backlog=14, split=True, variant='lanes', seeds=40)),
           ('L16, lanes only + dependents', dict(design='L', k=16, backlog=14, split=True, variant='closure', seeds=40))])
    table('Saturation, backlog 2982 PRs (42 x 27/10), f = 3 %, D = 600 s, lanes split, shared files split', rows,
          [(f'L{k}, lanes only', dict(design='L', k=k, backlog=42, split=True, variant='lanes', seeds=5))
           for k in (16, 32, 64)])
    table('Saturation, backlog 994 PRs, f = 3 %, D = 240 s (P-15), lanes split', rows,
          [(n, dict(kw, D=240, backlog=14, split=True, seeds=40)) for n, kw in designs])


if __name__ == '__main__':
    {'extract': extract, 'run': run}[sys.argv[1]](sys.argv[2])
```
