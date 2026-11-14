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
