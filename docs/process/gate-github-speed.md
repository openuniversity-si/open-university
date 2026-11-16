# tower/gate on GitHub: where the time goes, and the cuts to p99 ≤ 60 s

Measured 14/11/2026 on the 39 `tower-gate` runs of the repository's first day (22 `pull_request`, 17 `merge_group`),
from the jobs' step times and logs, plus PR #19's run 43606632818 (attempt 1 red, attempt 2 green in 223 s). Each run's plan was recomputed on its
exact commit (`gate_infra.py plan`, an empty test store) and matched the job's check count in all 35 green runs.

| step (s) | p50 | p90 | p99 = max |
|---|---|---|---|
| wait for a runner | 2 | 3 | 6 |
| set up job + checkout (`fetch-depth: 0`) | 2 | 3 | 7 |
| cache restore (`.toolchain`) | 1 | 4 | 5 |
| toolchain (`setup.sh`): 7 s on a miss (34 runs), 1 s on a hit (5) | 7 | 8 | 9 |
| verify: plan + stages (the runs with no test) | ≈ 10 | ≈ 11 | ≈ 12 |
| verify: the tests' batch and the reruns alone | ≈ 17 | ≈ 233 | ≈ 465 |
| cache save (post, only on a miss) | 3 | 4 | 14 |
| **job** | **44** | **254** | **490** |

**Why the tail is slow.** Not the setup: the steps before verify sum to about 12 s at p90. The tail is the tests: a
run's verify time follows the cold cost of its plan's tests (`scripts/tests/costs.json`) divided by the 4 vCPUs, and
never drops below its longest test. Every run over 60 s planned 12 to 84 tests with a cost of 123-951 s, or one of
`deploy-slow-a/b/c` (110 s each), `gate-infra` (55 s), `infra-runner` (44 s), `infra-pooler` (40 s). Reruns alone add to
it: `infra-intask-standby` (37 s) in 5 runs, and in the 476 s run `deploy-slow-a/b/c` reran one after another (~330 s).
And **every merge-queue run judged again what its pull request's run had judged**. All 17 queue commits had the same
tree and the same parents as the pull request's merge commit, judged green against the same base (max one entry per
queue build). That doubled the slow tail: 153, 161, 260 and 490 s on the queue. **A red, not a slow run:** the toolchain
cache carried the PostgreSQL cluster (`.toolchain/pgdata`), saved while its server was running. On a fresh runner the
restored `postmaster.pid` named a pid that could be alive there, so `setup.sh` failed with "postgres is not accepting
connections". 1 of the 7 runs that restored the cache was red this way (its rerun on another runner was green).

**The cuts.**

