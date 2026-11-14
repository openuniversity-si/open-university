# GATE-SPEED — retro

Stage 7 of the unit flow (D-077), over Daniel's brief (30/10 10:43 BRT), his PR comments of 11:46–13:02 BRT, the
[intake](intake.md), [research](research.md), [audit](audit.md), [plan](plan.md), ADR-42 and the five PRs merged on
30/10: #815 (13:49 BRT), #816 (14:29), #817 (15:33), #818 (15:45), #819 (16:18), plus #820 (this retro). It is written
when the session stops, not when the program ends: waves 2 (R1, R2, R4 at A3), 3, 4, 5 and 6 are not built, and
section 6 gives each its exact next step.

## 1. Brief and intake
- **The real problem held.** The gate recomputed what did not change and paid a process and a git repository per test
  case. The measurements only sharpened it: the cold script suite is about 805 CPU-seconds on any machine, most of it
  git processes (7,354 in one script).
- **What the brief could not know, found by evidence:**
  - The e2-micro sustains 0.25 vCPU: 805 CPU-s cannot fit 10 s cold on it at any parallelism. "The whole suite in 10 s"
    is reachable only warm, with every unchanged test judged by its content key (D-093, ADR-42).
  - This session has no shell on the VM, and the VM runner gated none of these PRs. It keeps the code it started with,
    so the merged fixes (User-Agent, self-update) reach it only after one restart. Every VM number below is therefore
    Daniel's baseline or pending.
  - Daniel's later orders changed the program while it ran: waves at the state of the art (11:47), Bazel with Gazelle
    and no Buck2 (11:50, 11:53), continuous operation with no night (12:57), the registry without addition conflicts
    (13:02), and every green commit merged at once by the session (13:49). Each is recorded (D-094, D-097, D-095, D-098)
    and placed in the plan.

## 2. Research, audit and plan
- The audit's six roots held. R3's state-of-the-art rung (A3, a snapshot of the shared store per run) was measured
  before building it: a fresh process pays about 30 ms for its first registry read with the shared cache warm (10 ms
  on the file store the gate's stages use), so a snapshot saves at most about 20 ms per Python process. The memo (A2,
  commit 1) stays (D-103).
- The audit misattributed one cause: the 66 comment-list reads per gate came from the SLO evaluation in the verdict
  hooks (`gate_status.verdict_hooks` → `slo.collect`), not from the defect router. A deeper tracer found it before
  commit 5, which therefore detaches the hooks instead of gating the router.

## 3. Execution
Timeline (BRT, 30/10; commit, gate event, and the PR it merged in):

