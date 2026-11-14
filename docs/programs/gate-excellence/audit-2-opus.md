# GA2 — Gate excellence, audit 2 (deep-dive)

## 0. Executive summary

1. GA1 holds up: of 17 findings, 7 confirmed as written, 9 confirmed with corrections or widening, 1 refuted (F-13: lanes run in their own cloud containers, so the box is not the scale wall; the single train lock is, G-09). GA1 line numbers in `gate-local` are off by 6–8 lines; §1 gives the corrected ones.
2. Measured from 347 gate verdicts (#560–#691): of 231 head changes between gates, **151 were base merges** and 40 docs-only (**37 RETROs**). Forced base merges (structure check `rebase_errors` + "0 behind" rules, G-05/F-07) are the #1 gate multiplier, the RETRO case is #2, and carrying test results over 40 docs-only deltas had 0 counter-examples (Q3).
3. The gate overloads its own container: on an idle 4-vCPU box the green base **fails its own gate cold** (614 s, 2 timeouts, load avg 30) and passes warm (306 s), same code. KF3's "load-sensitive" class is self-inflicted (8 parallel script tests on 4 vCPUs); PostgreSQL is not the bottleneck (Q1, Q9, G-08).
4. The PR's own gate judges the PR: tooling is the checkout that runs it, and Transport v0 even runs the train from the producing PR's checkout (G-12, G-13). Every engine PR, step 4 included, grades itself.
5. Tier 2 is not what D-065 (5) says: it is mode `dev`, so it reuses box-local script-test passes and KD1 excusals, publishes no evidence, and runs in whichever container produced `pr.ready`; on 27/10 it ran on the box without PostgreSQL. `eaa408de` is still unmerged (G-01, G-02, G-07, Q8).
6. KD1 decided 149 verdicts against **35 different "base" shas** in one day (each machine's stale local ref, G-06), and twice excused a failure in a test the PR itself edited (#662, Q5). Docs-only changes skip the script tests that read docs, which manufactures base defects (G-15).
7. Script-test cache hit rate ≈ 28 %, and hits do not shorten the stage; e2e smoke + perf alone set a ≈ 110 s floor no cache moves (Q1, Q4). Status-comment PATCHes dominate API use (≈ 25 content-creating calls per gate, Q7).
8. Target: 27 building blocks in 4 waves (§5): wave 0 stops losing green work (preflight first, classified tier-2 verdict, a designated train executor, gate sized to its container); wave 1 makes the proof a v4 object with tier, base sha, gate version and input digest, judged by a pinned gate; wave 2 makes it reusable (carry-over, one merge rule, pr.ready from forge state); wave 3 shares and parallelises it (verified proofs in the train, sharded tier 2, forge enforcement).
9. The five paused gate units map onto blocks (BD1 → B-10/B-22, GS2 → B-04/B-11, AR1 → B-15, HD1 → B-19, MQ1 → B-18/B-20); four of them collide on `gate-script-tests.json` and two on `merge.json` (G-14).
10. CRITICAL premises for Daniel: P-01 docs-only carry-over (now with data), P-02 tier-2 reuse (meanwhile the code is made to obey D-065 (5)), P-03 a real GitHub status + branch protection / Vercel off (nothing on GitHub enforces the gate, G-11), P-04 shared store (money), and two new: **P-G1** a pinned gate judges every PR, **P-G3** no forced base merge in tier 1 once the train merges.

Base: `mod/roadmap-integration` at `2e423b7e`. Branch `mod/ga2`. Audit only; no code changes, no PR. Builds on GA1 (`origin/mod/ga1:docs/programs/gate-excellence/audit-1-fable.md`, `bed976b1`).

## 1. Verdict on GA1

Method: every citation re-read on `2e423b7e` (the base has not moved since GA1: `git log origin/mod/roadmap-integration -1` = `2e423b7e`); field numbers re-read from the box snapshot on `origin/mod/ga1-evidence`; four local measurements (§3). Line numbers in GA1 are off by 6–8 lines in `scripts/gate-local` from §1.1 on (e.g. the PostgreSQL abort is `:178-179`, not `:185-187`; the six prerequisites `:277-285`, not `:271-277`; classification `:292-299`, not `:286-296`; the record `:414-419`, not `:409-415`). The content is right; step 3 should cite the lines below.

### 1.1 Findings F-01..F-17

| ID | Verdict | Evidence (this audit) | Why |
|---|---|---|---|
| F-01 proof bound to head sha | **Confirmed, stays #1** | `gate-local:173,416` (record `<sha>.<suffix>`, deleted at start of every rerun); `gate_report.py:73-76` (`input_hash` = sha+mode+stage names: it hashes no content, so it adds nothing a sha does not); `train.py:76-78`; #691 run 2 on the RETRO head (`sessions.log` 11:08) | The key is the commit, not what was proved. Added: the record is deleted at the **start** of a rerun (`:173`), so a rerun of a green head that is killed leaves the head with no proof at all. |
| F-02 red base turns every PR red | **Confirmed, corrected** | `defects.json` `defects.stages=["script tests"]`, `rerun_timeout_s=1200`; `defect_detect.py:115-127`; both KD records still `status: "open"` (`docs/process/defects/*.yml`) | Correction: the base used to adjudicate is the tool checkout's **local** `origin/mod/roadmap-integration`, not the PR's base and not fetched (G-06), so the lever is machine-dependent. Also applies in tier 2 (G-01). |
| F-03 train blames a PR for an env failure | **Confirmed, corrected, widened** | `gate-local:82-159` (flock, slot, fetch, worktree) then `:178-179` abort; `:205` status begins **after** the abort, so no status comment either; `gate_report.py:218-234` (3 args → no events); `eaa408de` exists only on `origin/claude/merge-train-pr-ready-f7mxzt`, not on base (P-05 holds) | `eaa408de` would halt on this instance only because the 2000-char output tail contains `toolchain: ` (`engine_role.py:158`, `train.tier2_log_chars`); `FAIL local postgres did not start` alone classifies `code`. Widened: the train ran **on the box** (night-plan §26, owner `hb-1111`), against D-065 (3) "the box is off the critical path" (G-07). The ejected heads have no un-eject path (`train.py:61,73`). |
| F-04 nobody is told a gate ended | **Confirmed, corrected** | `gate_status.py:55-68,89-92`; `coordinator_launch.py` stderr port | Correction: history is **per checkout** (`record_dir` = `<checkout>/.gate/records`, `gate-local:89`), mixes modes/plans, and the "expected" figure is a **sum** of stage times, not a critical path (G-04). |
| F-05 2–7× the ceiling | **Confirmed numbers, corrected cause, re-ranked to #4** | 21 walls re-read in `sessions.log` lines 459–575; KF3 `audit.md:6-14` | Correction: the lanes ran in **Claude Code cloud containers** ("--cloud Max", 17 launch lines), one per session, not 30–40 sessions on one box. KF3 traced the load to the gate's **own** parallelism: `gate.script_tests_concurrency=8` on a 4-vCPU container while install/lint/unit overlap (G-08). Controlled numbers in Q1. |
| F-06 pr.ready refusals force new heads | **Confirmed, widened** | `pr_ready.py:67-91`; `sessions.log` 11:09 (#615 told to push an empty `Plan: 3` commit) | Widened: pr.ready also depends on **where** the gate ran (G-03), and the coordinator emitted #605/#607/#580/#586 by hand (`sessions.log` 10:31, 11:09). |
| F-07 three "behind" rules | **Confirmed, corrected to four** | `commit_check.py:92-104` refuses a behind head that never merged the base at its current merge base, evaluated on the PR's **live** head (G-05); `merge-phase` MERGEABLE; briefs "0 behind"; train none | The structure-check rule is the one that forces the first base merge of almost every PR at 41 merges/h; it is a head-churn driver GA1 listed but did not count. |
| F-08 caches keyed wide, unshared, unevicted | **Confirmed, corrected** | `gate_result_cache.py:70-99`; `gate-stages.json` (`unit tests`/`integration tests` inputs `**`); `providers.json:98-102` (`enum: ["local"]`) | Correction: the script-test cache **is** reused by tier 2 (G-01); "the train deliberately starts cold" is true only for build/lint/tsc/vitest/stage markers. |
| F-09 two proof stores, Vercel the only check | **Confirmed** | `gate-local:414-419`; `pr_ready.py:45-50`; `forge_github.py:3-5` | Unchanged. Q12 below on Vercel. |
| F-10 decorative stage graph, docs disagree | **Confirmed, softened** | `gate-fixed.sh:22` reads `gate_graph.py resources`; `gate_test_cache.py:139` uses `gate_graph.run_commands` | The graph is used for **resources** (heavy_db slots) and script-test execution, not for stage order. `gate-quiet` is `gate-local` on the working tree (`scripts/gate-quiet:5`) = legacy `pr` plan: confirmed. |
| F-11 KD1 flip vs quarantine | **Confirmed; hypothesis part unchanged** | `defect_detect.py:158-169` sets `raw_result` and flips; `gate_report.py:65-67` then publishes the flipped stage as `PASS` with `class: null` | Added: the published `engine.step.measured` for a flipped stage says `ok`, so `slo`/history count a red stage as green. |
| F-12 promised events never emitted | **Confirmed** | grep over `scripts/**/*.py` (tests excluded): no emitter of `env.drift`, `gate.slow`, `gate.started`, `session.ended`, `pr.pushed`; `forge_events.gate_slow` called only by `scripts/tests/test_forge_events.py:201-203`; `slo.breached` built only inside `slo.py`, which nothing schedules | Contracts exist (`contracts/events/env.drift.v1.json`, `gate.slow.v1.json`, `slo.breached.v1.json`): the gap is producers only. |
| F-13 the box saturates at ~1 gate/min | **Refuted as stated, replaced** | lanes are cloud containers (above); `train.lock_ref`, `train.lock_lease_s=3600`, `engine_role.LockedRole` | Tier 1 already scales horizontally (one container per session, 3 slots each). The real serial point is **tier 2: one train lock, one tier-2 gate at a time** across the whole engine (G-09). |
| F-14 comment hygiene | **Confirmed** | `forge_github.py:215-228` (PATCH failure → POST duplicate); `github_api.py:84-90` (403 → `auth`, fatal); `forge_events.py:185-199` (dedupe window read per publish); `forge_github.py:64-67` (60000-char limit) | Q7 sizes it. |
| F-15 gate as discovery loop for structure | **Confirmed, corrected** | `local-checks.json` runs **six** checks, not only `structure_fast`: it includes `no_registered_literals` and `secret_scan_diff`; `local_checks.py:181-217` | The local set lacks the base-relative modules (literal_census, config_check, vendor, unit_check, perf_tests, hermetic, decision_premises) = ~9 s of the 11 s tree part (Q2), and the whole PR-metadata part (G-05). |
| F-16 train single points of failure | **Confirmed** | `train.py:265-275` (halt on base move; break on first refusal), `:318-319` | Unchanged. |
| F-17 not hermetic, not attested | **Confirmed** | `gate-local:136,365`; `hermetic.py`; `gate_result_cache.py` keys use registry pins | Unchanged; see O-05. |

### 1.2 Opportunities O-01..O-16

| ID | Verdict | Why |
|---|---|---|
| O-01 content-addressed proof | **Confirmed keystone; resized L → M+M** | Splits cleanly: (a) record `head_tree`/`base_sha`/`toolchain_id` in `gate.passed` (additive, v4 schema, S); (b) carry-over rule for docs-only deltas (M, needs P-01). (b) is safe without O-02 for the RETRO case because `gate-areas.json` already classifies `docs/units/**` as documentation. |
| O-02 delta-aware inputs + real scheduler | **Confirmed, split** | Narrowing inputs (S per stage) is independent of replacing bash scheduling (M). Do the inputs first; the scheduler swap buys little until stages are smaller. |
| O-03 ledger + board | **Confirmed** | Add: the ETA must be a critical-path estimate (G-04) and keyed by stage × plan from `engine.step.measured`. |
| O-04 classify before blame | **Confirmed, raised to wave 0** | Smallest change with the largest blast-radius reduction: preflight at the top of `gate-local` (before flock/slot/worktree) + `gate.failed class=env` from driver aborts + land `eaa408de` generalised (classify on the driver's own exit code 2/`FAIL` prefix, not on the log tail). |
| O-05 environment attestation | **Confirmed** | Prerequisite for any reuse across machines (O-06, O-07). |
| O-06 shared store | **Confirmed, re-scoped** | Because lanes are separate containers (F-13 corrected), a shared store is what turns N cold containers into warm ones; it matters more than GA1 thought. Needs P-04 (money). |
| O-07 train consumes proofs | **Confirmed, sharpened** | Must first resolve G-01 (what "never cached" means) and G-02 (tier 2 must emit evidence). |
| O-08 base health | **Confirmed** | Must also fix G-06 (adjudicate against a recorded base sha). |
| O-09 pr.ready without new heads | **Confirmed, widened** | Add: ready decided from the PR's REST state, not the local checkout (G-03). |
| O-10 one merge rule | **Confirmed, widened** | Must include `commit_check.rebase_errors` (G-05). |
| O-11 visible GitHub check | **Confirmed, CRITICAL stays** | See Q12. |
| O-12 cost accounting | **Confirmed** | Q1/Q7 give the first numbers. |
| O-13 `--explain/--why` | **Confirmed** | Cheap; most data exists. |
| O-14 executor pool | **Confirmed, re-ordered** | The first executor pool is the train (G-09): sharded tier 2 before any tier-1 pool. |
| O-15 smaller stages | **Confirmed** | Add: script-test concurrency sized to the container (G-08). |
| O-16 retire outgrown | **Confirmed** | Add the stale D-065 (5) wording or the code (G-01), and `local-gate.md` claims. |

## 2. New findings (G-NN)

Working notes, written as found (SAVE OFTEN); ranked in §4. Citations on base `2e423b7e`.

### G-01 Tier 2 is mode `dev`, so the "tier 1 only" cache guard does not tell the train from a PR (fact)

- The train runs `scripts/gate-dev --sha <combined>` (`config/registry/train.json` `train.tier2_command`), i.e. `gate-local --dev`, mode `dev` (`scripts/gate-local:107`). Every cache guard tests the **mode**, not the tier: `TIER1_MODES = {'dev'}` (`scripts/lib/gate_result_cache.py:32,39-41`), `forge-events.tier1_gate_modes = ["dev"]` (KD1 adjudication, `scripts/lib/gate_report.py:99,122`).
- Lint/typecheck/vitest/stage-result caches miss in tier 2 only by accident: `engine_role.CommandGate.run` points `GATE_BUILD_CACHE_DIR` at a fresh temp dir (`scripts/lib/engine_role.py:148-152`), and those markers live under that dir (`gate-local:195`, `gate-runner.sh:59`).
- The **script-test cache is not under that dir**: `gate_test_cache.location()` reads `GATE_TEST_CACHE_DIR` or `gate.test_cache_dir` = `~/.cache/open-university/gate-tests` (`scripts/lib/gate_test_cache.py:48`), and `key()` has no tier check (`:66-98`). So tier 2 **reuses tier-1 script-test passes** from the box-wide store — the stage that dominates gate time (107–321 s) — while D-065 (5) says "Tiers 2 and 3 never use cached test results" (`docs/domain/DECISIONS.md:67`) and `gate_result_cache.py:13` claims the same.
- KD1 also applies in tier 2 (mode `dev` is in `tier1_gate_modes`): the train can merge a combined head whose script tests are red on a known base defect.
- Class: fact (code path), the effect on 27/10 runs is inference (the train's tier-2 runs all aborted before any stage, F-03).
- Impact: the rule the train's correctness argument rests on is not what the code does; either the rule or the code must change (it is a decision, not a bug fix: reuse is what O-07 wants, but bound to an attested proof, not to a box-local marker). Stages: train, merge.

### G-02 Tier 2 leaves no evidence: no `gate.passed|failed`, no `engine.step.measured`, no status (fact)

- `gate_report.py` publishes events only when `argv[5]` (the PR) is set and the sha is a full sha (`scripts/lib/gate_report.py:234`); the status comment needs `--pr` (`gate-local:205`, `gate-runner.sh:9-12`). The train calls `gate-dev --sha` without `--pr`, so a tier-2 run writes only a local `.dev.pass` file for the combined sha in the train's checkout and its stage timings are lost (only the train's own `train:batch` step is measured, `train.py:251`).
- The same holds for bisection probes (`train.py:314`, `judge`).
- Impact: tier 2 is the most expensive gate in the system and the only one with no per-stage history, no ETA, no classified failure record, and no reusable proof for the combined tree. Stages: train, dashboards, release (tier 3 cannot reuse what tier 2 proved).

### G-03 pr.ready fires only when the gate runs in the session's own checkout on the gated head (fact)

- `ready_hook` passes `root=None`, so `ready_after_gate` reads `git rev-parse HEAD` of `pr_ready.ROOT`, the checkout that holds the **tool** (`scripts/lib/gate_report.py:169`, `scripts/lib/pr_ready.py:62-83`), and the plan ticks from `base..HEAD` of that same checkout with `base = plan-tick.base_ref` = `origin/mod/roadmap-integration` as a **local ref**, not the PR's `baseRefOid` (`pr_ready.py:76-79`).
- So a gate run by the coordinator, the heartbeat or any checkout not sitting on the head never emits `pr.ready` ("checkout HEAD … is not the gated head"); a stale local `origin/…` ref changes which commits count as ticks and which merge base decides `lane_id` (`pr_ready.py:35-42`).
- Inference: this is why "gate green, pr.ready not emitted" needed a hand-run `scripts/pr-ready` for #605/#607 (GA1 Q10).
- Impact: the gate's hand-off to the train depends on where it ran, not on what it proved. Stages: pr.ready, train.

### G-04 The status ETA is per checkout, mixes modes and plans, and sums overlapping stages (fact)

- `history()` reads `record_dir/reports/*/*/stages.json` where `record_dir` = `<this checkout>/.gate/records` (`gate-local:89`), i.e. **per checkout**, not per machine as GA1 F-04 says; the newest 5 runs of any mode/plan (`gate_status.py:55-68`).
- `render_live` reports the **sum** of expected stage times left (`gate_status.py:89-92`), which it labels "stages overlap, so wall time is shorter": no critical path, although `gate_graph.py` has the graph.
- Impact: even with history, the ETA is not a wall-clock ETA. Stages: session, coordinator, Daniel.
### G-05 The structure check judges the PR's live forge state, not the gated head, and costs 1 REST call per commit (fact + measurement)

- With `--pr`, `structure.py` runs `commit_check.fetch` (`scripts/lib/structure.py:522-534`), which reads `pulls/<n>` and compares `base...pull["head"]["sha"]`, i.e. the head **at the moment the stage runs**, not `$sha` the gate checked out (`scripts/lib/commit_check.py:142,160`). A push during a gate makes the structure verdict describe a different head than every other stage.
- It also reads every comment (`decision_wait.errors`, `commit_check.py:132,162`), so a STATUS comment can turn a tree-identical head red (#607 f3f77b4b, GA1 F-15) and a later `Decision:` comment turns it green again: the stage is **not reproducible from the head**.
- Cost: `pulls/<n>` + `pulls/<n>/commits` + **one `commits/<sha>` per PR commit** + file pages + two `activity` pages + `compare` + all comment pages (`commit_check.py:142-166`). A 12-commit PR with 40 comments ≈ 20 calls per structure check, on every gate and every re-gate.
- `rebase_errors` (`commit_check.py:92-104`) refuses a head that is behind its base and has **never** merged it at the current merge base. At 41 merges/h (GA1 Q6) every PR that branched more than a minute before its first gate is behind, so the first gate of a fresh PR fails on structure unless the session already merged the base, which is itself a new head (#671 3943619e, GA1 F-15). This rule is a fourth "behind" rule, not in GA1 F-07's list of three (it is listed there as `commit_check.rebase_errors` but not counted as a head-churn driver).
- Measured locally (4 vCPU, idle, this checkout, base `origin/mod/roadmap-integration`): `scripts/structure-check --base …` **11.3 s**; the same with `--pr 691` **19.2 s** (+7.9 s, all REST). Per module (tree part): config_check 3.9 s, literal_census 1.9 s, vendor 1.7 s, unit_check 1.1 s, perf_tests 1.0 s, hermetic 0.5 s, the other 18 modules < 0.2 s each (sum 10.9 s). See Q2.
- Impact: the stage that GA1 ranks as the top discovery-loop cost is ~60 % deterministic tree work (cacheable by tree + base tree) and ~40 % mutable PR metadata that should be judged once per head change in seconds, not inside every gate. Stages: session, gate, train (tier 2 has no `--pr`, so it never runs these checks: the train merges heads whose PR metadata it never verified).

### G-06 Known-defect adjudication runs against the session's local view of the base, not the PR's base (fact)

- `adjudicate_known_defects` calls `defect_detect.resolve_base()`, which resolves `gate.batch_base_ref` = `origin/mod/roadmap-integration` with `git rev-parse` in `defect_detect.ROOT`, the **tool checkout**, without fetching (`scripts/lib/defect_detect.py:45-49`, `scripts/lib/gate_report.py:124`). The PR's `baseRefOid`, which `gate-local` already has (`gate-local:97-99`), is not passed.
- So the verdict of a red PR depends on how stale that checkout's remote-tracking ref is: a session that last fetched hours ago re-runs the failing test on an old tip (where the defect may still exist, excusing it) or the base sha differs per machine, so the per-(base, test) cache (`defect_detect.py:52-65`) is never shared between sessions that see different tips.
- The re-run uses the tool checkout's `node_modules` by symlink (`defect_detect.py:81-83`) — the base's tests run with the head's dependencies.
- Impact: the one lever that saved the 27/10 KF2 wave (F-02) is non-deterministic across machines; and `known_defects[].base_sha` in `gate.passed` is not the base the PR was gated against. Stages: gate verdict, train (tier 2 too, G-01).

### G-07 The train role ran on the box, whose environment no gate stage checks (fact)

- D-065 (3): "Every session (lanes, engine lane, train and battery roles) runs in a provider cloud session … the box is off the critical path" (`docs/domain/DECISIONS.md:67`). On 27/10 the train ran from the box (`--owner hb-1111`, `motor-exec-engine`, night-plan §25–26; first real run "box, 10:20-10:28, owner motor-box-tr", `sessions.log` 10:31). The box has no PostgreSQL; cloud containers get one from the SessionStart hook (`scripts/cloud/setup.sh`).
- `train.enabled` defaults to `false` in the registry (`config/registry/train.json`) and was switched on through the gitignored local change log ("train.enabled=true since 03:04Z (3d6419a535d9)", `sessions.log` 10:31), i.e. the switch that decides whether green PRs are re-proved and merged lives in one machine's `.tower/config`, invisible to every other machine and to review.
- Impact: the stage that decides merges ran where the gate's environment is least controlled, under a flag no other machine can see. Stages: train, merge.

### G-08 The gate overloads its own container: script-test concurrency is fixed at 8 regardless of CPUs (fact + inference)

- `gate.script_tests_concurrency = 8` (`gate_test_cache.py:140`), started right after install and overlapping lint, typecheck, unit and integration (`gate-local:308-317`, `gate-fixed.sh`); cloud containers have 4 vCPUs (`nproc` = 4 here; KF3 measured on the same shape). Nothing reads the CPU count; `gate.slots = 3` lets three such gates share one container.
- KF3 attributed both load-sensitive failures to this intra-gate load ("under parallel script-stage load", `known-defects.json:72`; KF3 `audit.md:6-14`) and fixed the **tests**, not the oversubscription.
- Inference: much of F-05's spread (130 s → 1316 s on the same container shape) is self-inflicted contention, not neighbour load. Q1 gives the unloaded baseline.
- Impact: flaky timing failures (a reliability cost) and long walls (a throughput cost) from one constant. Stages: gate, session.

### G-09 Tier 2 is a single global serial point (fact + arithmetic)

- The train is a `LockedRole` with one forge lock (`train.lock_ref = train/lock`, lease 3600 s); a run drains the queue batch by batch (`train.py:228-240`), each batch running one tier-2 gate (`tier2_timeout_s = 1800`) and, when red, up to `bisection_max_runs = 4` more.
- Throughput bound (inference): `batch_size = 8` per tier-2 run; with a tier-2 wall of ~10 min (the full dev plan cold, 614 s in Q1; ~7 min warm) the all-green ceiling is ≈ 8 × 60/10 ≈ 48 PRs/h cold to 8 × 60/7 ≈ 68 PRs/h warm, i.e. ≈ 1 100–1 600/day; one red batch costs 1 + up to 4 runs (≈ 35 min) for at most 8 PRs. 1 000 PRs/day needs ≥ 50 % of batches green at size 8; 100 k/day needs ≈ 70 merges/min, two orders of magnitude above one lock.
- `queue()` re-reads every open PR's whole event log plus its head over REST after **every** batch (`train.py:141-149,231-236`): O(open PRs × comment pages) calls per batch.
- Impact: this, not the box's gate slots (F-13 refuted), is the scale wall; and tier 2 is also where all proofs are re-made. Stages: train, merge, release.

### G-10 The proof store is PR comments read by paging, with no index (fact)

- `pr_ready.emit_ready` and `train.queue_entry` replay the full log of the PR (`forge_events.replay(port.read(repo, pr))`, `pr_ready.py:47`; `train.py:146`); `publish` reads the dedupe window before every append (`forge_events.py:185-199`, up to `github_max_pages = 20` × 100 comments); the status comment is found by paging back up to `gate.status_find_pages = 5` pages (`forge_github.py:215-221`).
- A PR with 8 heads (#615) carries ≥ 16 gate comments plus `engine.step.measured` events; every reader pays for every past head.
- Impact: proof lookup cost grows with heads × runs per PR and with open PRs; it is the hidden cost behind F-14 and G-09. Stages: pr.ready, train, dashboards.

### G-11 Nothing on GitHub enforces the gate (fact)

- `mod/roadmap-integration` and `main` report `protected: false`; `main` has `required_status_checks.enforcement_level: off` (REST `branches/<name>`, read 27/10). The protection endpoint answers 403 to this session's identity.
- Every merge rule (green on the exact head, ≤ N behind, train only) is enforced only by the tool that merges; a session with write access can merge a red PR with one call, and the 27/10 log shows merges by the per-PR rule, by the coordinator and by the train in the same day.
- Impact: the proof is advisory; "the train is the only merger" (D-065 (4)) cannot be true by construction until the forge refuses other merges. Turning protection on is an account action that needs a status the gate can write (P-03). Stages: merge, release.

### G-12 The PR's own gate judges the PR, in tier 1 and in tier 2 (fact)

- "Tooling is this script's checkout. --pr/--sha checks the head out only as the code under test" (`gate-local:21,65-67`): every stage script, `gate_report.py`, the classifier, `defect_detect`, the cache keys and the structure check are read from the checkout that **runs** the gate. A lane session runs `gate-dev --pr <n>` from its own checkout, which sits on the PR head (pr.ready even requires it, G-03). So a PR that edits `scripts/gate-local`, `gate-stages.json`, `structure.py`, `commit_check.py` or the registry is judged by its own edited version.
- Transport v0 makes it worse for tier 2: `ready_hook` starts `scripts/train run` from the same checkout (`train_trigger.py:24-33`, `root = ROOT`), and `CommandGate` runs `root/scripts/gate-dev` (`engine_role.py:150`): the train code and the tier-2 gate that decide the merge are the **producing PR's** code.
- The guard for gate changes (D-025: a gate change must cite an approved D-NNN, `commit_check.gate_errors`) is itself part of the code under change.
- Class: fact (code paths). No abuse observed; the risk is accidental: an engine PR that breaks the gate in a way that hides its own failure (e.g. a mis-keyed cache, a wrong `expected_stages`) passes itself, and the next PRs inherit it. The gate-excellence step 4 PRs are exactly such PRs.
- Impact: the verdict is not a function of (head, trusted gate); it is a function of (head, head's gate). Elite shape: the verdict comes from a **pinned gate** (the base tip's tooling, or a released gate version recorded in the proof as `gate_version`), and the head's gate code runs only as code under test (its script tests). Stages: gate, train, merge.

### G-13 The train runs inside whichever ephemeral container emitted pr.ready (fact + inference)

- Transport v0 launches the train detached in the producer's checkout (`train_trigger.py:24-33`, `start_new_session=True`), logging under that checkout's `.gate/train/`. A lane container is reclaimed when its session idles or ends; the lock ref is renewed before every judged run with `train.lock_lease_s = 3600` (`engine_role.py:84-91`, `forge_github.py:267-285`), and another contender is refused until `expires` (`forge_github.py:276-277`).
- Inference: a container reclaimed mid-run strands the train lock for up to one hour, during which every other `pr.ready` producer exits `busy`; the batch's tier-2 log disappears with the container. The tier-2 gate also competes with the lane's own gates for the container's 4 vCPUs and its 3 gate slots (G-08).
- Impact: tier 2's environment, tooling version (G-12), lifetime and capacity are those of a random lane session. This is the engine-side cause behind the box incident (G-07): there is no designated tier-2 executor at all. Stages: train, merge.

### G-14 The gate's test map is a hand-kept aggregate that every engine PR edits (fact)

- `scripts/lib/gate-script-tests.json` (79 tests with hand-written `covers` lists, the script-test cache key, `gate_test_cache.py:66-98`) was changed by **103 of 1 598** non-merge commits on the base since 2026-10-20; `CODEOWNERS` by 52, `scripts/gate-local` by 38, `docs/process/EVENTS.md` by 30. All five paused gate units edit it (#667, #683, #677, #680 list it in their files; #671 edits `gate-areas.json` instead), and two of them both create `config/registry/merge.json` (#667, #680).
- D-065 V4 says "no aggregate is committed by a PR (generated from the manifests or written by the train)"; this file is exactly such an aggregate, and its `covers` are the cache's correctness boundary: an under-declared `covers` is a false cache hit (the same failure mode as GA1's O-01 risk, already live today for script tests).
- Impact: merge conflicts between gate PRs (step 4 will be a train of exactly these), and a correctness hole no check closes (nothing verifies `covers` against what a test actually reads). Elite shape: covers derived (import/exec trace of the test under the hermetic harness, which already intercepts Python processes, `hermetic.py:82-107`) or declared per test file (a header in the test itself), never in a shared file. Stages: session, gate, step-4 planning.

### G-15 A docs-only change skips the script tests that read docs (fact)

- The `docs` area (`docs/**`, `**/*.md`, `**/*.txt`, `**/*.rst`) maps to **no** stage groups (`scripts/lib/gate-areas.json`, area `docs`, `groups: []`), so a docs-only PR runs only the six always-stages. But 12 `covers` entries of `gate-script-tests.json` are docs paths, e.g. `lessons.test.sh` and `coordinator.test.sh` → `docs/units/*/retro.md`, `program.test.sh` → `docs/programs/**`, `units.test.sh` → `docs/domain/DECISIONS.md`, `event-contracts.test.sh` → `docs/process/EVENTS.md`, `premises.test.sh` → `docs/process/premises/*.yml`.
- So a docs-only PR (or, after B-14, a docs-only delta) can break a script test without running it; the break surfaces on the **next** code PR as a red stage that reproduces on the base, i.e. a new "known base defect" (the F-02 wave mechanism). On a code PR the same docs edit does run them, because the code area pulls in `script-tests` and the per-test cache keys on `covers`.
- Impact: a hole in selection that manufactures base defects; and the reason B-14's carried plan must be "always-stages **plus every script test whose `covers` meets the delta**", not the bare docs plan. Stages: gate, base health, train.

## 3. Answers to GA1 §5 open questions

Status per question: **measured** (number from a run here), **read** (from code or evidence), **open** (left for planning, with why). Measurements ran in this cloud container (4 vCPU, 15 GB, idle box otherwise), never through a PR, never touching Neon, Vercel or production.

**Q1 — Where the seconds go, per stage, under no outside load (measured)**
Two runs of `scripts/gate-dev --sha 2e423b7e` (no `--pr`: exactly the train's tier-2 invocation, full dev plan, no Neon) in this idle 4-vCPU container, caches redirected to scratch: **cold** (empty build, test and defect caches; pnpm store already populated by the SessionStart hook) then **warm** (same caches).

| Stage | Cold (s) | Warm (s) | Note |
|---|---|---|---|
| secret history / tree / workflows / drift / schema | 7.6 / 2.8 / 0.0 / 0.5 / 0.2 | 1.5 / 2.6 / 0.0 / 0.6 / 0.3 | history scan is incremental when warm |
| structure check | 11.9 | 11.1 | tree part only (no `--pr`), Q2 |
| install | 4.3 | 3.8 | store warm in both |
| suite union | 282.1 | cached | |
| script tests | 302.1 | 3.7 (all cached) | |
| lint | 374.5 | cached | |
| typecheck | 30.2 | cached | |
| unit tests | **324.7 FAIL** (1 timeout: `site-health.test.ts` 5 s) | 120.7 PASS | same code |
| integration tests | **340.5 FAIL** (1 timeout: `database.int.test.ts` 30 s) | 159.3 PASS | same code |
| smoke database | 3.2 | 3.3 | |
| builds (test engine / production) | 26.8 / 27.2 | 4.9 / 2.7 | |
| browsers install / inventory | 29.5 / 9.1 | 1.2 / 2.9 | Chromium download cold |
| e2e smoke | 57.6 | 54.6 | never cached |
| performance tests | 57.1 | 56.3 | never cached, runs alone |
| **GATE TOTAL** | **614 s, FAILED** | **306 s, PASSED** | ceiling 180 s |
| CPU (user+sys over the whole container) | 1 840 CPU-s (≈ 3.0 of 4 cores for 10 min) | 705 CPU-s | load average peaked at 30 during the cold parallel block |

Findings from it: (a) **the base fails its own gate on an idle container** when script tests, suite union, lint, unit and integration overlap; both failures are timeouts, and both pass when the same tests run with less overlap (G-08 confirmed; KF3's "load-sensitive" class is self-inflicted). (b) Cold, the critical path is the parallel block (≈ 375 s, set by lint under contention) + builds + e2e + perf. (c) Warm, the floor is the uncached tests: unit/integration ≈ 160 s in parallel + e2e smoke 55 s + perf 56 s ≈ 280 s; even a run where every cacheable stage hits is ≈ 15 + 5 + 55 + 56 ≈ 130 s, so **e2e smoke and performance tests alone set a ≈ 110 s floor** that no cache moves (B-15 narrows when they run; B-04 removes the contention). (d) Field medians (Q4) are ≈ 1.3–2× these idle numbers, consistent with the same self-contention plus host noise. `GATE_SLOTS=1` vs 3 concurrent gates was not run: one gate alone already saturates the container, so three concurrent gates can only be worse; the B-04 sizing run (concurrency 4 vs 8) is open question 8.

**Q6 — Tier-2 economics (measured + arithmetic)**
Tier 2 today is the cold run above: no `--pr`, full dev plan, fresh build cache, so **≈ 600 s and a real chance of red on load timeouts alone**, plus the script-test markers it silently reuses from the producing container (G-01; in a fresh train container they would be cold too, +300 s). A batch of 1, 4 or 8 costs the same full plan; a `gate-batch` union plan for app-only batches drops the script-test stage (`delivery`/`engine-*` areas absent) but keeps unit, integration, builds, e2e and perf (≈ 450 s cold, inference from the stage table). Halt risk from base moves: on 27/10 the peak was 41 merges/h under the per-PR rule (`night-metrics` 04:55), i.e. a base move every ≈ 90 s, against a ≈ 600 s tier 2 — with other mergers active, a batch would almost never reach merge (`train.py:265-267` halts). With the train as the **only** merger the base moves only through the train itself, so the halt disappears; that is a precondition, not an optimisation (B-24 makes it enforceable). Bisection of a red batch of 8: up to 4 more runs ≈ 40 min.

**Q2 — How much of the structure check is tree-deterministic? (measured + read)**
24 modules read only the tree (some also the base for a diff: migrations, absolute baseline, shared literals, config_check, literal_census, hermetic, vendor, production_guard, defects, decision_premises, threshold, size); 3 read PR metadata over REST (`commit_check` incl. `decision_wait`, `visual_guard`, the `Premises:` line), `structure.py:453-571`. Time on base, idle: tree part **11.3 s** (`--base` only), with `--pr 691` **19.2 s**; inside the cold gate below **11.9 s**. So ≈ 60 % of the stage is cacheable by `(head tree, base tree)` and ≈ 40 % is REST-bound PR metadata that changes without a new head (G-05). GA1's "> 80 % tree-only" holds by module count (24/27), not by time. Four modules are ≥ 1 s each (config_check 3.9 s, literal_census 1.9 s, vendor 1.7 s, unit_check 1.1 s, perf_tests 1.0 s): together 9.6 s, i.e. the whole tree cost; they are the ones a session's local check set lacks (F-15).

**Q3 — False carry-over risk, and what actually changes the head (measured from the event log)**
Method: every forge-events comment on PRs #560–#691 (132 PRs) was parsed the way `forge_github._events` does: 5 478 events, 347 verdicts (`gate.passed` 163, `gate.failed` 184, all plan `dev`) on 108 PRs; all 339 gated shas fetched locally; the delta between each pair of consecutive gated heads of a PR classified by `git diff --name-only`. Raw tables: appendix (scratch CSVs were not committed; the method is reproducible from the comments).
- Gates per PR: median 3, max 8; 89 of 108 PRs gated more than once; 8 same-sha re-gates, all failed → passed (structure check, test-db, claude-session, a perf test: flakes or env, no code change).
- 231 head changes between gates: **base merge 151 (65 %)**, docs-only 40 (17 %), code 39 (17 %), empty 1. Of the 40 docs-only changes, **37 are RETRO commits** (`docs/units/*/retro.md`).
- Docs-only deltas: 35 passed → passed, 4 failed → failed, **1 passed → failed** (#650, f5ef4d3e → ffe2c58e, only `docs/units/config-theme/retro.md` changed; the red stage was the structure check, i.e. PR metadata, not a test). So **0 counter-examples** for carrying test and build results over a docs-only delta in 40 cases, and 1 case that proves the PR-metadata check must still run on the new head (B-11, B-14 keep it).
- Base merges: 34 passed → passed (pure "behind" re-gates), 80 failed → failed (re-gating into a still-red base), 29 failed → passed (base fix brought in), 8 passed → failed (the base made a green PR red). Base merges are therefore the **largest** source of gate runs (151 of 231) and the only class where the verdict genuinely changes because of someone else's code; that is the train's job (tier 2 on the combination), not tier 1's.
- Ranking consequence: F-01's RETRO case is real (37 re-gates ≈ one per unit) but the forced base merge (F-07 + G-05) is **4× larger**. B-18 (one merge rule; no forced base merge in tier 1 once the train merges) and B-14 (carry-over) together remove ≈ 80 % of re-gates (34 + 80 + 37 of 231 head changes are either pure-behind, still-red or docs-only).

**Q4 — Cache hit rate in the field (measured from the event log)**
- 169 of 347 verdicts list any `cached_tests` (the feature started 02:34Z on 27/10; 343 verdicts after it): ≈ half the verdicts get any hit. Cached tests per verdict: median 0, max 78; among verdicts with a hit, median 47.
- No denominator exists in the payload (O-12 gap). Using the count of `scripts/tests/*.test.sh` at each gated sha (53–80, median 76) as the denominator: **pooled script-test hit rate ≈ 28 %**.
- The script-test stage was **not faster** with hits: median 462 s / p90 742 s with any cached test (n = 169) vs 355 s / 670 s without (n = 117). Inference: the stage wall is set by its slowest uncached tests and by load (G-08), not by how many tests are skipped; caching the cheap tests does not move the critical path. Only stage-level hits (whole stage skipped) move wall time, and those require narrow inputs (B-15).
- Field per-stage durations (median / p90 s, from `engine.step.measured`): script tests 408 / 718 (n 286), integration 232 / 405, unit 207 / 314, suite union 135 / 192, lint 68 / 286, structure check 68 / 88 (n 347), e2e smoke 51 / 67, performance 47 / 60, typecheck 42 / 144; every other stage ≤ 20 s median. Sum of stage times per verdict (upper bound of wall): median 830 s, p90 2 058 s.

**Q5 — Is KD1's FAIL → PASS flip ever wrong? (measured)**
- 149 verdicts carry `known_defects` (91 failed, 58 passed) on 55 PRs and 35 distinct `base_sha`s — **35 different "bases" for one integration branch in one day**, consistent with G-06 (each machine's local view). Four defect/test pairs explain all: KD-024bbecb `generate.test.sh` 146, KD-4db6e693 `premises.test.sh` 23, KD-0d4efec3 `literals.test.sh` 11, KD-37467336 `structure-check.test.sh` 9 (two of them are not in the registry the base holds: only 024bbecb and 4db6e693 have records, so KD1 excused tests whose defect id was derived on the fly).
- Only **2** of the 149 verdicts were on PRs that touched the excused test or its likely inputs, both on #662 (c9ffdf37 changed `structure-check.test.sh`; 300fa994 changed `generate.test.sh` and `config/registry/generate.json`). Those two flips excused a failure in a test the PR itself edited: exactly GA1's masking hypothesis, now observed twice. Rule for B-10/B-22: a test whose own file or declared `covers` the PR changes is never excused.

**Q7 — API budget per gate (read; arithmetic)**
Calls per `gate-dev --pr` for a PR with k commits and ≤ 100 comments (code paths cited): `pr view` 1; `gate_status begin` ×2, each find (issue + ≤ 5 pages) + POST/PATCH ≈ 3 → 6; stage PATCHes at ≥ 15 s spacing (`gate.status_min_interval_s`) ≈ 15–25 for a 4–7 min gate; structure check `--pr` ≈ 7 + k (`commit_check.py:142-166`); `emit_evidence` = `change` 1 + dedupe window (issue + pages) 2 + POST 1 → 4; `ready_hook` = `change` 1 + full `read` 1 + window 2 + POST 1 → 5; final status 1–2. **≈ 45 + k calls per gate, ≈ 25 of them content-creating (POST/PATCH)**. If `pr.ready` fires, the detached train run adds `open_changes` + 2 per open PR (≈ 80 at 40 open PRs) per queue build (G-09). At 40 concurrent sessions × ~3 gates/h: ≈ 6 600 calls/h and ≈ 3 000 content-creating requests/h on one GitHub identity, against GitHub's documented 5 000/h primary limit and the secondary limit on content creation (80/min, 500/h) — inference: the status PATCH cadence alone exceeds the secondary hourly limit at that concurrency. No 403/rate-limit incident appears in the 27/10 logs (grep of `sessions.log`, `night-*`), so this is a risk, not an observed failure. The dominant term is the status PATCH cadence, not the dedupe read GA1 suspected; a failed evidence POST fails the gate as class env (`gate_report.py:239-242`, `github_api.py:88-90`).

**Q8 — Is `eaa408de` merged? (read)**
No. `git branch -r --contains eaa408de` → only `origin/claude/merge-train-pr-ready-f7mxzt`; `git log 0aeac030..origin/claude/merge-train-pr-ready-f7mxzt` = that one commit; base is `2e423b7e`. It classifies the tier-2 result with `gate_classify.classify(stage, log_tail)` and halts on `env`. It catches the 27/10 instance only because the 2000-char tail contains `missing toolchain: postgres`; a driver abort whose tail lacks one of the ENV phrases still ejects (e.g. `FAIL could not reset the local test database`, `gate-local:191`). It belongs in wave 0, generalised (§5 B-02).

**Q9 — PostgreSQL as a shared bottleneck (measured)**
Local cluster on `127.0.0.1:54322`, idle container, N concurrent `CREATE DATABASE` + `DROP DATABASE … WITH (FORCE)` pairs, 3 repetitions each: N = 1 → create 129–149 ms, drop 33–47 ms; N = 3 → create avg 189–234 ms (max 271), drop ≈ 95–121 ms; N = 8 → create avg ≈ 540 ms (max 641), drop ≈ 185–235 ms (max 282); N = 16 → create avg 0.85–1.14 s (max 1.3 s), drop avg 0.37–0.58 s (max 1.0 s). Latency grows roughly linearly with concurrency (each create/drop checkpoints), but stays **two orders of magnitude below KF3's 30 s stall**. Conclusion: the 30 s `claude-session` drop timeout was CPU starvation of the whole container (load ≈ 30, Q1), not cluster contention as such; raising `heavy_db_slots` is not the lever, B-04 is. Residue: after two full gate runs the cluster holds 2 `tower_test_*` databases (`tower_test_f793abf827`, the checkout's own, and `tower_test_f02`, left by a test and never dropped); no growth between the runs, so the leak is per test fixture, not per run. Not measured: the box's own cluster (absent, which is the F-03 point).

**Q10 — Who emitted `pr.ready` on #605/#607? (read)**
The coordinator, by hand: `sessions.log` 11:09 "pr.ready emitted: #607 25c1df7b lane=admin-lane (…), #605 791bb476 lane=playback-lane (…)"; earlier 10:31 "coordinator emitted pr.ready #580 0f285975 + #586 1d4ddfd9". The gate's own hook could not have done it from the coordinator's checkout (G-03: `ready_after_gate` needs the tool checkout's HEAD to equal the gated sha). The lane sessions read their PR state from their own checkout and comments, not from the event log replay, hence "not emitted".

**Q11 — Load sensitivity as a class (read)**
Host-derived values: only `hermetic-expectations.test.sh` (the KF3 guard itself) and `merge-phase.test.sh:300` (`limit=$(nproc)`, marked `host-ok`, bounds concurrency, asserts nothing). Clock-reading or sleep/timeout-based script tests: 18 of 175 files (`gate-db`, `gate-fixed`, `gate-heavy-db`, `gate-isolation`, `gate-worktree-resources`, `invoker-tooling`, `test_claude_session`, `test_cloud`, `test_config_check`, `test_credentials`, `test_forge_events`, `test_gate_graph`, `test_github_cli`, `test_hermetic`, `test_perf_tests`, `test_preflight`, `test_root_identity`, `root_probe.py`): each is a timing-budget candidate to audit in one class-fix PR. Web: 3 `*.perf*.test.ts` files (`pnpm test:perf`, the `performance tests` stage) assert wall budgets on the gate's own machine; plus `catalog-contract.test.ts` and `youtube-progress.test.ts` read the clock. Decision (non-critical, mine): wall-clock budgets do not belong in a per-PR verdict on an unisolated container; they move to tier 3 or run alone (they already run after `join_steps`, `gate-local:392-398`) and must report, not fail, unless the diff touches their inputs. The root cause on 27/10 was intra-gate oversubscription (G-08), not the tests.

**Q12 — Vercel "Account is blocked" (read)**
It is a **commit status** (`context: Vercel, state: failure, "Account is blocked."`), present even on the base merge commit `2e423b7e`; zero check runs. `mod/roadmap-integration` and `main` are **unprotected** (`protected: false`; main `required_status_checks.enforcement_level: off`), and no script reads commit statuses (grep: no `statuses`/`mergeable_state` reader; the train merges by `gh pr merge --match-head-commit`, `forge_github.py:145-153`). So it gates nothing and is pure noise. Corollary (G-11): nothing on GitHub enforces the gate either; every merge rule lives in tooling a writer can bypass. Removing the integration or adding a real status are account actions (P-03, CRITICAL).

**Q13 — Disk and inode budget per gate run (measured)**
One cold `gate-dev --sha` run on base: report directory `reports/<sha>/dev-<ts>/` **26 MB, 3 113 files** (browser artifacts, stage logs); build cache (lint/vitest/Next outputs) **109 MB** after one run; script-test markers 324 KB; `/tmp/tower-worktrees` residue 4.3 MB (ports and e2e dirs, never removed); the gate worktree itself was removed by the exit trap. Extrapolation (inference): the box keeps every run's report forever (no eviction, F-08); at 347 verdicts/day in the field that is ≈ 1.1 M files and ≈ 9 GB/day if they accumulated on one machine — the inode outages on the box came from the runs that do (heartbeat, coordinator, train: each tier-2 and bisection run writes a report under the runner's `.gate/records`). In lane containers the same growth is bounded by the container's life. B-23 owns eviction; until then a `gate-gc` that keeps the newest N reports per (sha, mode) is a one-commit fix inside B-12's PR or alone.

**Q14 — Signature of the proof (decided)**
Decision (non-critical, reversible): until executors are untrusted, the proof is authenticated by (a) the trusted comment author association already enforced on read (`forge-events.github_trusted_associations`), (b) a content hash over the canonical payload — the `event_id` already is one (`EVENTS.md:130`) — and (c) **new**: `input_digest` = sha256 over `(head_tree, base_sha, plan, selection, toolchain_id)` so a verifier can recompute it from git and the toolchain manifest without trusting the producer's arithmetic. A hash chain over the log adds ordering, not authenticity, and costs a read per append (G-10); skip it. Executor keys come with O-14 (any executor outside the trust boundary).

## 4. Consolidated ranking

Order: impact on merges per hour first, on the reliability of the verdict second, on scale third. Related findings are grouped into one rank; F-13 is refuted and replaced by G-09.

| Rank | Findings | One line | Measure behind the rank | Blocks |
|---|---|---|---|---|
| 1 | G-05, F-07 | Tier 1 forces base merges (structure check `rebase_errors` on the live head + 0-behind briefs): new heads, new gates | **151 of 231** head changes between gates were base merges; 34 pure-behind re-gates passed→passed, 80 re-gated into a still-red base (Q3) | B-18, B-11 |
| 2 | F-01 | The proof is the head sha; a docs-only commit throws it away | 40 docs-only re-gates, **37 RETROs**, 0 counter-examples for carrying test results (Q3); ≈ 220 s each (#691) | B-06, B-14 |
| 3 | G-08, F-05 | The gate overloads its own container: slow and flaky by construction | Field medians: script tests 408 s, integration 232 s, unit 207 s (Q4); **the base itself fails 2 timeouts on an idle 4-vCPU container** (cold 614 s FAILED, warm 306 s PASSED, same code), load average 30 (Q1) | B-04, B-15 |
| 4 | F-03, G-07, G-13, (P-05) | The train ejects green PRs for the machine's fault and runs wherever pr.ready was produced | 3 ejections in < 2 s each on 27/10; `eaa408de` unmerged; lock lease 3600 s in ephemeral containers | B-01, B-02, B-03, B-05 |
| 5 | G-12 | The PR's own gate (and its own train code) judges the PR | Code path (`gate-local:21,65-67`, `train_trigger.py`); applies to every engine PR, i.e. all of step 4 | B-09 |
| 6 | F-02, G-06, F-11 | Base defects: one bad merge reddens every lane; KD1 is machine-dependent and has masked the PR's own edits | 149 verdicts with known defects on **35 distinct base shas** in a day; **2 flips on a PR that edited the excused test** (#662) (Q5) | B-10, B-22 |
| 7 | G-09 | Tier 2 is one global serial lock | ≈ 48–68 PRs/h all-green ceiling at batch 8 and a 7–10 min tier 2; queue rebuild O(open PRs × pages) | B-03, B-20, B-21 |
| 8 | G-01, G-02 | Tier 2 reuses tier-1 script-test markers (contrary to D-065 (5)) and leaves no evidence | Code paths (`gate_result_cache.py:32`, `gate_test_cache.py:48,66`, `gate_report.py:234`) | B-07, B-08 |
| 9 | F-06, G-03 | pr.ready refuses for metadata and depends on the checkout it ran in | #615 empty `Plan: 3` commit; coordinator emitted #580/#586/#605/#607 by hand (Q10) | B-16, B-11 |
| 10 | F-04, G-04 | Nobody is told a gate ended; the ETA is per checkout and a sum | KF2 #657 "silent 50 min"; `gate_status.py:55-68,89-92` | B-17, B-12 |
| 11 | G-15 | A docs-only change skips the script tests that read docs | 12 docs `covers` entries, `docs` area `groups: []` | B-14 (plan rule), area fix |
| 12 | F-08 | Caches wide, local, unevicted; hits do not shorten the stage | pooled script-test hit rate ≈ 28 %; stage median 462 s with hits vs 355 s without (Q4) | B-15, B-19, B-23 |
| 13 | G-14 | The test map is a hand-kept aggregate every gate PR edits | 103 of 1 598 base commits since 20/10; 4 of 5 paused gate units edit it | B-13 |
| 14 | F-09, G-11 | Proofs in two stores; nothing on GitHub enforces the gate; Vercel red is noise | branches unprotected, zero check runs, Vercel status on every head incl. `2e423b7e` (Q12) | B-06, B-24 |
| 15 | G-10, F-14 | The proof store is paged PR comments; status PATCH cadence dominates API use | ≈ 45 + k calls and ≈ 25 content-creating calls per gate (Q7) | B-12, B-23 |
| 16 | F-15 | Structure failures discovered by the full gate | local checks lack the ≈ 9.6 s of base-relative modules and all PR metadata (Q2) | B-11 |
| 17 | F-16 | Train merge loop single points of failure | `train.py:265-275,318-319` | B-20 |
| 18 | F-17 | Not hermetic, not attested | network in install/browsers/media/fonts; no toolchain id in keys | B-19 |
| 19 | F-10, F-12 | Decorative graph; promised events never emitted; docs drift | grep: no producer for `env.drift`, `gate.slow`, `gate.started`, `session.ended`, `pr.pushed` | B-17, B-26 |

## 5. Target design, refined (building blocks and waves)

Principle (GA1's, kept): **prove once, bind the proof to content and to a trusted gate, verify everywhere else.** Two additions from this audit: the verdict must come from a **pinned gate**, not the head's own (G-12), and tier 2 needs a **designated executor** before it needs to be fast (G-07, G-09, G-13).

Sizes: **S** = one PR of 3–8 commits; **M** = 2–3 PRs; **L** = a program step. "Files" are the main ones, for collision planning (every block that adds a script test also touches `scripts/lib/gate-script-tests.json`, G-14; B-13 removes that collision). Waves are ordered so each one raises the capacity of the next: wave 0 stops the engine from losing green work, wave 1 makes the proof a trustworthy object, wave 2 makes it reusable, wave 3 makes it shared and parallel.

### Wave 0 — stop losing green work (all S, mutually independent, can run in parallel lanes)

| Block | What | Unlocks | Files | Deps | Risk |
|---|---|---|---|---|---|
| **B-01 Preflight first** | `gate-local` runs `preflight` database/browser/toolchain probes **before** flock, slot and worktree (`gate-local:75-159`); any gap exits 2 with one `FAIL env: <gap>` line, and with `--pr` publishes `gate.failed` with `class: env` and every expected stage in `missing_stages` (the exit trap passes mode and PR, `gate-local:126-127`). | No more 2-second "culprits"; the env class is visible on the PR and to the train. | `scripts/gate-local`, `scripts/lib/preflight.py`, `scripts/lib/gate_report.py` | none | Low; preflight already exists (`preflight.py:87-103`). |
| **B-02 Classified tier-2 result** | `gate-local` prints a machine line `GATE-CLASS: <code|env|contract>` (from the driver for aborts, from `gate_classify` per red stage); `CommandGate` reads that line, not a regex over a 2000-char tail; the train halts on `env`/`contract` and never ejects (generalises `eaa408de`, which should land first as is). | The train cannot eject for a machine's fault; the env PR is named. | `scripts/gate-local`, `scripts/lib/gate-runner.sh`, `scripts/lib/engine_role.py`, `scripts/lib/train.py` | B-01 (shares the abort path) | Low. |
| **B-03 Designated tier-2 executor** | Transport v0 still emits `pr.ready`, but the producer no longer runs the train in its own container (`train_trigger.py`): one train role session (D-065 (3) already says the roles are cloud sessions) holds the lock; `train.lock_lease_s` drops from 3600 s to the tier-2 timeout plus margin; the run log goes to the event log (B-08), not a container-local file. | Tier 2 runs in one known, preflighted environment; a reclaimed container no longer strands the lock for an hour (G-13); tier 2 stops competing with lane gates. | `scripts/lib/train_trigger.py`, `scripts/lib/gate_report.py` (`ready_hook`), `config/registry/train.json`, `docs/operations/train.md` | none | Medium: until B-21 the train is one session; its liveness becomes a monitored thing (heartbeat already exists). |
| **B-04 Size the gate to its container** | Script-test concurrency = `min(gate.script_tests_concurrency, nproc)` and `gate.slots` derived from vCPUs (registry holds the per-vCPU ratio, not the absolute); a per-stage timeout from the registry (`gate.stage_timeout_s` per stage, never shorter than today's observed p99). | Removes the self-inflicted load behind KF3 and much of F-05's spread (G-08); a hung stage ends with a classified failure instead of the 1800 s train timeout. | `scripts/lib/gate_test_cache.py`, `scripts/lib/gate-isolation.sh`, `scripts/lib/gate-runner.sh`, `config/registry/gate.json` | none | Low; numbers from Q1. Not a loosened threshold: timeouts are added where none exist. |
| **B-05 Land the classifier gaps** | Add the driver-abort strings (`postgres did not start`, `could not create/reset the local test database`, `missing TEST_DATABASE_URL`) to `gate_classify.ENV`, and make `gate_classify` run on the exit-trap path. | Today's exact incident class is labelled even before B-01/B-02 land. | `scripts/lib/gate_classify.py`, `scripts/gate-local` | none | Low. |

### Wave 1 — the proof becomes a trustworthy object (S–M; B-06 first, the rest parallel after it)

| Block | What | Unlocks | Files | Deps | Risk |
|---|---|---|---|---|---|
| **B-06 `gate.passed|failed` v4** | Additive new version: `tier` (explicit, see B-07), `head_tree`, `base_sha`, `base_tree`, `gate_version` (sha of the tooling that judged), `toolchain_id` (`toolchain_manifest.install_id()`), `selection_digest`, `input_digest` = sha256(head_tree, base_sha, plan, selection, toolchain_id, gate_version) (Q14), `lane_id`, `cost {wall_s, cpu_s, rest_calls, queue_wait_s}`; `.pass` files carry the same fields. Readers accept v3 and v4. | Every later block can verify instead of re-run; O-12 cost becomes data. | `contracts/events/gate.passed.v4.json`, `gate.failed.v4.json`, `schemas.lock.json`, `scripts/lib/gate_report.py`, `scripts/gate-local` | B-01 (abort path) | Low (additive). |
| **B-07 Tier is explicit, D-065 (5) made true** | `gate-local --tier 1|2|3` (default 1 for `--pr`, 2 for the train, 3 for the battery); every cache guard and KD1 keys on the tier, not on the mode (G-01); tier 2 stops reusing box-local script-test markers until B-20 replaces them with verified proofs. | The train's correctness argument matches the code; reuse becomes a decision (P-02), not an accident. | `scripts/gate-local`, `scripts/lib/gate_result_cache.py`, `scripts/lib/gate_test_cache.py`, `scripts/lib/gate_report.py`, `config/registry/forge-events.json`, `engine_role.py` | B-06 (records the tier) | Tier 2 gets slower by the script-test stage until B-20 (Q1/Q6 size it). |
| **B-08 Tier 2 leaves evidence** | Without `--pr`, the gate publishes its verdict and `engine.step.measured` on the repository channel with `sha = combined head` (G-02); bisection probes too. | Tier-2 history, ETA and reuse by content (B-20); tier 3 can see what tier 2 proved. | `scripts/lib/gate_report.py`, `scripts/lib/train.py` | B-06 | Low. |
| **B-09 A pinned gate judges** | The verdict comes from the **base tip's tooling** (a worktree of `baseRefOid` for tier 1, the batch base for tier 2), recorded as `gate_version`; the head's tooling runs only as code under test (its script tests). For a PR that changes the gate, a second, report-only run with the head's tooling shows the new behaviour (G-12). | The proof is a function of (content, trusted gate); engine PRs (step 4 itself) cannot pass themselves. | `scripts/gate-local` (tool root resolution), `scripts/gate-dev`, `scripts/lib/engine_role.py` | B-06 | Medium: two tool roots in one run; needs a D-NNN (changes what "the gate" is, D-025). |
| **B-10 KD1 against a recorded base** | Pass the PR's `baseRefOid` (tier 1) or the batch base (tier 2) to `adjudicate_known_defects`; fetch it; base re-runs use the base's own install. Verify `open` defects too and close stale ones. | Known-defect verdicts are reproducible and cache-shareable (G-06, F-02). Prerequisite of B-22. | `scripts/lib/gate_report.py`, `scripts/lib/defect_detect.py`, `scripts/gate-local` | B-06 | Low. BD1 #667 overlaps (re-plan it into this). |
| **B-11 Structure check split** | `structure check (tree)`: the 24 tree modules, declared deterministic, cached by (head tree, base tree, gate_version); `pr metadata`: commit plan, pushes, comments, premises line, judged against the **gated** sha (`compare base...$sha`, not the live head, G-05), also runnable alone after any push or comment, and its REST reads cut to one PR commits page (files from `git` locally). The same split feeds the local check set (F-15). | ~11 s of the always-run prerequisites becomes a cache hit on re-gates; the metadata part can never contradict the tree (G-05); a comment no longer flips a gate. | `scripts/lib/structure.py`, `scripts/lib/commit_check.py`, `scripts/gate-local`, `scripts/lib/gate-stages.json`, `config/registry/local-checks.json` | B-06 | Medium: commit_check reads move from REST to git. GS2 #683 (structure check off the critical path) folds in here. |
| **B-12 Status comment cost and shape** | One status comment per PR (edited across heads, superseded heads collapsed), PATCH only on stage end and at most once per 60 s, the D-027 class and log path per red stage, `gate_version`/`input_digest` in the footer. | Cuts ≈ 15–25 content-creating calls per gate to ≈ 6–10 (Q7); the comment becomes the human view of the v4 proof. | `scripts/lib/gate_status.py`, `scripts/lib/forge_github.py`, `config/registry/gate.json` | B-06 | Low. |

### Wave 2 — the proof becomes reusable (M; needs P-01 for B-14)

| Block | What | Unlocks | Files | Deps | Risk |
|---|---|---|---|---|---|
| **B-13 Derived test map** | Each script test declares its `covers` in its own header (or the hermetic harness records the files a test opened); `gate-script-tests.json` becomes generated and uncommitted (V4). | Ends the hottest gate-file conflict (G-14); makes the cache boundary checkable. | `scripts/lib/gate_script_tests.py`, `scripts/lib/hermetic.py`, `scripts/tests/*` headers, `scripts/generate` | none (can start in wave 1) | Medium: 79 tests to annotate once. |
| **B-14 Carry-over by delta (the RETRO case)** | When the PR has a passed v4 proof for an ancestor head `H0` with the same `base_sha`, classify `delta(H0, H)` instead of `base...H`: the plan is the stages whose declared inputs meet the delta (docs → the always-stages, ≈ 12 s of parallel work measured in Q1 plus ≈ 10 s of driver overhead, plus the script tests whose `covers` meet the delta, G-15; vs 220 s on #691) and every other stage is **carried** with `carried_from: <H0 event_id>`. First scope: deltas that the existing `docs` area covers. | One full gate per unit instead of two (F-01): the RETRO stays a file and the gate handles it (the brief's concrete case). | `scripts/lib/gate_policy.py`, `scripts/lib/gate_areas.py`, `scripts/gate-local`, `scripts/lib/gate_report.py`, `scripts/lib/pr_ready.py` | B-06, B-11, P-01 | Medium: docs read by tests (G-15: 12 `covers` entries, two on `docs/units/*/retro.md`) — the carried plan runs the always-stages **plus** every script test whose `covers` meets the delta; the tree structure check always runs. |
| **B-15 Narrow stage inputs** | Declare real `inputs` for lint, typecheck, unit, integration (`apps/web/**`, lockfiles, configs, `units/**`, `contracts/generated/**`), fail-closed `**` for anything undeclared (P-10); unit tests per unit as cacheable sub-steps. | Base merges that touch only scripts or docs stop missing every web cache; B-14 grows beyond docs. | `scripts/lib/gate-stages.json`, `scripts/lib/gate_result_cache.py`, `scripts/lib/gate-fixed.sh` | B-06, B-07 | Medium: an under-declared input is a false hit; tier 3 is the net. AR1 #671 (import-graph areas) is the same idea for the DB area and folds in here. |
| **B-16 pr.ready from forge state** | `ready_after_gate` uses the PR's REST head and commits (or the gated worktree), `baseRefOid` for ticks and `lane_id`, never the tool checkout (G-03); the plan-completeness refusal moves to the metadata check (B-11) so it is known at gate time; an empty `Plan: N` commit is never asked for. | `pr.ready` fires from any executor; the coordinator stops emitting it by hand (Q10). | `scripts/lib/pr_ready.py`, `scripts/lib/gate_report.py`, `scripts/lib/plan_tick.py` | B-11 | Low. |
| **B-17 Gate lifecycle events and ETA** | `gate.started {pr, sha, plan, expected_wall_s}` and the verdict as `gate.finished` for the wake; expected per stage from `engine.step.measured` (stage × plan, p50/p90) with the critical path from `gate_graph` (G-04); one board (`scripts/gate-board` or a pinned issue) over open PRs. | Nobody polls; the coordinator, Daniel and the producer session are woken by the event (F-04). | `contracts/events/gate.started.v1.json`, `scripts/lib/gate_status.py`, `scripts/lib/slo.py`, a new board script | B-06, B-08 | Low. GV1 is on hold for Daniel's design (P-G7). |
| **B-18 One merge rule** | `config/registry/merge.json` (one owner) with `max_behind_base`, `require_exact_head`, and whether tier 1 must merge the base at all once the train is the merger; `commit_check.rebase_errors` reads it (G-05, F-07). | Base merges stop being forced by the structure check; a green head knows if it is landable. | `config/registry/merge.json`, `scripts/lib/commit_check.py`, `scripts/merge-phase`, `scripts/lib/train.py` | none; P-G3 | Medium: BD1 #667 and MQ1 #680 both create `merge.json`; re-plan both onto this block. |

### Wave 3 — shared, parallel, enforced (M–L; money and account premises)

| Block | What | Unlocks | Files | Deps | Risk |
|---|---|---|---|---|---|
| **B-19 Attestation and hermetic network** | O-05 as GA1 wrote it: observed tool versions and config-log digest in keys and proof, pinned Vercel deps, `PLAYWRIGHT_BROWSERS_PATH`/pnpm `store-dir`/media cache seeded so a gate runs with the network off; HD1 #677's rest-fake readiness folds in. | Cross-machine reuse is safe. | `scripts/lib/gate_result_cache.py`, `gate_test_cache.py`, `scripts/cloud/toolchain.py`, `scripts/lib/hermetic.py` | B-06 | Medium: one-time key churn. |
| **B-20 Train verifies proofs** | Tier 2 = `gate-batch` union plan of the members (`gate_batch.py` exists), member proofs bound to `(head_tree, base_sha, gate_version)` verified, not re-run; tier-2 result cached by combined tree + gate_version; merge the proven prefix on a forge refusal; rebuild on a base move instead of halting (F-16). | Batch cost ≈ one union gate; the train can be the only merger. | `scripts/lib/train.py`, `engine_role.py`, `gate_batch.py`, `config/registry/train.json` | B-07, B-08, B-09, B-19, P-02 | Medium-high: needs P-02. |
| **B-21 Sharded tier 2** | Lane-partitioned train executors (disjoint units → disjoint batches, merged in order by a cheap final tree check), or speculative batches on predicted tips. | Lifts G-09's ~68 PRs/h ceiling linearly with executors. | `scripts/lib/train.py`, `train_ownership.py`, `config/registry/train.json` | B-03, B-20 | High: design work; the first L block. |
| **B-22 Base health signal** | Tier 3 on `integration.advanced` publishes `base.red {tests, since}` / `base.green`; KD1 adjudication for every stage kind from that signal (no 20-minute re-run in tier 1); re-gate asks paused while base is red. | A bad merge costs one fix, not 14–31 re-gates (F-02). | `scripts/lib/defect_detect.py`, `battery` role, `contracts/events/base.*` | B-08, B-10 | Medium: masking risk, mitigated by "test inputs untouched by the PR". |
| **B-23 Shared store** | Second `providers.storage_adapter` (R2 or a git ref) for stage/test markers, build outputs and proofs; LRU eviction and `scripts/gate-gc`. | New containers start warm (each lane is its own container, F-13 corrected). | `scripts/lib/adapters/storage*.py`, `config/registry/providers.json` | B-19, P-04 | Medium (poisoning; content-addressed and verified entries). |
| **B-24 Forge enforcement** | A gate status context (e.g. `tower/gate`) written from the v4 proof, branch protection requiring it on `mod/roadmap-integration` and `main`, the Vercel integration removed while the account is blocked (Q12, G-11). | "The train is the only merger" becomes true by construction. | `scripts/lib/forge_github.py`; account settings | B-06, P-03 | Account action. |

### Cross-cutting small blocks (any wave)

- **B-25 `--explain` / `--why`** (O-13): plan, selection, expected wall from B-17, cache hits predicted, preflight result; for a red run, the failing test, class, log path and base status. S, after B-06.
- **B-26 Retire what drifted** (O-16 plus): AGENTS.md `.gate/logs`, `gate-quiet` plan, ADR-28/33 budgets, D-065 (5) wording after B-07, `local-gate.md:62`. S, docs only.
- **B-27 Move the `train.enabled` switch out of one machine's local change log** (G-07): the flag lives in the shared store or the registry default; the train refuses to run where `OU_CONFIG_STORE=file` overrides it. S.

### Order and why

```
wave 0:  B-01 ─┬─ B-02        B-03        B-04        B-05          (parallel; B-02 after B-01's abort path)
wave 1:  B-06 ─┬─ B-07 ── B-08                                       (B-06 first: every other block writes its fields)
               ├─ B-09        B-10        B-11 ── B-12
wave 2:  B-13 (any time)   B-14 (P-01) ── B-15    B-16 (after B-11)    B-17    B-18 (P-G3)
wave 3:  B-19 ── B-23 (P-04)     B-20 (P-02) ── B-21     B-22     B-24 (P-03)
```

Capacity argument: wave 0 removes the failure modes that discard green work (27/10: three ejections, ~6 h of base-red waiting is wave 3's B-22, but its pre-condition B-10 is wave 1). Wave 1 gives every later consumer one object to verify. Wave 2 halves the gates per unit (B-14) and removes forced base merges (B-18), the two biggest multipliers of gate count (F-01, G-05). Wave 3 turns the single serial tier-2 point into a pool (B-20, B-21), the only way past ~1 600 PRs/day (G-09).

Mapping of the paused units: BD1 #667 → B-10 + B-22 (+ its `merge.json` → B-18); GS2 #683 → B-04 + B-11 (its timing report feeds B-17); AR1 #671 → B-15; HD1 #677 → B-19 (its readiness fix stands alone and can merge as is); MQ1 #680 → B-18 + B-20 (merge order) + B-17 (orphan detector is a board query). GV1 → B-17, after Daniel's design call.

## 6. Consumer contracts revised

GA1 §4's `gate.proof v4` is kept with four changes: (1) `gate_version` (G-12) and `tier` (G-01) are first-class; (2) the base is a **sha recorded by the producer** (`baseRefOid` or the batch base), never resolved from a local ref (G-06); (3) `input_digest` replaces `input_hash` and is recomputable by any verifier (Q14); (4) the PR-metadata verdict is a separate, cheap event bound to the same head, because it changes without a new head (G-05, Q3 #650).

```
gate.passed|failed v4 {                      # one per (tier, head, plan) run; additive over v3
  repo, pr|null, sha, unit, premises,        # v3 subject (pr null for tier 2/3, repository channel)
  tier: 1|2|3,                               # explicit, never derived from mode
  plan, selection {kind, units, tests, digest},
  head_tree, base_sha, base_tree,            # base_sha = baseRefOid (tier 1) | batch base (tier 2) | tip (tier 3)
  gate_version,                              # sha of the tooling that judged (base tip, B-09)
  toolchain_id, observed_versions{},         # B-19
  input_digest,                              # sha256(head_tree, base_sha, plan, selection.digest, toolchain_id, gate_version)
  stages[{name, result, raw_result?, class, duration_ms, cached, carried_from?, inputs_digest}],
  missing_stages[], known_defects[{test, signature, base_sha, defect}], failing_tests[], cached_tests[],
  carried_from?: {event_id, sha, delta_files[]},  # B-14; absent when everything ran
  cost {wall_s, cpu_s, rest_calls, queue_wait_s, cache_hits, cache_misses},
  lane_id                                     # decided at the gate (B-16), not by pr.ready alone
}
pr.checked v1 { repo, pr, sha, base_sha, result, errors[] }  # the PR-metadata verdict (B-11): plan, pushes, comments, premises line
gate.started v1 { repo, pr|null, sha, tier, plan, expected_wall_s, critical_path[] }
```

| Consumer | Receives | Invariants it checks | Binding | Reuse rule |
|---|---|---|---|---|
| **Session (lane)** | `gate.started`, the verdict (wake), `--why` on red | the verdict's `sha` is its pushed head; `gate_version` is the base's gate unless it changed the gate | head sha + plan | A docs-only commit after a green proof gets a carried proof in ≈ 20–30 s (B-14, estimate from Q1); a base merge is never required by tier 1 once B-18 lands. |
| **pr.ready** | the tier-1 `gate.passed` v4 and `pr.checked` for the same sha | `sha` = PR head over REST (not a checkout, G-03); `pr.checked.result = pass` (plan ticked, trailers); `lane_id` not null | (pr, sha, plan = `plan-tick.required_gate_kind`) | A carried proof is as good as a full one when `carried_from.delta_files` ⊆ the docs area and the PR-metadata check passed on the new head. |
| **Train, queue** | `pr.ready` → its evidence | evidence is a v4 `gate.passed` with `tier = 1`, same `sha` as the PR head, `gate_version` reachable from the base; no `pr.ejected` **with class code** for this sha | (pr, sha, lane_id) | A member whose `base_sha` is older than the tip is not stale for the queue: tier 2 proves the combination. |
| **Train, tier 2** | the members' v4 proofs; produces its own v4 proof on the combined head (repository channel) | its own run is `tier = 2`, uses the batch base's `gate_version`, and publishes evidence (B-08); a red run carries `class`; class env/contract halts, never ejects (B-02) | (combined head, combined tree, base_sha, gate_version) | Never reuses box-local markers (B-07). Reuse of member proofs or of a combined-tree proof is allowed only through verified v4 proofs (B-20) and only if P-02 is confirmed. |
| **Merge** (train, `merge-phase`) | the tier-2 proof (train) or the tier-1 proof (per-PR rule until the train is the only merger) | exact head (`--match-head-commit`); the registry merge rule (B-18); proof read from the event log, not a `.pass` file | merge sha's tree = tested tree (`train.py:281-287` already) | A proof made on another machine is accepted when it is v4 with a `gate_version` on the base (B-09/B-19). |
| **Release** (frozen, D-054) | tier-3 proof on the release head + DB gate | `tier = 3`, full battery, `gate_version` = release head's base tooling | release head | Re-run only stages whose `inputs_digest` changed since the last tier-3 proof (after B-15). |
| **Board / dashboards / coordinator** | `gate.started`, verdicts (all tiers), `pr.checked`, `engine.step.measured` | — | (pr, head, tier) | ETA from the ledger by stage × plan, critical path (B-17); a superseded head is shown as such. |
| **Known-defect adjudication** | red stages of tier 1/2 + `base.red` (B-22) | the test's own file and `covers` are untouched by the PR (Q5: two violations on #662); base = the proof's `base_sha` | (test, signature, base_sha) | Cache shared across machines because the base is a sha, not a local ref (G-06). |

Invariants for every consumer (GA1's six, amended): (1) the head sha is the pointer, `input_digest` is the key; (2) the base is a recorded sha; (3) a red names its class and its test; (4) nothing is loosened silently — a carried stage names the proof it came from and the delta; an excused test names its defect and the PR never touched it; (5) the proof travels (event log or store, never a local file); (6) the environment and **the gate version** that produced it are named; (7) the tier is explicit and each tier's reuse rule is the one written in D-065 (5) or its amendment.

## 7. Remaining open questions for planning

1. **Tier-2 executor shape (B-03).** One long train-role cloud session, or the coordinator's session holding the role? Both satisfy D-065 (3); the choice decides who restarts it and where its logs live. Planning picks one; it is not a premise for Daniel.
2. **Pinned gate mechanics (B-09).** Base-tip worktree per run (≈ 1 s with `git worktree add`, plus an install for web tooling) vs a released gate ref advanced by the train after each merge. Measure the first in a throwaway worktree before writing the PR.
3. **Covers derivation (B-13).** Header declaration vs hermetic-trace: the trace covers Python only (`hermetic.py`); shell tests spawn node and git. Spike one test of each kind before choosing.
4. **Stage inputs for web stages (B-15).** Which paths outside `apps/web/**` do lint/typecheck/unit/integration read (`contracts/generated/typescript/**`, `units/**`, `config/registry/**` through generated modules)? Needs a read of `tsconfig`/vitest config and one run with an access trace.
5. **The sum-vs-wall gap.** The event log has no stage start/end times (Q3/Q4 caveat), so field wall time cannot be reconstructed per stage; B-06 should add `started_at` per stage. Until then, wall comes from `GATE TOTAL` lines quoted by sessions.
6. **Secondary rate limits (Q7).** The arithmetic says the status PATCH cadence can exceed GitHub's content-creation limit at 40 concurrent gates; no incident is logged. Count real calls in one gate with a request counter in `github_api` (cheap) before sizing B-12.
7. **Bisection cost on a red batch (G-09).** With `bisection_max_runs = 4` and a ~7–10 min tier 2 (Q1), a red batch of 8 costs up to 50 min of the only train. Is a smaller batch under red streaks (adaptive batch size) worth it before B-21? Simulate on the 27/10 merge log.
8. **Load in lane containers.** Q1 shows the gate overloads an idle 4-vCPU container on its own; how much of the field spread (130–1 316 s) is that versus host contention between cloud containers? Re-run Q1 with `script_tests_concurrency = 4` in a throwaway worktree (B-04 sizing).
9. **What the `docs` area must still run (B-14) — answered here.** #650 shows the structure check can turn red on a RETRO, and 12 `covers` entries are docs paths (two of them `docs/units/*/retro.md`: `lessons.test.sh`, `coordinator.test.sh`), G-15. The carried plan is therefore the always-stages plus the script tests whose `covers` meet the delta (the per-test cache already computes this), and the `docs` area itself should gain the `script-tests` group filtered by `covers`.

## 8. Premises with blast radius

### 8.1 GA1's premises re-evaluated

| ID | GA1 status | Now | Evidence / reason |
|---|---|---|---|
| **P-01 CRITICAL** content-addressed proof; docs-only commit carries it | For Daniel | **Still CRITICAL, now with data**: 40 docs-only re-gates, 37 RETROs, 0 counter-examples for carrying test/build results; 1 structure-check flip (#650) shows the metadata check must still run (B-14 keeps it). | Q3 |
| **P-02 CRITICAL** tier 2 may reuse attested proofs | For Daniel | **Still CRITICAL, and sharper**: the code already reuses box-local script-test passes in tier 2 (G-01), contrary to D-065 (5). Decided meanwhile (safest reversible): B-07 makes the code obey D-065 (5) as written until Daniel decides; this costs tier 2 the script-test stage (≈ 300 s cold, Q1). | G-01 |
| **P-03 CRITICAL** visible GitHub check or silence Vercel | For Daniel | **Still CRITICAL, widened**: Vercel's status gates nothing (no branch protection, no reader, Q12); the same account action is what makes "train is the only merger" enforceable (G-11, B-24). | Q12 |
| **P-04 CRITICAL** shared store (money) | For Daniel | **Still CRITICAL, raised in value**: lanes are separate containers, so every lane starts cold; the shared store is what warms them. Wave 3 only. | F-13 corrected |
| **P-05 CRITICAL** `eaa408de` not on base | Verify | **Verified true** (not critical any more): only on the TR2 head branch. Its landing is B-02's first commit. | Q8 |
| P-06 snapshot complete | Decided | Holds; nothing after 11:37 used. | — |
| P-07 quoted walls are `GATE TOTAL` | Decided | Holds; the event log confirms the scale (sum of stages median 830 s ≥ wall). | Q4 |
| P-08 paused units re-planned by step 3 | Decided | Holds; mapping in §5. HD1 #677's readiness fix can merge on its own. | §5 |
| P-09 180 s ceiling stays | Decided | Holds. | — |
| P-10 narrowing fails closed | Decided | Holds; applies to B-15. | — |
| P-11 event log is the proof transport | Decided | Holds, with the cost caveat of G-10 (paging, no index). | G-10 |
| P-12 one exceptional day | Decided | **Partly refuted**: Q1 shows the gate fails on an idle container from its own load (G-08), so the slow, flaky tail is structural, not only the day's load. | Q1 |

### 8.2 New premises

| ID | Premise | If false (blast radius) | Status |
|---|---|---|---|
| **P-G1 CRITICAL** | The verdict may come from a pinned gate (the base tip's tooling, B-09) instead of the PR's own tooling; the head's gate code runs as code under test plus a report-only run. This changes what "the gate" is (D-025, D-065). | Without it, every engine PR (step 4 included) judges itself (G-12); the alternative is a human or second-session review of every gate change, which D-055 removed. | **For Daniel** (decision; touches the gate's source of truth) |
| **P-G2** | The train role runs in one designated cloud session (D-065 (3) already says so); Transport v0 producers stop running it in their own containers. | Tier 2 keeps running in random containers (G-13); a reclaimed one strands the lock up to an hour. | Decided (within D-065 (3); reversible) |
| **P-G3 CRITICAL** | Once the train is the merger, tier 1 does not require the PR to merge the base when behind (`commit_check.rebase_errors` relaxed by a registry rule; merge commits only, no rebase, stays). | Base merges keep driving 65 % of re-gates (Q3); the train re-proves the combination anyway. Relaxes a refusal of the structure check (D-025/FP1), so it needs a decision. | **For Daniel** |
| P-G4 | `script_tests_concurrency` and `gate.slots` may be derived from the container's vCPUs. | None beyond today's numbers; this adds no loosening (no test, timeout or budget changes). | Decided |
| P-G5 | Adding per-stage timeouts where none exist is not a loosened threshold. | If read as a new failure mode, stages that hang today would fail instead of waiting 1 800 s. Set them above observed p99. | Decided |
| P-G6 | Wall-clock perf budgets stay blocking in tier 1 until a D-NNN moves them (Q11 recommends tier 3 / report-only); B-04 removes the load that makes them flaky first. | — (the safe default) | Decided (no change without a D-NNN) |
| P-G7 | GV1 (visibility) stays on hold until Daniel's design call (11:05/11:09); B-17 is the input to that call, not a unit. | — | Decided (Daniel's standing order) |
| P-G8 | The `train.enabled` switch must not live in one machine's gitignored change log (B-27). | A second machine disagrees about whether the train exists. | Decided |
| P-G9 | Step 3 sequences B-06 (v4 contract) before any other wave-1 block, because each writes its fields. | Parallel wave-1 PRs collide on `gate_report.py` and the contract lock. | Decided |

## Appendix: evidence index

### Code read on `2e423b7e` (beyond GA1's list, or re-read for a correction)

- `scripts/gate-local` (whole file: `:21,65-67` tool root; `:75-88` flock and slot; `:89` record dir; `:97-104` PR identity; `:112-134` exit trap; `:136-160` fetch and worktree; `:171` local config store; `:173,416` record; `:178-192` PostgreSQL and test DB; `:205,299` status begin ×2; `:277-285` prerequisites; `:292-299` classification; `:308-317` script tests overlap; `:412` verdict call).
- `scripts/lib/gate-runner.sh` (`step`, `step_cached`, `gate_want`, `launch`/`join_steps`, `secret_tree`); `gate_report.py` (`:58-89` events, `:116-134` KD1, `:154-182` ready hook, `:217-246` main); `defect_detect.py` (whole); `gate_result_cache.py` (`:13,32,39-41,70-99`); `gate_test_cache.py` (`:48,55-110,130-150`); `gate_status.py` (`:55-100`); `gate_classify.py`; `pr_ready.py` (whole); `plan_tick.py` (`:30-50`); `engine_role.py` (`:30,84-105,138-159`); `train.py` (`:60-81,141-149,222-325`); `train_trigger.py`; `forge_github.py` (`:64-67,73-166,215-228,267-285`); `forge_events.py` (`:185-199`); `github_api.py` (`:84-90`); `commit_check.py` (`:92-166`); `decision_wait.py` (`:65-75`); `structure.py` (`:453-571`); `local_checks.py` (`:181-227`); `gate-stages.json`; `gate-areas.json`; `gate-script-tests.json`.
- Registry defaults: `config/registry/gate.json`, `defects.json`, `train.json`, `plan-tick.json`, `forge-events.json`, `slo.json`, `local-checks.json`, `providers.json`.
- `eaa408de` (diff of `scripts/lib/train.py`) on `origin/claude/merge-train-pr-ready-f7mxzt`.
- `docs/domain/DECISIONS.md` D-065 (row at `:67`); `docs/units/KF3/{audit,plan,retro}.md`; `docs/process/defects/*.yml`.

### GitHub evidence (REST, read-only; nothing posted)

- Forge-events comments of PRs #560–#691: 5 478 events, 347 verdicts on 108 PRs (Q3–Q5), parsed by a read-only sub-agent; raw CSVs stayed in this session's scratch space (not committed: derived data, reproducible from the comments with the method in Q3).
- `commits/2e423b7e/status` (Vercel `failure "Account is blocked."`), `commits/2e423b7e/check-runs` (0), `branches/mod%2Froadmap-integration` and `branches/main` (`protected: false`), `branches/…/protection` (403).
- PR bodies and file lists of #667, #671, #677, #680, #683 (§5 mapping).

### Box evidence (`origin/mod/ga1-evidence`, `docs/programs/gate-excellence/evidence/box-snapshot-20261027-1137/`)

- `sessions.log.txt`: merge lines 459–575 (walls), 575 (#653 1 316 s), 591 (first train run 10:31, `train.enabled=true since 03:04Z`), 627 (retroactive RETRO comments), 637–645 (TR2b/TR2 merges, 11:09 pr.ready by the coordinator, 11:17 duplicate run, 11:19 pause).
- `night-plan.md` §25 (duplicate train run, same owner), §26 (ejections on the box).
- `night-metrics.log.txt` 05:06–10:00 (failed_gates, KF2/KF3 waves).
- `known-defects.json:72` (KF3 drop-database signature "under parallel script-stage load").

### Local measurements (this container: 4 vCPU, 15 GB RAM; base `2e423b7e`; throwaway gate worktree under `/var/tmp/open-university/gate-checkouts/slot1`, removed by the gate itself; caches and records redirected to this session's scratch space; no PR, no Neon, no Vercel)

- `scripts/structure-check --base origin/mod/roadmap-integration` 11.3 s; `+ --pr 691` 19.2 s; per-module timings (Q2).
- `scripts/gate-dev --sha 2e423b7e` cold (614 s, FAILED on two load timeouts, 1 840 CPU-s) and warm (306 s, PASSED, 705 CPU-s): Q1.
- Disk per run (Q13): reports 26 MB / 3 113 files per run, build cache 109 MB. CREATE/DROP DATABASE latency at 1/3/8/16 concurrency (Q9).
- Not found in the snapshot: evidence of the heartbeat misreporting the last merge (brief); no finding is based on it.

### Cited sources that do not exist here

- `/workspace/torre/motor/*` (absent in cloud containers; the GA1 snapshot is used instead).
- `.github/workflows/` (absent by design, D-009).
