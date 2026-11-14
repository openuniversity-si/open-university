# GATE-GC-CHEIO — audit: a retention bound per key is not a bound on the folder

## The stop

28/10 17:00 on the box (`/workspace/torre/the-tower`): `git fetch` failed with `No space left on device` while `df`
showed 40 GB free. `df -i` showed the inode table full:

    2,009,145 of 2,031,616 inodes used (99%)

The ceiling was the number of files, not their size. The train stopped three times that day for it, and each stop
looked like a transport fault.

## Where the inodes were

Measured on the box by Daniel, 17:32, with `du -s --inodes <dir>` (numbers quoted from the brief):

| `du -s --inodes` | inodes |
|---|---|
| `/workspace/torre/the-tower/.gate/records/reports` | 198,038 |
| `/workspace/torre/the-tower/.gate/report-only/reports` | 64,659 |
| `.gate` entire | 262,710 |
| `.git` entire | 5,236 |

40 shas under `records/reports` (1.5 GB), 14 under `report-only/reports` (475 MB); about 3,300 files per gate run (one
log per test, per stage). The palliative on the box (keep the 12 newest shas per folder) freed 155,000 inodes, 95% → 87%.

**Re-measurement.** This unit runs in a Claude Code cloud container; `/workspace/torre` does not exist here
(`ls -d /workspace/torre` → `No such file or directory`), so the box's table cannot be re-measured from this session.
What this session can measure, it measured:

| command | output |
|---|---|
| `df -i /` (20:36Z) | `/dev/vda 16777216 226480 16550736 2% /` |
| `du -s --inodes .gate` before any gate ran | `.gate: No such file or directory` |
| `du -s --inodes .git` | `54` (a fresh shallow clone) |

The files one gate run writes here are measured in [plan.md](plan.md) step 6 / [retro.md](retro.md) after this
unit's own gate runs, with the command beside the number.

## The code path that grew

`scripts/lib/gate_gc.py:46-59`, `collect_reports` (head of `mod/roadmap-integration` at `1de1fc2b`):

```python
    for sha_dir in (p for p in reports.iterdir() if p.is_dir() and SHA.match(p.name)):   # :50
        by_mode = {}
        ...
        for runs in by_mode.values():                                                     # :56
            for run in _newest(runs, keep):                                               # :57
                _remove(run, removed)
```

It keeps the newest `gate-gc.reports_keep` (3, `config/registry/gate-gc.json:90`) runs of each (sha, mode) and removes
the rest. It never removes a sha directory. Every push creates a new sha, and a gate run writes
`$record_dir/reports/<sha>/<mode>-<timestamp>` (`scripts/gate-local:280`), so the number of sha directories grows by one
per gated head, without ceiling. The bound is per key; the set of keys is unbounded. A bound inside an unbounded set is
not a bound.

The collection runs from the gate's exit hook, `scripts/lib/gate-hooks/exit.sh:8`, on `"${record_dir}/reports"`. The
report-only (advisory) run has its own record dir, `<root>/.gate/report-only` (`scripts/gate-local:112`,
`scripts/lib/gate_pin.py:39,307`), so the same per-key bound and the same growth apply there.

GX-19's own plan promised the folder bound: "Observable: … report directories stop growing past the bound"
(`docs/programs/gate-excellence/plan.md:324`). The test it shipped (`test_reports_keep_the_newest_per_sha_and_mode`)
proves the per-key bound only; nothing tested the folder.

## The two decisions this change must respect

- **D-070 — bound what grows.** The gate-excellence program (D-070) owns gate hygiene; GX-19 (`plan.md:323`) implements
  F-08 "hygiene" under it, and the done line is "report directories bounded" (`plan.md:526`). A bound that does not
  bound the folder does not meet it. D-070 is also the D-NNN this gate change cites for D-025's gate-change rule.
- **D-069 item 4 — a verdict must be reproducible.** "(4) The event log is append-only; events are versioned and
  idempotent; every engine state is rebuildable by replay." Applied here: pruning must never remove the evidence of a
  run whose verdict is still being explained — the run a live gate is writing, the sha a live process holds, and the
  history the readers of `reports/*/*/` rely on (answered below, step 3).

## Constraints carried

Hygiene never changes a verdict: `exit.sh:8` ends in `>/dev/null 2>&1 || true`, and stays that way. No production
change (D-054). Merge commits only; this unit never merges its own PR.

## Step 3 — how long an old run stays diagnosable, and who reads `reports/*/*/`

**What reads `reports/*/*/` today** (`rg -n "reports" scripts/lib scripts/gate-*`, readers only):

| reader | what it reads | history it needs |
|---|---|---|
| `scripts/lib/gate_status.py:99-112` `history` | the `stages.json` of the newest `gate.status_history_runs` (5) runs across `reports/*/*/`, for the ETA medians | 5 runs |
| `scripts/lib/gate_explain.py:136-138` `latest` (`gate-dev --why` with no path) | the newest run | 1 run |
| `scripts/lib/gate_explain.py:141` `why(logs)` (`gate-dev --why <path>`) | any run a person names, by path | the run being explained |
| `scripts/gate-batch:34-36` | its own run's report, right after the gate exits (`Gate reports:` line) | its own sha, the newest |
| `scripts/lib/battery.py:116`, `scripts/lib/gate_noite.py:115` | their own run's `GATE_REPORT_DIR` | their own sha |
| `.gate/report-only/reports` | no program; the advisory verdict is posted on the PR by `gate_pin.py:316-337` | the head being explained |