| PR | Commit | What | Gate (about, BRT) | Verdict |
|---|---|---|---|---|
| #815 | `0cef25ef` | STEP 0, D-090 | 10:52 | green `5b5be5b742d5` |
| #815 | `e52c650f` | runner blockers (User-Agent; machine refs skip pre-push), D-091 | 10:58 | red `eb5cb73a21f3`: my wire test bound `0.0.0.0`, which went through the proxy |
| #815 | `2fd79c2a` | the wire test on loopback (also carried intake and research, staged early) | 11:09 | green `4eb053fcecbf` |
| #815 | `371df115` | audit | 11:47 | green `fb5743e12897` |
| #815 | `b23a6399` | plan, ADR-42, D-092, D-093 | 11:57 | green `46fa3c2bab01` |
| #815 | `236cd497` | wave 1.1: constant registry reads | 12:07 | green `5c555f8bc93c` |
| #815 | `ec822d4f` | wave 1.2: batched sha-keyed git reader | 12:21 | green `8dd90f6b0419` |
| #815 | `409583d2` | wave 1.3: the whole suite judged in one pass, `scripts/test-suite` | 12:38 | green `dac227c331f2` |
| #815 | `1788581d` | plan of every wave, D-094 | 12:47 | green `2680dc4cf68e` |
| #815 | `a9531336` | wave 1.4: change-scoped secret scans | 12:54 | red: the key name `gate.secret_scan_scope` names a secret |
| #815 | `2e36ecce` | fix: `gate.leak_scan_scope`; the proof's epoch cost | 13:10 | green `fe7043253777` |
| #815 | `be73a609` | registry core, D-095 | 13:25 | red `da47e7ca003f`: the pinned base had no renderer for the new target |
| #815 | `3e4fb539` | the target lands disabled, D-096 | 13:40 | green `8d5e60026f35`; merged 13:49 (`88adff93`) |
| #816 | `fdc1fdd0` | wave 1.5: verdict hooks detached | 14:00 | green in the sha form (unbound: #815 had merged) |
| #816 | `fc75833b`, `affd9cf5` | waves 5–6 plan (D-097); wave 1.6 runner self-update, D-098 | 14:20 | green; merged by the train 14:29 (`2eef3d95`) |
| #817 | `6a28d725`, `1a00dd2d`, `18d400a5` | wave R (63 owners split, D-099); the train's shard shadow; R5 part 1 (153 readers, D-100) | 14:50, 14:55, 15:25 | green; tier 2 red once (TX32 timeout under load), merged by the train 15:33 (`b10d17be`) |
| #818 | `b6eed487` | one `registry` target, D-101 | 15:40 | green `81016e5c1e28`; merged 15:45 (`00d5722f`) |
| #819 | `9167dd68` | R5 part 2: selection by readers, D-102 | 16:05 | green `e494e66b609a`; merged 16:18 (`8461a31d`) |

Failures, by root-cause class:
- **Code (mine):** the wire test's bind address; a registry key named like a secret; three pushes refused by the
  literal census (`commit_check --local` without `--stdin-refs` does not run the census the push runs; I learned to
  run it with refs); the stash conflict markers that the gate API read from the working tree (I edited the tree while
  a gate started).
- **Contract (P-46):** a generate target a PR adds cannot run under the pinned base: it lands disabled and the next
  PR enables it (D-096, D-101).
- **Base defects:** the proof's `wall_s`/`queue_wait_s` held epochs (monotonic start against an epoch clock); the
  train died on a `train.batch.shards` event too large for one comment (the shadow is now skipped, as its docstring
  promised); a defect record's stored `area` turns red whenever a unit manifest gains a path (re-derived by hand each
  time; wave R.5).
- **Load:** `ou-addresses.test.ts` TX32 (0.94 s idle) hit its 5 s timeout in tier 2, where a registry change ran the
  whole web battery beside the script tests. The timeout was not touched; R5's reader selection is the structural
  answer. `push-guard.test.sh` failed once in gate 12 and did not reproduce in four runs.
- **Platform:** #815 merged at a green head while later commits were on the branch, so GitHub stopped following the
  branch; #816 continued it (D-098).

## 4. Targets vs measured
| Target | Goal | Before | Measured (where) | Status |
|---|---|---|---|---|
| T1 whole suite, warm | ≤ 10 s, warn > 1 s | did not exist | p50 2.61 s, max 3.01 s over five runs, 111 of 111 by key (container, 2 CPUs) | met here, **WARNING** (> 1 s); VM pending |
| T1 whole suite, cold | — | 468 s, 805 CPU-s (container, 2 CPUs); 704 s (VM) | 390 s (2 CPUs), 318 s (4 CPUs) | **miss, physical** (D-093) |
| T2 push → verdict | ≤ 60 s | 36 min 47 s (VM) | 157–564 s per gate here under the pin; script tests and web stages still dominate | **not met** |
| T3 docs-only gate | ≤ 30 s | 36 min 47 s (VM) | 157–174 s here (stages 34 s, the rest report and hooks; the hooks are now detached) | **not met** |
| T4 GitHub reads per gate | ≤ 30 | 128 (VM), 135 here | 112–117 counted per pinned gate; the detached hooks take about 66 off the verdict's path from #816 on | **not met** |
| T5 peak memory | ≤ 600 MB | 460 MB (VM) | largest test process 179 MB here; VM pending | met here |
| T6 counts | never lower | 111 scripts, 2,262 Python test functions | 111 scripts; +19 new test functions; no test removed, skipped or quarantined | met |