| cut | saving | risk | here? |
|---|---|---|---|
| (b) the queue reuses the tests' green verdict of an exact duplicate | the whole tests' time of a queue run: 17/17 hits measured, every queue run ≈ 20-30 s | a reuse under a weaker key: see below | **done** |
| (a) cache the toolchain's binaries only (`!.toolchain/pgdata`, log, socket, home; key `toolchain-bin-`), and `postgres.py` makes afresh a cluster whose server started before this boot | the red above. A hit then runs `initdb` (between the 1 s of a hit and the 7 s of a miss) | none: the cluster holds throwaway test data | **done** |
| (c) a shallow checkout | ≤ 2 s | the plan's diff and the history secret scan need the history | no |
| (e) more tests at once on the 4 vCPUs | none: the batch is CPU-bound (wall ≈ cost / 4) | starves the timing-bound tests (`infra-intask-standby`'s 20 s waits, 13/11) | no |
| (e') shard the planned tests over N jobs (longest first by `costs.json`) behind an aggregator job named `tower/gate`, with `if: always()` and red unless every shard is green | a run's tests ≈ max(longest test, cost / 4N): 238 s → ~60 s for 84 tests with N = 4 | a skipped required job counts as passing, hence the aggregator's own check | proposed |
| (f) split the tests over 35 s (`deploy-slow-*` into six; `gate-infra`, `infra-runner`, `infra-pooler` in two) | the floor (e') cannot pass: 110 s → ~37 s | none (each split is its own unit, its covers unchanged) | proposed |
| (d) a test that was red in the batch reruns alone in its own shard, not after the batch | the ~330 s of serial reruns | none once (e') exists | proposed |

**Why (b) cannot pass a red tree.** A green pull request run records `tower-gate-green-<key>` as an artifact (7 days).
The key is the sha256 of the judged commit's tree, its parents, the `--base`, the plan's stages and tests and the runner
image (`ImageOS`, `ImageVersion`, OS, arch), plus a key version. The tree is every tracked file, so the same tree means
the same verifier, gate, tests, registry and toolchain pins. The same parents make all the history below the commit the
same. The queue run (`--reuse`) accepts a record only under exactly that name, not expired, from a run of this
repository (never a fork's head) on one of the commit's parents. Even then it runs every stage again, since they also
read the commit itself (the secret scan of the history reads the queue commit's message). A record exists only after
`verify-commit` exited green. A failed lookup is a miss, and a miss runs the tests. What it does not add: a flaky test
green once is green once, as before. The whole suite still runs after each merge to `main` (`full-suite.yml`).

**After the owner installs the staged workflows** (`services/runner/github/tower-gate.yml` and `full-suite.yml` as
`.github/workflows/`): the queue runs should say "tests green in run N" and finish in ≤ 30 s. The PR runs stay as above
until (e')+(f) land. p99 ≤ 60 s needs both: the queue half is reached here, the pull request half is not. To measure
again:

```
gh api 'repos/openuniversity-si/open-university/actions/runs?per_page=100' \
  --jq '.workflow_runs[] | select(.name=="tower-gate") | [.id,.event,.conclusion] | @tsv'
gh api repos/openuniversity-si/open-university/actions/runs/<id>/jobs \
  --jq '.jobs[] | .steps[] | [.name, .started_at, .completed_at] | @tsv'     # the steps' times
gh api repos/openuniversity-si/open-university/actions/jobs/<job id>/logs \
  | grep -E 'verify-commit: |Cache (restored|not found)'                     # the verdict, the reuse, the cache
```

## QUEUE-REARM: the wait from a green tower/gate to the merge queue (16/11/2026)

**The report.** #55, #60, #63 and #64 had auto-merge on and a green `tower/gate` on their head, and entered the merge
queue only after auto-merge was turned off and on (`DELETE`/`PUT pulls/<n>/ccr/auto_merge`).

**What the measure says** (`scripts/queue-wait --last 18`, #49 to #67). GitHub adds a pull request with auto-merge on
to the queue some time after the required check turns green, not at once. On the 14 pull requests nobody touched, that
wait was 4 to 68 s (#54 4 s, #52 6 s, #67 5 s, #59 13 s, #51 17 s, #56 19 s, #57 23 s, #62 33 s, #65 37 s, #49 40 s,
#58 41 s, #66 41 s, #61 46 s, #53 68 s). The four "stalls" were turned off and on 25 s (#60), 80 s (#64), 94 s (#55)
and 119 s (#63) after their green: three of the four inside that range or just past it, so none waited long enough to
show that GitHub would not have queued it. The session's 60 s re-arm raced GitHub's own entry. #64's earlier head was
not queued for a real reason: #63's merge left it in conflict, fixed by a merge commit of `main`. (#63's off and on
left no `auto_merge_disabled` event on its timeline; the session's transcript has it at 00:05:36 UTC.)

**Ruled out.**
- The check's source: the ruleset requires the context `tower/gate` with no app pinned, and the only thing that
  reports it is the `tower/gate` job of `tower-gate.yml`, one check run per head (no commit status), its check suite
  complete within a second of the job.
- Auto-merge turned on before the check existed on the head: #53, #65 and #67 were armed that way too and entered on
  their own (68, 37 and 5 s).
- The pushing token: every head's `pull_request` run started, and the queue's entry does not wait on a workflow.

**The rule.** No re-arm and no nudge: a pull request with auto-merge on and a green `tower/gate` is left to GitHub.
Only one that `scripts/queue-wait <pr>` shows still `never queued` well past the untouched maximum is a case to
look into, with its timeline.

## QUEUE-RUN: the queue's own time, and the queue built side by side (16/11/2026)

**The measure** (`scripts/queue-wait --segments --last 20`, #52 to #71, from a pull request's entry into the queue to
its merge):

| segment | what it is | p50 (s) | max (s) |
|---|---|---|---|
| dispatch | the entry to the check suite of tower/gate on the queue's commit | 17 | 47 |
| pickup | that suite to the job's start on a runner | 2 | 4 |
| gate | the `merge_group` job (VERDICT-REUSE: the tests' green stands for the first entry) | 28 | 174 |
| land | the green to the merge | 31 | 33 |
| **total** | | **81** | **226** |

`dispatch` is GitHub's own 17-19 s; #69's 47 s is that plus #68 still ahead of it, since the queue built one entry at
a time. `land` is two groups, 3-12 s or 31-33 s, also GitHub's. `deploy/prepare` does not hold the merge: it waits for
main to move and ends 1-2 s after it. The gate's tail (148-174 s, #55 #56 #64) is the pull requests whose plan ran the
deploy tests. One entry at a time at the p50 is 0.74 merges a minute (about 1,070 a day), and at the max 0.27.

**The values** (staged in `.github/rulesets/main.json`, applied by the owner):

| key | was | is | why |
|---|---|---|---|
| `max_entries_to_build` | 1 | 5 | five entries verify side by side, each on main plus the entries ahead of it, so the queue's time is no longer the sum of its entries: about 5 / 81 s = 3.7 a minute at the p50, and 5 / 226 s = 1.3 a minute at the max |
| `max_entries_to_merge` | 1 | 5 | the green entries at the front merge in one step, so `land`'s 31 s is paid once per group instead of once per entry |
| `grouping_strategy` | ALLGREEN | ALLGREEN | every entry of a group must be green to merge (HEADGREEN would let a red entry in under a green one behind it), so every commit main takes was judged green |
| `min_entries_to_merge`, `min_entries_to_merge_wait_minutes` | 1, 0 | 1, 0 | a lone entry never waits for company |
| `check_response_timeout_minutes` | 60 | 20 | an entry whose check never answers leaves the queue after 20 minutes, not 60; the gate's slowest run was 490 s and its job's own timeout is 30 minutes |

**What the workflows need: nothing.** `tower-gate.yml`'s concurrency group is the queue commit's sha and
`deploy/prepare`'s the queue's branch, so the five entries' runs never cancel or wait for each other. The toolchain cache
is restored read-only by every run. The runners: a public repository on the Free plan runs at most 20 jobs at once, and
each building entry holds two (tower/gate and `deploy/prepare`, which waits for the merge). So 10 for the queue, up to 7
for the fronts' pull request gates, one doorbell and one `full-suite` make 19, under 20. More than five builds, or more
than seven fronts, starts queueing jobs for a runner.

**What it costs.**
- Only the first entry's tests reuse its pull request's green verdict. The entries behind it have the entry ahead as
  their first parent, not main, so VERDICT-REUSE misses and their gate runs its plan's tests (a docs pull request about
  30 s, one that touches the deploy tests 150-230 s). That costs throughput nothing: they run side by side.
- A red entry leaves the queue and the entries behind it are built again without it.
- The deploy's fast path (QUEUE-SWAP) needs the merge's first parent to be the deployed commit
  (`/tower/deploy/last-sha`). In a burst main moves faster than a build ends, so only the first merge swaps. The others
  are deployed by the build that the push rings, of main's head: correct and slower, never wrong. Making the fast path
  follow a burst is a unit of its own.

**To apply** (an admin's credential; the live ruleset also has keys the staged file does not spell, so patch it in place):

```
gh api repos/openuniversity-si/open-university/rulesets/27250343 \
  | jq '{name, target, enforcement, conditions, bypass_actors, rules: (.rules | map(if .type == "merge_queue"
        then .parameters += {max_entries_to_build: 5, max_entries_to_merge: 5, check_response_timeout_minutes: 20}
        else . end))}' \
  | gh api -X PUT repos/openuniversity-si/open-university/rulesets/27250343 --input -
```

## GATE-ISOLATED: the timing-bound tests beside the batch (16/11/2026)

In the 150 `tower-gate` runs up to 16/11, 32 had a test that was red in the batch and green alone, and in all 32 it was
`infra-intask-standby` (its 20 s waits starve beside a 4-worker batch). Those runs took 98-146 s; the 110 without a rerun
had a p50 of 19 s. `verify-commit` now runs the tests that `gate.isolated_tests` names by themselves, at the same time as
the batch of the others, which gets one worker fewer (`GATE_TEST_WORKERS`). Measured on 4 CPUs on the 28 tests a change of
`tower_infra/container.py` plans: the batch of all 28 took 111 s with `infra-intask-standby` red; that test beside a
3-worker batch of the other 27 passed in 14 s and the batch took 42 s. An isolated test still red runs once more alone,
like any test red in the batch (VERIFY-ALONE).
