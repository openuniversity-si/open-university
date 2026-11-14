# gate-speed — diagnóstico

Measured in the session container (Daniel, 30/10 23:11 BRT): 4 vCPUs, 15 GB, the pinned toolchain. One command
measures the main metric and every guard, the same at the baseline and at the end of every phase:

```
scripts/test-suite --metrics --warm --json <file>             # main metric and guards, no coverage tracer
scripts/test-suite --metrics --coverage <dir> --json <file>   # the coverage guard: a second cold pass under coverage.py
```

`--root <checkout>` measures another checkout (the baseline below is the base `c770ba2e`, a clean worktree);
`<dir>` holds coverage.py 7.10.7 (`python3 -m pip install --target <dir> coverage==7.10.7`). The hermetic
sitecustomize starts coverage.py in every Python process the tests start when `COVERAGE_PROCESS_START` is set.

## Métrica principal
**`cold_wall_s`: the wall of the whole engine test suite run cold** (every `scripts/tests/*.test.sh` executed, none
answered by its content key: a fresh, empty result store), in parallel at the box's width (4 workers here), from the
first start to the last end.

It is a proxy of Daniel's goal (all tests in at most 10 s on the e2-micro, ideal 1 s). Its gaps:
1. **The box.** The container has 4 vCPUs; the e2-micro has 2 burst vCPUs and 0.25 sustained. Its cold wall is about
   `cpu_s / 2` while burst credit lasts and up to `cpu_s / 0.25` after (D-093). So `cpu_s` is the guard that predicts the
   e2-micro, and the e2-micro is measured once, at the end.
2. **Cold is the worst case.** A real change is judged mostly by key (`warm_wall_s`) plus the tests its change selects;
   the cold wall bounds every change from above.
3. **Tests only.** The gate's checks (structure check, secret scans, generated drift, schema compat, shellcheck) are not
   in it; their cost is recorded below as context, not as a target of this program.

## Métricas de guarda
Re-measured at the end of every phase; a phase passes only if none gets worse (D-115).

| Guard | Better | What it protects |
|---|---|---|
| `coverage_pct`: line coverage of the engine's Python (`scripts/`, tests and generated code excluded) under the whole suite, every Python test process included | higher | what the suite checks; no speed-up may drop it |
| `test_functions`: `def test_` in `scripts/tests/**.py` (OU-DECOUPLE's G2) | higher | no test deleted or skipped to hit a number |
| `failed`: script tests that failed in the cold pass or in the coverage pass (two independent cold runs, a flake shows as a difference) | lower | a green suite; a flake is a failure until it is owned |
| `cpu_s`: CPU-seconds of every process of the cold pass | lower | what the e2-micro pays; no wall bought by burning CPU |
| `warm_wall_s`: a second pass, every unchanged test answered by key | lower | the path a typical change takes |

`script_tests` (the number of `*.test.sh`) is reported, not guarded: a phase may regroup scripts as long as
`test_functions` and coverage hold.

## Linha de base
Measured on 30/10 between 23:28 and 23:42 BRT in the session container (4 vCPUs, 4 workers), on a clean worktree of
the base `c770ba2e` (after Open University left, #825 and #826), with `scripts/test-suite --metrics --root <worktree>`.

| Metric | Baseline | Notes |
|---|---|---|
| **`cold_wall_s` (main)** | **169.1 s** | three cold runs: 165.5 s (two tests failing early for a reason of the box, below), 169.1 s, 178.4 s (with a light load beside it); the tests start in discovery order, because this box has no recorded durations (the gate orders longest first by the durations a box records) |
| `cpu_s` | 529.5 CPU-s | 3.1 CPUs busy on average out of 4; the e2-micro floor is about `cpu_s / 2` = 265 s with burst |
| `coverage_pct` | 89.12 % | 21,425 statements in 153 files, 2,330 missed; every non-generated module of `scripts/lib` is imported by some test (153 of 153), so a module no test imports would not count: none today |
| `test_functions` | 2,337 | OU-DECOUPLE ended at 2,333; #826's head added four |
| `failed` | 0 | the cold pass and the coverage pass, and the third cold run |
| `warm_wall_s` | 3.55 s | 94 of 95 answered by key |
| `script_tests` (reported) | 95 | 63 take over 1 s, 18 over 10 s; their walls sum to 612 s |

Where the wall goes (cold pass, each test with one CPU because the suite runs 4 at a time):

| Test | Wall |
|---|---|
| `structure-check.test.sh` | 59.7 s |
| `train.test.sh` | 54.6 s |
| `push-guard.test.sh` | 44.2 s |
| `train-reuse.test.sh` | 39.6 s |
| `census.test.sh` | 27.5 s |
| `prepush.test.sh` | 27.0 s |
| `budgets.test.sh`, `generate.test.sh`, `visual-guard.test.sh`, `config.test.sh` | 15.5–16.3 s each |

Findings the measurement itself produced:
1. **The tests read the box's global git configuration.** This container signs every commit (`commit.gpgsign` with an
   ssh signing program): a fixture commit costs 80 ms here against 7 ms with `GIT_CONFIG_GLOBAL=/dev/null`
   (10 commits each way). A few tests isolate git (`test_train.py`, `gate-pin.test.sh`, `test_prepush.py`), the rest
   inherit whatever the box has, so the suite's cost and even its verdict depend on the box. A missing system: the
   hermetic rules isolate the network, the clock and the random seed, not git.
2. **The critical path is the long tail.** The four longest tests alone are 198 s of wall; with one CPU each they end
   the run while the other three CPUs idle (3.1 of 4 busy on average).
3. **Two tests depend on where the checkout lives.** `claude-session.test.sh` and `root-identity.test.sh` drop to uid
   65534 and failed when the worktree sat under a 0700 directory; they pass from a world-readable path. The baseline
   above uses one.
4. **Coverage had never been measured.** It now is, through the hermetic sitecustomize every Python test process
   already loads.

Context, not targets (the gate's checks, GATE-SPEED retro): the structure check takes about 20 s here, the secret scans
about 1 s each on a change.