Before/after per stage against the VM baseline (container numbers, the VM's pending):
- Script tests 704 s (VM, cold, full selection): a registry key now selects 7 tests instead of 22 (from the PR after
  #819); warm, every unchanged test is a key lookup (1.33 s for 111 keys, was 3.56 s).
- Secret scan (history) 191 s (VM): 0.67 s here for the PR's own commits (was 4.85 s), 1.1 s in the gate.
- Secret scan (tree) 94 s (VM): 0.97 s here for the PR's files (was 2.08 s), 1.2 s in the gate.
- Structure check 154 s (VM): 23.4 s → 20.2 s here.
- Train: `train-reuse` 7,354 → 1,322 git spawns (53 s → 21 s); every train run reads the unit manifests once per commit.
- REST: checked before every gate and train run; the 15,000-an-hour token never fell below 14,800 remaining, and no
  run waited on quota.

## 5. Lessons
| Problem | Change that would have prevented it | Owner |
|---|---|---|
| A rule or target a PR adds cannot run under its own pinned gate | the brief template says so; a target lands disabled and the next PR enables it (D-096) | structure owner (A Torre) |
| `commit_check --local` passes what the push refuses | `scripts/commit-check --local` runs the census with the branch's refs by default | engine-commit-plan |
| Session-side edits to the working tree while a gate starts | the gate API reads the head's registry, not the working tree's | engine-gate-run |
| A defect record stores a derived `area` | derive it on read (wave R.5) | engine-defects |
| A green head merges while later work is on the branch | D-098: each green commit merges at once and the next PR starts from the base | A Torre |
| No shell on the VM: its numbers depend on its runner | the runner publishes `scripts/test-suite` results as an event after each refresh (wave 3, the warm runner) | engine-service |
| The tracer had to be built in the session | keep `sitecustomize`-style call and spawn tracing as `scripts/gate-trace` | engine-gate-report |

## 6. Not done, with the exact next step
1. **VM numbers (Daniel).** On the VM, in the runner's checkout: `git pull`, restart the runner service once (the
   unit `scripts/service runner --print-unit` prints), then `scripts/test-suite` twice (cold, then warm) and post the
   two `suite:` lines. From then on the runner updates itself (`service.self_update`).
2. **Wave 2, rest:** R2 A3 (template fixture repositories and an in-memory git double for `train`, `train-reuse`,
   `structure-check`: the three hold about 30 % of the cold suite); R4 A3 (the post-verdict hooks as a `chores` runner
   job, an additive kind of `job.v1`); R1 A3 (results any runner trusts: PASS markers under a git ref namespace the
   gate runs write, verified by key).
3. **Wave R, rest:** `DECISIONS.md` one file per decision with a generated register; `docs/structure/assets.json`
   per entry; defect `area` derived on read.
4. **Wave 3:** the covers checked against the imports and reads each test makes (the tracer of this unit); the warm
   runner computing keys on push.
5. **Wave 4:** Bazel measured on the e2-micro first (server memory, cold, warm, time to verdict; D-xxx with the
   numbers), then `MODULE.bazel` and Gazelle-kept `BUILD` files, the `build.backend` adapter, bazel-remote on the VM's
   disk.
6. **Waves 5–6:** ADR-43 (continuous verification replaces ADR-33), the `verify-base` runner job, flake-aware culprit
   finding, continuous scans, the speculative queue; capacity measured against about 21,600 CPU-s a day.
7. **Waves 7–9 (added by Daniel's 13:15–13:26 BRT orders, D-104):** the zygote test server and the warm path (0.1 s
   typical, < 1 s most, ≤ 10 s worst, on the e2-micro); mypyc or Cython only where a CPU profile shows the gain; the
   10 ms best case, which this container's floor already puts out of reach for any path that starts a process or calls
   git. This retro is rewritten as the final one after wave 9.