**What the bound could break, and what changed for it.** `history` needs 5 runs; every kept sha holds at least one,
so `gate-gc.reports_shas_keep ≥ gate.status_history_runs` is enough, and
`test_the_folder_bound_keeps_what_the_readers_need` holds that. `latest`, `gate-batch`, the battery and the nightly read
their own, newest run, which is also the `--live-sha` the exit hook protects. The one reader the bound can break is
`why(<path>)` on an old run: before this change it would have said "no stages.json … (the run did not reach its
report)" — a false account of a verdict. It now says the run is gone, names `gate-gc.reports_shas_keep` and says how to
rebuild it (rerun the gate on that sha; D-069 item 4: the state is rebuildable, the verdict is also on the PR's status
comment and in the event log).

**The keys, set from the need, not from a guess.** A verdict is "still being explained" while the train holds its PR.
The train takes `train.batch_size` (8) PRs per batch and calls its queue growing past `train.queue_growing_batches` (2)
batches (`config/registry/train.json`); a red verdict older than that has already raised `train.queue.growing` and comes
back with a new sha. So:

- `gate-gc.reports_shas_keep = 16` = 8 × 2, the two batches the train holds; ≥ 5, the history reader's floor.
- `gate-gc.report_only_shas_keep = 8` = one batch: the advisory folder has no program reader, its verdict is already on
  the PR, and its logs are read only by the session of a gate-change PR in the batch being judged.

Both carry `review by 2026-11-28` in `x-source` (the registry's meta-schema, `contracts/config/registry.v1.json`,
allows no `review_by` field — `additionalProperties: false` — and `gate-gc.reports_keep` has none).

**How long a diagnostic of an old run stays possible.** A run stays until 16 newer shas are gated into the same folder
(8 for the advisory folder), and at most `gate-gc.reports_keep` (3) runs per (sha, mode) inside each. In wall time it
depends on how many heads one box gates. Measured on the base (`git log --merges --first-parent 1de1fc2b
--since=2026-10-28T00:00:00Z | wc -l` → **58** merges between 00Z and 19Z, each with at least one green gate on its exact
head; `git log --no-merges 1de1fc2b --since=2026-10-28T00:00:00Z | wc -l` → **336** commits, each pushed alone, so 336
heads): at the merge rate (~2.9 shas/h) a run stays ≈ 5.5 h; if one box gated every pushed head (~16.8/h), ≈ 1 h. Past
that, the verdict lives in the PR status comment and the event log, and the report is rebuilt by rerunning the gate on
the sha.

**Inode cost of the bound**, from the box's own averages (198,038 inodes / 40 shas ≈ 4,951 per sha in records; 64,659 /
14 ≈ 4,619 in report-only): 16 × 4,951 + 8 × 4,619 ≈ 116,000 inodes, about 5.7% of the box's 2,031,616, against the
262,710 of 17:32 — and, unlike it, constant.

**The lock.** `scripts/gate-local:155-157` opens the lock with `exec 9>"$lock"` (truncating) and takes `flock`; nothing
writes a sha into it, and a waiter's open would truncate one anyway. So today `gate.lock` names no sha. The collection
still honours a held lock that names one (flock probe; a lock nobody holds protects nothing), and the running gate's own
sha is protected by `--live-sha` from the exit hook, which runs while the gate still holds the lock.

## Step 6 — the same shape elsewhere

**One gate run's files, measured here** (this unit's first gate-dev, head `bf0c51c0`, 21:01Z):

| command | output |
|---|---|
| `find .gate/records/reports/bf0c51c0…/dev-20261028T210132 -type f \| wc -l` | **3,288** files |
| `du -s --inodes .gate/records/reports/bf0c51c0…/dev-20261028T210132` | **3,821** inodes (files + directories) |

So the brief's "about 3,300 files per run" holds on a second machine.

**Top 10 by inodes in this container** (`du -s --inodes ./* ./.[a-z]* /tmp/* | sort -rn | head -10`, 21:08Z, after
one gate run):

| inodes | path | bounded? |
|---|---|---|
| 32,636 | `./apps` (`node_modules`) | fixed by the lockfile; does not grow per push |
| 24,282 | `./.toolchain` | fixed by the manifest; one install per pinned version |
| 3,899 | `/tmp/tower-gate-pin` | yes, on the folder: `gate_pin.evict` keeps `gate-pin.keep_worktrees` base shas (`gate_pin.py:225`) |
| 3,826 | `./.gate` | **this unit**: one run so far, now bounded by `gate-gc.reports_shas_keep` |
| 1,682 | `./.git` | grows with history, packed by git |
| 1,363 | `/tmp/node-compile-cache` | Node's own cache, keyed by source; not the gate's |
| 1,027 | `./scripts` | tracked files |
| 906 | `./docs` | tracked files |
| 242 | `./units` | tracked files |
| 223 | `/tmp/tmp3mm8tfq1` | a test's temp dir |

**The same unbounded-folder shape, by code** (not measurable here, nothing wrote them in this container):

- `.gate/evidence/pr-<n>-<time>-<uuid>/` (`scripts/lib/ship_verify.py:100`): one directory per `ship-verify` run, never
  removed. Frozen with production (D-054), so it does not grow today; it will when the release pipeline (roadmap step 8)
  runs it. Not fixed here.
- `/workspace/torre` on the box: not reachable from this session; the box's own top 10 needs the same
  `du -s --inodes` there.

Fixed here: only `.gate/records/reports` and `.gate/report-only/reports`.
