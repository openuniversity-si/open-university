# BASEFIX-shellcheck: retro

Unit: the base `mod/roadmap-integration` passes its own pinned gate. PR #769, branch `mod/basefix-shellcheck`, base
`c003303d0`. Session 2026-10-28, 15:05–16:40 UTC.

## 1. Brief quality
- **The red stages were right; one name was not.** "`Neon PR acceptance` inside script tests" is not a failure of its
  own. It is a stage of the nested gate that `gate-db.test.sh` drives, and its FAIL line is the output a red gate-db
  prints. Reading it as a third failure would have sent work to the wrong place.
- **The shellcheck count depends on the machine.** The brief's 31 findings came from shellcheck 0.10 or later (0.11.0
  gives 32 in exactly its 12 files). This machine has 0.9.0, which adds 7 findings (SC2119, SC2317) in 4 other files.
  The brief could not know this, because the tool is not pinned anywhere.
- **No failing check was on record for gate-db.** The engine event for gate-db on the base (KD-6bdaf1ee) kept only the
  tail line `GATE TOTAL: …` as its signature, so the failing check had to be found again from scratch.
- **The rules said the base merges in, and the newer brief says it does not.** MERGE LOOP and the merge-train rule
  (Daniel 08:30) conflict on this. I followed the newer one: no base merge into this branch.
- **The branch name conflicted.** The harness named `claude/base-fix-gate-failures-sh28fj` and the brief named
  `mod/basefix-shellcheck`. I took the brief's name, which is the `mod/<unit>` convention.

## 2. Audit and plan
- P1 (the flakes need the gate's load to show up) held in a weaker form. Neither suite failed in 9 plain or loaded
  runs, nor in one full script-test run. The causes were found by reading the code and then reproducing each one
  directly: an instant stage for the runner race, a concurrent preflight for the stamp, a simulated sweep for the
  database.
- P2 (the base run's unit timeout and two 300 s kills came from my own load) is decided by the head gate. See §4.
- P3 (shellcheck is not pinned) held. The code is now clean under both versions.
- **The plan changed once (`483f256f`).** Items 4 and 5 moved their fixes from the two test files to the helpers that
  hold the root causes: `gate-runner.sh`, and `test_db.py` for the sweep class.

## 3. Execution
Timeline (UTC, commit times):

| Time | Commit | What |
|---|---|---|
| 15:12 | `f6f14e58` | audit skeleton; draft PR #769 and STATUS |
| 15:13–15:32 | | base gate on `c003303d0` (1109 s) while I fixed shellcheck |
| 15:34 | `7f2fa5da` | audit and plan |
| 15:36 | `29a282c2` | shellcheck clean under 0.9.0 and 0.11.0 |
| 15:37–15:58 | | root-cause hunt for gate-db; claude-session in a sub-agent |
| 15:59 | `d3b00f86` | gate runner: the watcher ends without a signal |
| 16:02 | `bcd56846` | claude-session's own stamp and database; the sweep spares live owners |
| 16:03 | `483f256f` | audit root causes, plan revision |
| 16:01–16:06 | | five runs of each suite under load: 5/5 and 5/5 |
| 16:06–16:34 | | head gate on `483f256f`: pinned run green except env e2e |

Failures and rework, each with its class:
- **My mistyped `Claude-Session` trailer on `f6f14e58`** (class: hand-typed constant). The post-commit hook pushes
  on commit, so the commit cannot be amended. Later commits are correct.
- **Push refused twice by the literal census** (class: the pre-push scan reads the working tree, not the commit).
  The first time, my merge-phase edit had turned an existing URL literal into a new one; the plain SC2155 split fixed
  it. The second time, the sub-agent's uncommitted `[:10]` was the cause; I stashed it, and the final code calls the
  real `ou_test_db_name` instead of hard-coding the length.
- **Dead ends on gate-db:** the host-wide gate slot (the nested gate inherits it), the slot checkout path (a nested
  gate gets none), an async forge write (it is synchronous), the hermetic clock (opt-in), and the per-test timeout
  (600 s). About 20 minutes of reading. What ended it was a full script-test run through the gate's own runner,
  which failed a different suite (`gate-local.test.sh`, a stage record whose directory was gone), and then a
  300-iteration reproduction.
- **I measured the base gate under my own load.** I ran targeted suites while the base gate ran, so its unit timeout
  and the two 300 s kills are not clean evidence. Lesson 5 below.

Where time went: about 25 min shellcheck, about 45 min root causes (with the sub-agent in parallel on
claude-session: 1181 s, about 167k tokens), about 6 min five-run evidence, then the gate.

## 4. Gate
- Base `c003303d0` (loaded by my suites): FAILED, 1108.8 s. shellcheck; unit tests (TX32 5 s timeout); capture
  regression and e2e + a11y killed at 300 s. script tests PASSED on that run.
- Head `483f256f`, nothing else on the machine: `scripts/gate-local --sha 483f256f…`, exit 1.
  - Pinned run (the verdict, base tip tooling, GX-05; 839.5 s): every stage PASS, including shellcheck (25.5 s) and
    script tests (255.7 s; gate-db and claude-session green), unit tests and capture regression. The one exception is
    `e2e + a11y`, killed at 300 s (class env).
  - Report-only run (the head's own tooling; 859.8 s): the same, plus `performance tests`, where
    `read-latency.perf.int.test.ts` took 1058 ms against its 1000 ms bound. That check is a known load-sensitive one
    and the code under test is untouched; the bound is unchanged.
  - `e2e + a11y` is this container's environment, identical on the base. WebKit cannot launch ("Host system is
    missing dependencies to run browsers"), so 162 WebKit cases fail in milliseconds. Ten Chromium cases (health,
    no-video guard) also fail, and 795 cases on 4 workers do not fit 300 s. Installing system libraries needs root
    and is outside the manifest (setup.sh never does it), so I did not do it by hand. Owner: env (GX-ENV). On the
    brief's machine this stage passed (its 12:06 measurement listed only shellcheck and script tests).
  - P2 confirmed for the unit timeout and capture regression (both pass unloaded); refuted for e2e (env, above).
- Runs: one base gate, one head gate (pinned and report-only). No re-runs.

## 5. Lessons (each with its prevention and owner)
1. **A signal to a just-forked bash subshell runs the parent's EXIT trap.** Prevention: never signal a subshell to
   end it on the normal path; tell it through a FIFO or pipe. The runner now does this, and `runner.test.sh` fails if
   a stage that ends in time sends any signal. Owner: gate runner (engine-gate-run). This one race could explain
   other "random" red gates: it deletes a gate's checkout and logs mid-run.
2. **Shellcheck is not in the toolchain (D-027 gap).** Prevention: pin it in `config/registry/toolchain.json` and
   `scripts/cloud/toolchain.json` like gitleaks, so every gate machine runs one version. Owner: env (GX-ENV).
3. **The sweep took "no live backend" for "abandoned".** Prevention, now in `test_db.py`: the owner pid is recorded
   on create, live owners are spared, and the sweep re-decides under the DDL lock. Still open: `postgres.py` and
   `setup.sh` create databases outside `test_db.create`, so those have no owner. Owner: engine-test-support.
4. **A defect signature built from the last tail line names nothing.** `GATE TOTAL: N8s` was KD-6bdaf1ee's whole
   signature. Prevention: make the signature the first `FAIL` line of the tail, and keep the tail. Owner: KD1 /
   `defect_detect`.
5. **Measure a gate on a quiet machine.** Prevention: one line in the brief template ("run nothing else while a gate
   measures"), or the gate refusing a host with a load above N. Owner: brief template / gate preflight.
6. **The pre-push scan reads the working tree.** A sub-agent's uncommitted edit blocked an unrelated commit's push.
   Prevention: scan the commits being pushed. Owner: push guard / local-checks.

## 6. The step that should have descended
| Work done by an AI today | Same tomorrow? | Descends to | Cost this time | Owner |
|---|---|---|---|---|
| Running shellcheck under two versions to explain a count | yes | deterministic script: the pinned toolchain makes it one version | ~10 min, 3 turns | env |
| Reading a red gate-db with no failing check in its event | yes | deterministic rule: the signature is the first FAIL line | ~20 min of dead ends | KD1 |
| Pulling the engine event log to find a suite's last failure signature | yes | deterministic script: `scripts/gate-dev --why` reads the forge log by test name | ~5 min, 4 calls | gate tooling |
| Deciding whether a finding is a false positive (SC2016 on `bash -c '…$1' _ arg`) | yes, same decision as gate-fixed.sh's directives | rule in the engine: a shellcheck wrapper or lint note that names the accepted pattern | ~10 min | gate tooling |
| Writing a five-run harness under load | yes, every flaky-suite unit | deterministic script: `scripts/run test <name> --repeat 5 --load` | ~5 min | test-excellence |
| Choosing the branch when the harness and the brief disagree | yes | rule: the launcher passes one branch name | 1 decision | launcher |

## 7. The coordinator's gate on its box (A Torre, `482468b8`)
A Torre ran the gate on `483f256f` on its own machine and recorded this, kept here so the record stays in one file:

- **The gate there blamed the PR for the environment.** `script tests` failed with `postgres is not accepting
  connections on 127.0.0.1:33743: runuser: failed to execute /tmp/ou-root-pg-.../bin/initdb: Permission denied`.
  The uid-0 probe drops to `ou-postgres` and runs `initdb` from inside the gate's checkout. That checkout defaulted to
  `$HOME/.cache/...`, and `$HOME` there is `/home/box`, mode `0700`, which another uid cannot traverse.
  `scripts/cloud/env.sh` exports `GATE_CHECKOUT_ROOT` from `cloud.root_gate_checkout_root` only when running as
  uid 0, and that directory did not exist. With `GATE_CHECKOUT_ROOT` pointing at a traversable directory,
  `script tests` passed in 24 s and both suites went green on this head.
- **Not fixed here:** the private checkout root under a non-root session is a machine setting. It belongs to
  whoever provisions the machine (D-027), not to this PR. `e2e + a11y` is still outside `defects.stages`, so a
  browser failure can never be proven to be the base's: that is `GATE-E2E-BLIND`
  (`backlog/gate-sem-webkit.md`), queued behind this unit. It is also why this container's env-only
  `e2e + a11y` (section 4) shows as red.
- **One correction to that record:** claude-session did not fail on the watcher race. Its recorded failure
  (KD-c9225259) is the shared-stamp equality, reproduced 3/3 with a concurrent preflight, and its database could
  be swept while idle (reproduced 2/2). The watcher race is gate-db's and gate-local's (section 5, lesson 1).
- **Lesson (A Torre):** the unit was scoped as two flaky suites. It turned out to be three causes and one environment
  premise. The premise only became visible because the gate ran for real, on the exact head, on each machine. An
  audit that stops at the first root cause leaves the next one to whoever is blocked by it.
