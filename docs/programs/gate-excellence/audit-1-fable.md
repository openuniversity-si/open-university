# GA1 — Gate excellence, audit 1 (exploratory)

Base: `mod/roadmap-integration` at `2e423b7e` (TR2 #690 and TR2b #691 merged). Branch `mod/ga1`. Audit only; no code changes, no PR.

## 0. Executive summary

1. The gate proves a change well enough to merge, but it proves the **head sha**, not the content: every new head (RETRO commit, base merge, empty `Plan: N` commit) discards the proof and the whole PR plan re-runs (F-01, F-06; #691 234 s + 220 s for a docs commit; #615 eight gates).
2. On 27/10 the field gate-dev wall was median ≈ 419 s, 16 of 21 runs over the 180 s ceiling, up to 1316 s under 30–40 concurrent sessions; the ceiling only warns and the registry targets (10 s / 15 s) are an order of magnitude away (F-05).
3. A red base made 27–31 of 40 open PRs red for ~6 h; the gate can excuse only script-test failures and re-runs them on the base with a 20-minute timeout; the two registered defects are stale (F-02, F-11).
4. The train's tier 2 ejected three green PRs in under 2 s each because the box had no PostgreSQL; the driver abort has no stage, no class and no event, the train never consults the classifier, preflight exists but is not wired in, and the announced fix (`eaa408de`) is not on base (F-03, F-17).
5. A gate ends and nobody is told; ETA says "no history" on every cloud box because history is a local directory while the durable per-stage data already sits in `engine.step.measured`; three partial dashboards, no board (F-04, F-12).
6. Two proof stores (local `.pass` files vs forge events), no base sha, no toolchain hash, no signature, no GitHub check; the only visible check on every PR is Vercel's "Account is blocked", ignored by hand at each merge (F-09).
7. Caches are keyed on the whole tree, never shared, never evicted (inodes 94–100 % twice), and the train deliberately starts cold; the stage graph is declared but not used to schedule (F-08, F-10).
8. The world-elite shape is one **content-addressed, attested, portable proof** (tree + base tree + toolchain + plan) that pr.ready, the train, merge and release *verify* instead of re-running; the train then re-proves only the combination, on a union plan, with a classified verdict (O-01…O-07).
9. Around it: `gate.started`/`gate.finished` and a board with real ETAs (O-03), base-health adjudication for every test kind (O-08), one merge rule in the registry (O-10), cost accounting and `--explain/--why` (O-12, O-13), and executors that run anywhere for the 100k/day picture (O-14).
10. Five premises need Daniel (§6): proof carry-over for docs-only heads (the RETRO case), tier-2 reuse of attested proofs, a visible GitHub check or silencing Vercel, a paid shared store, and whether `eaa408de` is merged. Fourteen measurements are queued for the deep-dive (§5).

## 1. Current-state map

### 1.1 One driver, six spellings

Every gate is `scripts/gate-local` (422 lines). The other entry points are wrappers that set a mode:

| Entry | Spelling | Mode / record suffix | Who calls it today |
|---|---|---|---|
| `scripts/gate-dev` | `gate-local --dev` (`scripts/gate-dev:9`); `--batch` goes to `gate-batch` (`:4-8`) | `dev`, `<sha>.dev.pass` | sessions (`--pr <n>`), `pr-ready`, the train's tier 2, `ship-tail` |
| `scripts/gate-quiet` | `gate-local` on the working tree, no record | none | sessions before pushing |
| `scripts/gate-db` | `gate-local --db --pr <n>` | `db`, `<sha>.db.pass` | DB-classified PRs, `ship-tail` (frozen) |
| `scripts/gate-batch` | `gate-local --dev --sha <union> --plan-file` (GS1) | `dev` on the combined head | the train (batch) |
| `scripts/gate-noite` | `gate-local --noite` | `noite`, `<sha>.noite.pass` | end of day on `origin/main` |
| `gate-local --tier3 --sha` | full battery, Chromium only, never cached | `tier3`, `<sha>.tier3.pass` | the battery role (M6) |
| `scripts/program-gate` | program-level gate (see §1.6) | — | programs |

Facts about the driver (`scripts/gate-local`):

- **Serialization.** One gate per checkout via `flock` on `.gate/gate.lock` (`:95-101`), then at most `GATE_SLOTS` (default 3) gates per machine via `gate-isolation.sh` (`:104-107`). A second gate on the same checkout waits silently (`"another gate run holds … waiting"`).
- **Head identity.** With `--pr`, head and base shas come from one REST call (`github_cli.py pr view … headRefOid,baseRefOid`, `:114-121`). The head is checked out detached into a fixed per-slot path so lint/tsc caches stay portable (`:141-166`).
- **Database.** Every non-DB gate needs local PostgreSQL: `pgtools_start` or `FAIL local postgres did not start` (`:185-187`), then the per-checkout database is created and its schema dropped (`:188-200`). This is the string behind today's train ejections (see F-05).
- **Stage pipeline** (`gate-stages.json`, 22 stages): six independent checks launch in parallel (secret history, secret tree, no workflows, structure check, generated drift, schema compat, `:271-277`), then DB-path classification picks the dev plan and selection (`gate_policy.py classify`, `:286-296`), then install, script tests, suite union, lint→typecheck, unit, integration, smoke database, builds, browser install, inventory, e2e smoke, performance (`gate-fixed.sh`, `:318-385`). `step` writes one `<stage>.stage.json` with `seconds` (`gate-runner.sh:14-25`); `step_cached` consults the tier-1 result cache for stages declared `deterministic` (`gate-runner.sh:52-69`; only `suite union`, `unit tests`, `integration tests` are deterministic in `gate-stages.json`).
- **Verdict.** `gate_report.py` is the verdict (KD1): it exits 0 when every failing test is a known base defect (`:404-407`). On pass with `--sha` the record `<sha>.<suffix>` is written with `sha, date, nightly, host, kind, db` (`:409-415`). The record is **a local file**, keyed by head sha only: no base sha, no toolchain hash, no stage set, no selection.
- **Status comment.** One live comment per (head, mode) through `gate_status.py` (`gate-runner.sh:9-12`, `gate-local:239`, replanned after classification `:296`). ETA comes from the median of the last `gate.status_history_runs` (5) runs found under this machine's `.gate/records/reports/*/*/stages.json` (`gate_status.py:55-68`); a fresh cloud box therefore always prints `no history`.
- **Budget.** `gate_budget_report` prints elapsed against the ceiling on exit (`:135`); over budget is a warning, never a failure (D-064 (f)).

### 1.2 Observed numbers (box evidence, 2026-10-27, `evidence/box-snapshot-20261027-1137/`)

Source: `sessions.log.txt` (merge lines quote the gate wall time), `night-metrics.log.txt`, `night-plan.md`. BRT = UTC-3.

| Measure | Value | Where |
|---|---|---|
| gate-dev wall time, 21 merged PRs that quote it (s) | 30, 130, 160, 169, 179, 218, 220, 262, 351, 369, 419, 448, 519, 527, 610, 611, 631, 713, 885, 981, 1316 | `sessions.log.txt` merge lines 04:18–10:27 |
| median / p90 of those | ≈ 419 s / ≈ 900 s; 16 of 21 above the 180 s ceiling (D-064 (f)); the ceiling is "noted, not loosened" 14 times | same |
| green → merge latency under the per-PR rule | median 0.8 min, p90 2.0 min, n=58 since 02:00 | `sessions.log.txt:591` |
| merges recorded in the log | 149 lines | same |
| "re-gate" asks in the log | 38 | same |
| base-defect waves forcing re-gates | KF2 (countries.test.ts, generate.test.sh): 14 PRs told to merge base + re-gate; KF3 (gate-heavy-db, claude-session load-sensitive): ~12 PRs; `failed_gates=~31` at 05:45, `~27` at 10:00, all "red only on base defects" | `night-metrics.log.txt` 04:55–10:00 |
| RETRO-after-green re-gates | #629, #627 "post-gate retro commit re-gated"; #628, #582 "retro commit is the gated head"; #691 green 14:02Z on 51bce93f, RETRO 1fb11d94 re-gated and merged 14:07Z | `sessions.log.txt:451,465,473,483,637` |
| gate result never announced | KF2 #657: "gate result missing 28 min after STATUS" (07:05), "silent 50 min" (07:27) | `night-metrics.log.txt`, `night-plan.md:16-17` |
| train tier-2 ejections | #607 25c1df7b, #605 791bb476, #690 0aeac030 at 11:13–11:16 BRT, cause `local postgres did not start / missing toolchain: postgres`; box has no PostgreSQL; heads "out of the train queue for good (pr.ejected)" | `night-plan.md` §26, `sessions.log.txt:644` |
| duplicate train runs | two `train.py run --owner hb-1111` at 11:15; same owner = lock renewal, not refusal; log empty (block-buffered stdout); queue phase 8 min (config reload per call, fixed by TR2 memo `8d6b52b4`) | `night-plan.md` §25, `sessions.log.txt:591` |
| pr-ready refusal the gate could have caught | #615 refused "plan item 3 unticked"; session told to push an **empty** `Plan: 3` commit and re-gate (contradicts "no WIP commits") | `sessions.log.txt:639` |
| idle green PRs | #605, #607 green 06:54Z, then 219 commits behind; #615 "green but 284 behind" | `night-metrics.log.txt` 04:36, 04:55 |
| Vercel check | "Account is blocked" red on every PR; "not a gate input", ignored by hand each merge | `sessions.log.txt:452,459,529`, `night-metrics.log.txt` 06:45 |
| box disk | inodes 94% at 10:00, 100% at 17:59 the day before; worktrees pruned by hand (`tools/wt-prune.py`) | `night-metrics.log.txt`, `sessions.log.txt:36-44` |
| train log of run 11:11 | `EXIT 143` only | `train-run-1111.log.txt` |

Comparison with what the code expects: `gate.tier1_target_s` = 10 and `gate.slow_median_s` = 15 (`config/registry/gate.json:9-18`), ADR-28 warning 90 s, D-064 (f) ceiling 180 s, `train.tier2_timeout_s` = 1800 (`config/registry/train.json:150-152`). Measured medians are 25–40× the tier-1 target. The reference measurements in `docs/operations/local-gate.md:200-208` (cold single-unit PR 188.9 s, warm batch 152.3 s, full dev without plan 417.9 s) match the lower half of the field distribution; the upper half (600–1316 s) is the box under 30–40 concurrent sessions and load-sensitive tests (KF3's `gate-heavy-db`, `claude-session`).

### 1.3 Stage model and selection

- **Declared graph vs. real schedule.** `gate-stages.json` (version 3, 22 stages) declares `needs`, `resources`, `deterministic`, `inputs`; `gate_graph.py:47-65` validates it and `gate_graph.schedule` (`:87-131`) is a `ThreadPoolExecutor` scheduler. The gate does not use it for stages: the schedule is hand-written bash (`launch` + `join_steps`, `gate-runner.sh:94-114`; `gate-fixed.sh:100-147`). Only script tests go through the Python scheduler (`gate.script_tests_concurrency` = 8). The JSON is checked for name coverage only (`gate_graph.check`, `:154-161`). **Two sources of truth, one decorative.**
- **Three selection layers for a dev PR gate.** (1) *Area plan*: changed paths of `base...head` → areas in `gate-areas.json` → stage groups plus the six `always` stages (`gate_policy.py:84-85`, `gate_areas.py:259-271`); an unmapped path or an empty diff means the full plan. (2) *Unit selection*: `gate_select.py:45-105` picks the tests of changed units plus transitive `requires` dependents, plus `vitest related`; it fails closed to `full` on `gate.full_battery_globs`, on any non-doc path outside `apps/web/src/**`, or on an unattributed path (`:76-86`). (3) *Legacy browser impact* (`gate-impact.py`, hard-coded OWNERS table) only in the legacy `pr` mode. Dev mode always runs the 40-case smoke manifest (`gate-smoke.json`). `gate_noite.candidates` has its own fourth glob table (`gate_noite.py:41-48`).
- **Prerequisites run before classification.** The six `always` stages (`gate-local:271-277`) start before the plan exists (`:286-296`), so even a docs-only head pays the structure check (24–33 s measured, `local-gate.md:203-206`) plus two gitleaks scans, drift and schema compat.
- **Concurrency guards.** Per-checkout `flock` (`gate-local:95-101`); `gate.slots` = 3 per machine; `gate.heavy_db_slots` = 2 for `integration tests`, `smoke database`, `db schema/migrations` (`gate-fixed.sh:19-28`, `gate-isolation.sh:84-107`). No per-stage timeout exists in `step` (`gate-runner.sh:13-48`); the only hard timeouts are the train's 1800 s and the battery's 3600 s.
- **Failure classes.** `gate_classify.py:33-38` labels a red stage `env` (install, browser install/inventory, or an ENV regex such as `toolchain: ` without a CODE hit), `contract` (migration/db-schema constraint codes, "contradict|conflicting rules") or `code`. The class is printed and carried in `engine.step.measured` and the verdict (`gate_report.py:65-67`), but **changes nothing**: same exit 1, no retry, no `env.drift` event, not shown in the status comment.
- **Known defects (KD1).** `gate_report.py:116-134` turns a red stage into PASS when the same failure signature reproduces on the base (`defect_detect.py`); the verdict is `MERGEABLE — only known base defects`. This is the lever that let 14 KF2-blocked PRs merge on 27/10 ("only red a known base defect", `sessions.log.txt` ×11).

### 1.4 What "proof" is today

Three artifacts claim to be the proof, with different keys and different readers:

| Artifact | Key | Carries | Reader | Portable? |
|---|---|---|---|---|
| `.gate/records/<sha>.dev.pass` (`gate-local:409-415`) | head sha + mode | sha, date, nightly, host, kind, db | `merge-phase:97-132`, `ship_tail.record_ok` | no: a local file, deleted on failure or at the start of a rerun (`:129,173`) |
| `gate.passed` v3 event (`gate_report.py:58-89`; `contracts/events/gate.passed.v3.json`) | natural key repo/pr/sha/plan/input_hash, `input_hash` = sha256(sha, mode, expected stages) (`:73-76`) | stages with duration and class, missing_stages, cached_tests, known_defects, failing_tests; `unit` null; **no base sha, no lane** | `pr_ready.py:45-50`, `train.py:64-81`, `slo.py`, `stall_report.py` | yes: a `<!-- forge-events v1 -->` comment on the PR; readers page comments each time |
| gate-status comment (`gate_status.py`) | first line marker + sha + mode | human table; verdict JSONL collapsed | humans, nothing else | yes, but found only by paging each PR's comments |

Consequences: a proof cannot say against which base it was green; a new head (even a doc) has no proof; a machine other than the one that ran the gate cannot read the `.pass` file; the frozen tail trusts files while the train trusts events (`EVENTS.md:190-192`). The verdict is authenticated only by comment author association and the deterministic `event_id` (`EVENTS.md:130,176`).

### 1.5 Outputs, visibility and events

- **Status comment** (GV1): one per (PR, head, mode); `begin` (twice: before and after classification, `gate-local:239,296`), one PATCH per stage at most every `gate.status_min_interval_s` = 15 s, forced final; 5–15 REST calls per gate; failures never change the verdict (`gate_status.py:202-213`), but a failed PATCH falls through to creating a duplicate (`forge_github.py:222-228`). Content: stage table with state, duration, expected; final adds failing tests with signatures and known-defect marks. Missing: log path or run id, the D-027 class, a link to the session, and any ETA on a fresh machine ("no history", `gate_status.py:94`, because `history()` reads only this machine's `.gate/records/reports`, `:55-68`).
- **No check run or commit status.** The cloud token gets 403 on status writes (`EVENTS.md:176-178`, `forge_github.py:3-5`); nothing in `scripts/` calls check-runs or statuses. GitHub's "checks" area on a PR shows only Vercel ("Account is blocked" on every PR since the account block), which every merge decision had to ignore by hand.
- **Events emitted by the gate**: `engine.step.measured` per stage, `defect.*` on the repository channel, `gate.passed|failed`, then `pr.ready` and a detached `scripts/train run` (Transport v0, `gate_report.py:154-182`, `train_trigger.py:24-33`). **Promised but never emitted**: `env.drift` (`EVENTS.md:38`), `gate.slow` (`EVENTS.md:65`; `forge_events.gate_slow` has no caller), `slo.breached` (`scripts/slo evaluate` is called by nothing), `gate.started` (does not exist), `session.ended|failed` (the coordinator folds them). Durable per-stage history **does exist** in `engine.step.measured` and `slo.step_stats` already computes p95 per step (`slo.py:77-86`), yet ETA ignores it.
- **End of gate notifies nobody** except the shell that ran it (`gate-local:408-421`); `coordinator`'s notify port is stderr (`coordinator_launch.py:108,125`); `stall-report` is on demand (`scripts/stall-report:3`). KF2's "gate result missing 28 min" is the direct result.
- **Macro view**: `scripts/dashboard` writes `.gate/dashboard/slo.md` with four SLO rows that read `no_data` until 20 tier-1 verdicts exist (`slo.json`, `min_samples`); `scripts/stall-report` lists open PRs with their *last finished* verdict; a running gate is invisible to both. Three partial tools, no board.
- **Failure reporting**: console `FAIL <stage> (t; exit; log: /tmp/gate-local-<slug>.log)` plus 8 grep'd lines and the class (`gate-runner.sh:30-40`); the `/tmp` copy is shared by all three slots and overwritten. Full logs live in `.gate/records/reports/<sha>/<mode>-<ts>/` (AGENTS.md:43 says `.gate/logs/`, which does not exist). Signatures are heuristic first-error lines (`gate_failures.py:22`), capped at 50, posted to the PR without a `redact()` pass.

### 1.6 Consumers and the flow

```
 session (lane)                 gate-dev --pr n                     forge (PR comments)              train (box)                       merge / release
 ──────────────                 ───────────────                     ───────────────────              ───────────                       ───────────────
 push head H ──────────────▶ fetch head+base oids (REST)
                             flock + slot; worktree H
                             6 always stages ∥ ──▶ classify(base...H) ──▶ plan, selection
                             install → lint→tsc, unit, int, smoke-db, builds, e2e smoke, perf
                             gate_report: verdict  ─────────────▶ engine.step.measured ×N
                             known defects (KD1)                   gate.passed|failed v3 {sha, plan, stages, input_hash}
                             <sha>.dev.pass (local file)           gate-status comment (human)
                             ready_hook: HEAD==H, plan ticked ───▶ pr.ready {sha, lane_id, evidence=event_id}
                             train_trigger: `scripts/train run` detached ─────────────────────────▶ queue: pr.ready ∧ head==H ∧ evidence ok ∧ ¬refused
                                                                                                    ownership(lane_id) → pr.refused
                                                                                                    combine onto tip(base) → pr.conflicted
                                                                                                    tier 2 = gate-dev --sha combined (full, uncached)
                                                                                                    red → bisect → pr.ejected culprit (FAIL anything)
                                                                                                    green → gh merge --match-head-commit each ──▶ merge commit on mod/roadmap-integration
                                                                                                                                                  release = one merge into main (frozen D-054)
                                                                                                                                                  merge-phase needs <sha>.dev.pass on THIS machine
 contracts at each hop:  H exact (sha) ──▶ (sha, plan, stages) ──▶ (sha, lane_id, evidence) ──▶ head==sha at queue time; base = tip now, unrecorded ──▶ exact head + local file
 what is lost:           base sha, toolchain hash, class of a red run, log artifact, lane (null unit), signature
```

Who consumes what (`EVENTS.md:344`, code cited above): `pr_ready` → `gate.passed` on the PR channel; `train.queue_entry` → `pr.ready` + its `evidence`; `slo`/`stall_report`/`branch_age` → `gate.*`, `pr.*`; `merge-phase`/`ship-tail` → `.pass` files; GV1 comment → humans; nothing consumes the class, `cached_tests` or `input_hash`.

### 1.7 Other entry points

- `scripts/gate-batch` (GS1) builds a union commit with `git merge-tree`/`commit-tree` (`gate_batch.py:55-69`), gates it once with the union plan, and attributes the result per PR (`batch.json`). Documented as the train's tier 2 (`gate_batch.py:18`, `local-gate.md:196`), **but the train calls `gate-dev --sha` instead** (`train.json:133-139`), full plan, fresh cache dir per run (`engine_role.py:147-159`, `train_git.py:85-90`).
- `scripts/gate-quiet` is `gate-local` with no mode on the working tree, i.e. the legacy `pr` plan: shellcheck, script tests, `db schema/migrations`, Chromium **and WebKit** (`gate_policy.py:22-27`), not the "lint, typecheck, unit tests and build" AGENTS.md promises.
- `scripts/gate-noite` runs `--noite --sha origin/main --pr <last merged>` and writes `noite.json`/`noite.md` (`gate_noite.py:78-85,120`). `--tier3` is the battery role's full Chromium battery, never cached (`battery.json:148-169`). `scripts/program-gate` is not a test gate: it checks that every unit of a program merged and its goal metric (`program_gate.py:48-56`).

## 2. Findings ranked by impact

Ranking: impact on merges per hour first, on reliability of the verdict second. **Class**: fact (cited code or log), inference (derived), hypothesis (not provable from what I read). **Stages**: which engine stages the finding hurts.

### F-01 The proof is bound to a head sha, so every new head throws it away (fact)

- `.dev.pass` is `<sha>.<mode>` (`gate-local:409-415`); `gate.passed` natural key is repo/pr/sha/plan/input_hash with `input_hash` = sha256(sha, mode, stages) (`gate_report.py:73-76`); `pr_ready` and the train need a `gate.passed` for the **exact** sha (`pr_ready.py:45-50`, `train.py:76-78`). Nothing carries a tree hash or a base sha except the train's own `tree_sha` after merging (`train.py:282-295`).
- Classification diffs `base...head`, the whole PR (`gate_policy.py:80-84`), so a docs-only **commit** on a code PR re-runs the PR's whole plan. #691: run 1 on 51bce93f 234 s, retro commit 1fb11d94 → run 2 220 s with the same structure check (82 s) and script tests (107 s, 12 of them cached). #690: 146 s → retro 46 s → base merge 85 s. Only a docs-only **PR** gets the six-stage plan (`gate-areas.json documentation`, `gate_select.py:87-89`).
- Base merges are the other head changer: #605 ran 5 gates (337, 350, 348, 197 s), #607 6, #615 8, all green on the first code head between 07:00 and 07:14Z and still open at 14:19Z. Lint, typecheck, unit and integration caches hash the whole tree (`gate_result_cache.py:76-79`, inputs `**` in `gate-stages.json:91,104`), so a base merge or a `.md` change misses all of them.
- Impact: at least 2 full gates per PR by construction (code head + RETRO head), plus one per base move. With k lanes landing on one branch under a 0-behind rule, each merge invalidates every other green head: O(k²) gate runs (inference). The train then re-proves the same content a third time (tier 2, uncached, `train.json:133-149`).
- Stages: session, pr.ready, train, merge, release.

### F-02 A red base turns every open PR red, and the gate can excuse only script tests (fact)

- KF2 (countries.test.ts, generate.test.sh) and KF3 (load-sensitive script tests) made `failed_gates=~31` of 40 open PRs at 05:45 and `~27` at 10:00, "red only on base defects" (`night-metrics.log.txt`); 14 then 12 PRs were told to merge base and re-gate after each fix; throughput "gated on KF2 merge" for ~6 h (04:55–11:22Z).
- KD1 adjudication applies only to `defects.stages = ["script tests"]` (`config/registry/defects.json:10-24`); the vitest failure countries.test.ts could not be excused, so 14 green-by-content PRs waited. For script tests it re-runs the failing test on the base in a worktree with `defects.rerun_timeout_s` = 1200 s, inside a gate with a 180 s ceiling (`defect_detect.py:72-98`, `gate_report.py:116-134`).
- The two registered defects (`KD-024bbecb`, `KD-4db6e693`) are already fixed on base but stay `open`: verification runs only for `resolved` (`defect_detect.py:138`), there is no `open>verified` transition, both were hand-seeded (`run: kd1-seed`).
- Impact: a single bad merge costs every open lane one full re-gate plus hours of waiting; the fix PR itself (KF2 #657) went through conflict, two stalls and a relaunch. Stages: session, pr.ready, train (the train would have refused all of them), coordinator.

### F-03 The train turns an environment failure into a PR culprit, and nobody checked the box first (fact)

- `engine_role.CommandGate.run` reads the first `^FAIL (.+?)$` line as the stage (`engine_role.py:30,156-157`); `train.bisect` blames the oldest member when every probe is red (`train.py:311-324`); no `train*.py` or `engine_role.py` calls `gate_classify`, although `gate_classify.ENV` already matches `toolchain: ` (`gate_classify.py:18-21`).
- 14:13:02Z #607, 14:14:29Z #605, 14:16:52Z #690: `pr.ejected cause=culprit`, log `FAIL local postgres did not start … GATE TOTAL: 1.964s … missing toolchain: postgres` (`gate-local:185-187`, `scripts/cloud/postgres.py:42,154`). Each ejection took under 2 s and put a green head "out of the train queue for good" (`train.py:61,73`; `night-plan.md` §26).
- The class fix (TrainHalt on class env, TR2 plan item 7, commit `eaa408de`) is **not** in the merged #690 (merged head 0aeac030; the comment at 14:20:29Z announces it after the merge). It is not on base 2e423b7e.
- The abort happens **before any stage**: `gate-local:185-187` exits 1 from the driver, so no `.stage.json`, no `gate_classify` line (it runs only inside `step`, `gate-runner.sh:39`) and no `gate.failed` event (the exit trap calls `gate_report.py` with three arguments, `gate-local:126-127`; evidence needs five, `gate_report.py:233`). Even if classified, the ENV regex (`gate_classify.py:19-22`) matches `toolchain: ` but not `postgres did not start`.
- `preflight.database_problems()` reproduces exactly these checks and would have named the gap (`scripts/lib/preflight.py:87-103`), but preflight is wired only into `ship-tail` (`ship_tail.py:13`), not into `gate-local`, `gate-dev`, `gate-batch` or the train. The gate discovers the missing cluster after taking the flock, a slot and a worktree.
- The cluster itself lives inside one checkout's `.toolchain/pgdata` and every other checkout reuses whatever answers on 54322 (`scripts/cloud/postgres.py:155-158`, `env.sh:129`): a worktree-invoked gate, a deleted first checkout or a foreign listener all produce one of these strings.
- Impact: with the train on, a box drift ejects one green PR per batch until someone notices; the ejected heads need a new commit to re-enter. Stages: train, merge.

### F-04 A gate ends and nobody is told; a running gate is invisible off the machine (fact)

- The only wake is the exit of the shell that ran the gate (`gate-local:408-421`); `pr.ready` → detached `scripts/train run` is the only push-style handoff (`gate_report.py:154-182`). The coordinator's notify port is stderr (`coordinator_launch.py:108,125`). No `gate.started` event exists; `stall-report` sees only the last finished verdict; `scripts/dashboard` reads `no_data` until 20 tier-1 verdicts (`slo.json min_samples`).
- ETA: `history()` reads this machine's `.gate/records/reports` (`gate_status.py:55-68`), so cloud gates always print "no history" (`:94`), while per-stage durations already exist durably in `engine.step.measured` and `slo.step_stats` computes p95 from them (`slo.py:77-86`).
- Observed: KF2 #657 "gate result missing 28 min after STATUS", then "silent 50 min" (07:05, 07:27); the heartbeat pinged, relaunched a continuation session and only then learned the gate had passed. Lane sessions on #605 and #607 reported at 14:19Z that `pr.ready` "has not been emitted" while the event log shows it emitted at 14:08Z: a session cannot read its own PR's state cheaply.
- Impact: every gate costs a human or a session polling; wasted Claude quota while waiting; wrong decisions on stale state. Stages: session, coordinator, Daniel, train.

### F-05 The gate takes 2–7× its ceiling, and the ceiling has no teeth (fact)

- 16 of 21 quoted gate-dev walls exceed 180 s; median ≈ 419 s, max 1316 s (§1.2). GS2 #683 measured p95 879 s on #653's runs. Targets in the registry: `gate.tier1_target_s` = 10, `gate.slow_median_s` = 15 (`gate.json:9-18`); ADR-28 90 s, ADR-33 "2–3 min", D-064 (f) 180 s. Three budgets in docs, none enforced: `gate_budget_report` only warns (`gate-budget.sh:14-39`), `gate.slow` is never emitted.
- Where the time goes (from status tables): structure check 15 s (#690) / 82 s (#691) / 1m51s–3m18s (#671, #683 under load); script tests 107–121 s warm, 321 s cold (GV1), 12m16s on #683; the six prerequisites run **before** classification and cannot be narrowed (`gate-local:271-296`); install + build + browser install each run per fresh worktree. No per-stage timeout (`gate-runner.sh:13-48`).
- Load sensitivity: `gate-heavy-db.test.sh` (expects a CPU-count-dependent cap) and `claude-session.test.sh` (drop database 30 s) failed on ~12 PRs when 30–40 sessions shared the box (`known-defects.json`, KF3). The gate measures timing (`performance tests`, read-latency 1025 > 1000 ms on #634) on a box whose load it does not control.
- Impact: 7–20 min of wall per gate × 2–8 gates per PR; sessions idle on quota meanwhile. Stages: session, train (tier 2 = same cost again, timeout 1800 s).

### F-06 pr.ready refuses for reasons that force a new head (fact)

- `ready_after_gate` refuses unless every plan item is ticked by a `Plan: N` trailer in `base..HEAD` and the checkout HEAD equals the gated sha (`pr_ready.py:67-91`, `plan_tick.py:39-49`). #615 was refused "plan item 3 unticked" and the session was told to push an **empty** `Plan: 3` commit (`sessions.log.txt:639`; head f12b9b34 is that commit), then run the 8th gate (7m08s). #690 run 1 printed `pr.ready: not emitted (plan: items not ticked by a commit: 6)` because the RETRO is the last plan item, so the first green head of every unit can never be ready.
- `pr.ready` also derives `lane_id` from files at the merge base (`pr_ready.py:35-42`); `None` makes every unit foreign and `pr.refused` follows (`train_ownership.py:42-56`); #690 cf401301 and #615 f12b9b34 were emitted with `lane_id: null` and a refused head never re-enters (`train.py:61,73`; TR2 F5).
- Impact: a plan-completeness rule, which the structure check could verify on the body, costs a gate run and an empty commit that D-022 forbids. Stages: pr.ready, train.

### F-07 Three "behind the base" rules, none in the registry, and green PRs idle for hours (fact)

- `commit_check.rebase_errors` demands a merge commit of the base when behind (`commit_check.py:92-104`); `merge-phase:95` demands GitHub `MERGEABLE`; the briefs, BD1 (#667 `merge.max_behind_base`) and MQ1 (#680 "0 behind") demand 0 behind, a rule absent from base code. The train has no distance rule at all: the combined head is the merge.
- #605 green 07:00Z, #607 07:05Z, #615 07:14Z; by 04:36 BRT they were "~219 commits behind"; at 11:09 BRT two were finally fed to the train and ejected (F-03). Under the per-PR rule the green→merge latency was median 0.8 min, p90 2.0 min (n=58); the three outliers waited 7 h because their base went red (F-02) and then the merge path was frozen.
- Impact: unclear invariant → every merger implements its own; cost of 0-behind is one full gate per base move. Stages: merge, train, pr.ready.

### F-08 Caches are keyed too wide, never shared, never evicted, and unmeasured (fact)

- Keys: lint/typecheck `tree_digest(root)` over the whole tree (`gate_result_cache.py:70-79`); unit/integration inputs `**`; script tests keyed by hand-kept `covers` lists (79 tests) plus registry pin strings, not actual tool versions (`gate_test_cache.py:62-98`). The local registry change log `.tower/config` is gitignored and in no key, yet `OU_CONFIG_STORE=file` makes it drive behaviour (`gate-local:171`, `config.py:256`).
- Sharing: markers in `~/.cache/open-university/` per user per machine; the storage port has one adapter, `local` (`providers.json:98-100`); the train creates a **fresh** `GATE_BUILD_CACHE_DIR` per run (`engine_role.py:147-159`); `next/cache` incremental state is deliberately not stored (`gate-build.py:103`), so every build miss is a cold compile.
- Hygiene: no eviction anywhere (`gate-builds/<target>-<key>` full Next outputs, `reports/<sha>/<mode>-<ts>/` with browser artifacts, `source-scan.XXXXXX` tarballs, `/tmp/gate-local-*.log`); box inodes 94–100% twice in 24 h, pruned by hand. Race: `gate-build.py:116-117` renames onto an existing entry. Secret-scan state is one machine-wide slot (`gate_speed.py:142-175`) that thrashes across branches.
- Telemetry: `cached_tests` and `stages.json.cached` are listed; no hit rate, seconds saved, or trend exists. `local-gate.md:62` says "No test result is cached", contradicted by `:190-192` and the code.
- Impact: tier-1 reuse is near zero on long-lived PRs; tier 2 reuse is zero by design; disk is the recurring outage. Stages: session, train, box.

### F-09 Two proof stores, no base binding, no signature, and the only visible check is Vercel's "Account is blocked" (fact)

- `merge-phase` and `ship-tail` read per-machine `.pass` files; `pr-ready` and the train read forge events (`EVENTS.md:190-192`); HD1's hermetic `hermetic=pr-<n>` record would be refused by the frozen tail by design. A `gate.passed` is authenticated by comment author association and a deterministic `event_id` (`EVENTS.md:130,176`): anyone with a trusted association can mint one; no log artifact hash, no base sha, no toolchain hash.
- No check run or commit status is written (403 for the cloud token, `forge_github.py:3-5`); `get_check_runs` returns 0 on every PR. The one status on every head is Vercel `failure "Account is blocked."`, which every merge decision had to ignore by hand (#690 comment 14:09:57Z; 11 merge lines in `sessions.log.txt`).
- Impact: the merge rule cannot be checked by GitHub's UI or by a second machine; a visible red that means nothing trains humans to ignore red. Stages: merge, release, Daniel.

### F-10 The stage graph is decorative and the entry points disagree with their docs (fact)

- `gate-stages.json` + `gate_graph.schedule` exist; the real schedule is bash `launch`/`join_steps` (`gate-runner.sh:94-114`, `gate-fixed.sh:100-147`); only script tests use the scheduler. Four selection tables (`gate-areas.json`, `gate_select`, `gate-impact.py` OWNERS, `gate_noite.candidates`).
- `gate-quiet` runs the legacy `pr` plan with shellcheck, script tests, `db schema/migrations` and Chromium **plus WebKit** (`gate_policy.py:22-27`), not AGENTS.md's "lint, typecheck, unit tests and build". `gate-batch` is documented as the train's tier 2 (`gate_batch.py:18`, `local-gate.md:196`) but `train.tier2_command` is `gate-dev --sha` (`train.json:133-139`). `gate_status begin` runs twice per gate (`gate-local:239,296`).
- Impact: changes to the graph do not change the schedule; a contributor cannot trust the declared dependencies; reviewers of GS2-style changes edit bash. Stages: gate internals, GS2.

### F-11 Two policies for a failing test: KD1 flips FAIL to PASS, quarantine keeps it blocking (fact)

- `defect_detect.apply_to_report` rewrites the stage and `report.result` to PASS when every failure is a known base defect (`defect_detect.py:158-169`), printing `GATE: PASSED`; D-065 and `local-gate.md:180,373` say nothing is ever loosened. `quarantine.py:14` keeps a flaky test blocking. Which policy applies depends on which mechanism saw the failure first.
- Impact: the verdict's meaning differs per failure path; a `MERGEABLE — only known base defects` head can carry a regression masked by a same-signature base failure (hypothesis: not observed, but the signature is a 160-char first-error line, `gate_failures.py:22`). Stages: merge, train.

### F-12 Promised events and docs that the code does not honour (fact)

- Never emitted: `env.drift` (`EVENTS.md:38`), `gate.slow` (`EVENTS.md:65`; `forge_events.gate_slow` has no caller), `slo.breached` (`scripts/slo evaluate` is called by nothing), `session.ended|failed` (folded by `coordinator.py:42-45`), `pr.pushed`, `gate.started` (does not exist).
- Docs drift that misleads sessions: AGENTS.md:43 `.gate/logs/` (real: `.gate/records/reports/`); ADR-24 paths and bases (`~/.local/state/…`, `main|rewrite/v1`); ADR-28 90 s; `local-gate.md:4` "ADR-33 replaces ADR-28" without the new ceiling; STRUCTURE.md:100 "PRs are strictly serial (D-020)" after D-065 lanes.
- Impact: consumers wait for signals that never come; a new session plans from the wrong map. Stages: coordinator, dashboards, sessions.

### F-13 The box is the unit of scale, and it saturates at about one gate a minute (inference from facts)

- `gate.slots` = 3 per machine, `heavy_db_slots` = 2, one PostgreSQL instance on 54322 for every checkout, `slot_poll_s` = 1 busy loops (`gate-isolation.sh:53,77,86,105`), `/tmp/gate-local-<slug>.log` shared by all slots, per-checkout flock. Tier 2 runs on the same box as the lanes' tier 1.
- Arithmetic: 3 slots × ~3–7 min per gate ≈ 0.4–1 gate/min/box; 1000 PRs/day at ≥ 2 gates each needs ≈ 1.4 gates/min sustained, 100k/day needs ≈ 140/min. `EVENTS.md:333-339` names "tier 2 in shards" only at 10×; the reach-1000 program has no sharding or shared-cache unit.
- Impact: the current design cannot reach the program goal by tuning; it needs gates that run anywhere and proofs that travel. Stages: all.

### F-14 Comment hygiene costs API calls and can fail a gate (fact)

- One status comment per (head, mode) plus one forge-events comment per verdict: #615 with 8 heads carries ≥ 16 gate comments; stale heads are never marked superseded. A failed PATCH creates a duplicate (`forge_github.py:222-228`). Signatures are posted without `redact()` (`gate_status.cell` only strips pipes). A verdict over 60000 chars raises and **fails the gate with class env** (`forge_github.py:68`, `gate_report.py:239-242`). `github_api` treats 403 as fatal auth, so a secondary rate limit under 40 parallel gates fails verdict recording (`github_api.py:88-90`). Every `publish` re-reads up to 20 pages to dedupe (`forge_events.py:194`).
- Impact: GitHub is a single point of failure for the proof store, with growth proportional to heads × runs. Stages: pr.ready, train, dashboards.

### F-15 The gate is used as the discovery loop for structure failures (fact)

- First runs red on structure check: #607 29b042b1 (06:56Z), #607 f3f77b4b (13:07Z, a STATUS comment tripped the "decision-wait rule", fixed by a `Decision:` comment), #671 3943619e (malformed `Premises:` line + behind base), #677 ab2552fc (new literals, stale baseline), #683 6f9a792c (own literals/manifests), CO1, GK1 (`night-metrics.log.txt` 03:21, 03:42). TR2/TR2b retros: `structure_fast` passed locally, the full check failed twice on literals (LT1) and cross-unit imports (U2) (`TR2/retro.md:29-34`).
- `local-checks.json` runs only `structure_fast` (68 ms here); the literal census and import check live only in the gate's structure check (15–198 s).
- Impact: one wasted full gate per unit on average before the first green; the structure check also depends on PR metadata (comments, body), so it cannot be cached by tree. Stages: session, gate.

### F-16 The train's merge loop has single points of failure the gate could pre-empt (fact)

- A forge refusal on one member breaks the loop and leaves the rest unmerged though proven (`train.py:268-275`); a base move between build and merge halts with nothing merged (`:265-267`); approvals compare GitHub logins to lane ids, so cross-lane changes can never pass (`train_ownership.py:55-56`); lock owner strings are reused (`--owner hb-1111` twice = renewal, `night-plan.md` §25); `config.get` reloads cost 8m12s per queue build before `8d6b52b4`.
- Impact: the train cannot yet be the only merger; every one of these is a reason a green proof does not land. Stages: train, merge.

### F-17 The gate is not hermetic and its environment is not attested (fact)

- Network during a gate: `git fetch`, `pnpm install` (store outside the checkout, no `store-dir`), `playwright install chromium` each run (`gate-local:365`), `pnpm media:cache --from snapshot` from the real media origin on a miss (`gate-fixed.sh:79-81,126-128`), `pip install fonttools[woff]` from PyPI inside e2e (`scripts/cloud/fonts.py:21-26`). `hermetic.py` denies network only in Python script-test processes (`hermetic.py:82-107`); vitest, Playwright and the shell are unguarded; `hermetic_check.py` is a static lint.
- Attestation: the pass record has no toolchain hash; cache keys use registry pin strings and `node -v`, never the observed PostgreSQL, gh, gitleaks or Vercel versions (`gate_result_cache.py:33-34`); preflight's stamp short-circuits version probes once it matches (`preflight.py:49-55`); Vercel CLI is installed with `npm install --no-package-lock`, transitive deps unpinned (`scripts/cloud/toolchain.py:168-170`). A stale `.toolchain` yields the same keys as a correct one.
- Residue: `tower_test_<hash>` databases are created per checkout path and never dropped (only `tower_test_tmp_*` and `tower_test_g*` are, `test_db.py:130`, `int-teardown.ts:32`); `/tmp/tower-worktrees/<id>` and `gate-builds/<target>-<key>` are never removed; `/tmp` paths are `chmod 777` for uid sharing (`gate-isolation.sh:134,148`); trust auth on loopback lets any local uid drop any database (`postgres.py:174`).
- Impact: a verdict depends on the network and on an unrecorded machine state; "it passed on my box" is unverifiable, which is exactly what the train needs to verify. Stages: train, release, box.

## 3. Opportunities (the world-elite picture)

The thread that joins them: **the gate should produce a portable, content-addressed proof once, and every later stage should verify that proof instead of re-running the work.** Size: S ≤ 1 PR, M 2–4 PRs, L a program step. Each item names what it unlocks, its dependencies and its risk.

### O-01 Content-addressed proof (L, the keystone)

Record every verdict against `(head_tree, base_tree, plan, selection, toolchain_id, defects_snapshot)` and keep the head sha as a pointer, not the key. `tree_digest(root, inputs)` and the train's `tree_sha` already exist (`gate_result_cache.py:49-67`, `train.py:282-295`); `toolchain_manifest.install_id()` is the toolchain hash (`toolchain_manifest.py:79-83`).
- Unlocks: a RETRO or any docs-only commit **carries the proof** (the tree of every stage input is unchanged; D-NNN needed, this is Daniel's "the gate must handle it"); a base merge that changes no stage input carries it too; the train can check "this combined tree equals the proven tree plus a proven base delta" instead of re-proving; `merge-phase` and `ship-tail` can accept a proof made on another machine.
- Dependencies: O-02 (per-stage inputs), O-05 (attestation). Risk: an under-declared input list produces a false carry-over; mitigate with fail-closed inputs (`**` stays the default) and a nightly full re-prove that checks carried proofs (tier 3 already exists for this).

### O-02 Delta-aware stage inputs and a scheduler that obeys them (M)

Give every stage declared `inputs` and let `gate_graph.schedule` run the stages (it is written and tested; `gate_graph.py:87-131`). Narrow lint/typecheck/unit/integration from the whole tree to `apps/web/**` + configs + lockfiles + `units/**`; declare `generated drift`, `schema compat`, `secret scan (tree)`, `no GitHub Actions workflows` deterministic; split `structure check` into a tree part (cacheable) and a PR-metadata part (body, comments, plan ticks: cheap, uncacheable). Add a per-stage timeout from the registry.
- Unlocks: docs-only deltas cost the PR-metadata check only; a base merge misses only the stages whose inputs the base touched; GS2's critical-path work (#683) lands on a real graph instead of bash. Risk: a wrongly narrowed input (mitigation as O-01).

### O-03 Gate ledger and board: `gate.started`, `gate.finished`, ETA from history, one view (M)

Emit `gate.started` with the plan and expected durations, `gate.finished` as the wake for the producer, the coordinator and the train; compute expected durations from `engine.step.measured` (the data is already there, `slo.step_stats`) keyed by stage × plan kind; one `scripts/gate-board` (or a single pinned issue the gates edit) that lists every open PR × running/last gate × stage × ETA × result × failing tests × cached tests. This is GV1 "something better" (Daniel 11:05/11:09): design it with Daniel, not as a unit.
- Unlocks: no polling; sessions stop burning quota waiting; the heartbeat reads one board; "no history" disappears on cloud boxes. Dependencies: none hard; O-06 for a channel other than PR comments. Risk: another comment per gate unless the board replaces the per-head comments (mark superseded heads).

### O-04 Classify before you blame: preflight in the gate and an infra verdict in the train (S–M)

Run `preflight.database_problems()`/`browser_problems()` at the top of `gate-local` and in `engine_role.CommandGate` before tier 2; emit `gate.failed class=env` with `missing_stages` from the driver aborts (the exit trap today emits nothing); let the train raise `TrainHalt` on class env/contract and emit `env.drift` (promised in `EVENTS.md:38`); land TR2 item 7 (`eaa408de`) if it is still unmerged. Give the train a persistent per-box cache dir instead of a temp one (`engine_role.py:148-152`).
- Unlocks: no green PR is ejected for a box's fault; the box's drift becomes an env PR automatically (D-027 as code). Risk: low; purely additive.

### O-05 Environment attestation in the proof (S)

Add `install_id()`, observed tool versions (PostgreSQL, gitleaks, gh, node, pnpm, python), `platform`, and the digest of `.tower/config` to every pass record, `gate.passed` payload and cache key; pin Vercel's dependency tree; set `PLAYWRIGHT_BROWSERS_PATH`, pnpm `store-dir` and a pre-seeded media cache so a dev gate can run with the network denied (then enforce it: the hermetic harness exists for Python, extend the denial to the shell with a proxy allow-list).
- Unlocks: O-01's proof is trustworthy across machines; "passed on a stale toolchain" becomes impossible. Risk: initial key churn invalidates caches once.

### O-06 Shared cache and proof store across machines (M–L)

Implement a second `providers.storage_adapter` (R2 is already in the stack for media; GitHub release assets or a git ref are alternatives) for `tier1/` and `script-tests/` markers, Next build outputs plus `.next/cache`, and pass records; add eviction (LRU by size/age) and a `scripts/gate-gc` for DBs, reports, worktree dirs; add hit/miss and seconds-saved to `stages.json` and the status table.
- Unlocks: tier 2 and release gates start warm; a new box is useful in its first gate; disk stops being the recurring outage. Dependencies: O-05 (keys must carry platform and tool versions before sharing). Risk: a poisoned shared cache; mitigate with content-addressed entries verified by artifact hash (`gate-build.py` already verifies) and write access limited to gates.

### O-07 The train consumes proofs, re-proves only the combination (L)

Tier 2 should (a) accept member proofs bound to `(tree, base_tree)` and refuse members whose proof is stale rather than re-running them; (b) build the union with `gate-batch` (`gate_batch.py`, already written) and run only the union of member plans plus the integration-sensitive stages (build, e2e smoke, schema); (c) cache tier-2 results by combined tree (today "never cached" is a rule, D-065 (5), that needs a decision: cache the *result*, not the tests, keyed by content); (d) merge every proven prefix even when one forge refusal happens (`train.py:268-275`); (e) retry a base move instead of halting (`:265-267`); (f) unique lock owners.
- Unlocks: batch cost ≈ one gate per batch, not per member; a green PR is never re-proved three times; the train becomes the only merger as D-065 intends. Dependencies: O-01, O-04. Risk: the union plan under-selects; keep tier 3 (full battery on the integration tip) as the safety net it already is.

### O-08 Base health as a first-class signal (M)

Gate the base itself on every merge (the train's `integration.advanced` is the hook; tier 3 exists) and publish `base.red {tests, since}`; a PR red that matches a base red is adjudicated for **every** test kind (today only script tests, `defects.json:10-24`) without the 20-minute base re-run; a `base.red` pauses re-gate asks until `base.green`. Close the defect lifecycle: verify `open` defects each run, retire both stale records, seed from gate events only.
- Unlocks: a bad merge costs one fix PR, not 14–31 re-gates and 6 hours of a frozen lane. Risk: masking a real regression with a same-signature base failure; mitigate by requiring the failing test's inputs to be untouched by the PR.

### O-09 pr.ready without new heads (S)

Plan completeness is a body check: refuse at structure check time (it already reads the body and trailers) and let `pr.ready` fire on the green head when the body is complete; never ask for an empty commit. Make the RETRO the last **plan item but not the last head**: either RETRO before the final gate, or (with O-01) RETRO as a docs-only commit that carries the proof. `lane_id` derivation failures should refuse at the gate (`pr.ready: lane undecidable`) with the units listed, not at the train hours later.
- Unlocks: one green head per unit instead of two or three. Risk: none technical; one decision (RETRO ordering) for Daniel.

### O-10 One merge rule in the registry (S)

`merge.max_behind_base`, `merge.require_mergeable`, `merge.require_exact_head`, consumed by `gate_status` (show "N behind, limit M" in the verdict line), `pr_ready`, `merge-phase` and the train. BD1 (#667) and MQ1 (#680) both add `config/registry/merge.json`; pick one owner.
- Unlocks: a green head knows if it is landable; the quadratic re-gate cost becomes a conscious parameter. Risk: the two paused PRs conflict on the same file.

### O-11 A visible check on GitHub (S, needs Daniel)

Either a token with `statuses:write`/`checks:write` for the gate (so GitHub shows the gate instead of only Vercel's "Account is blocked"), or disable the Vercel GitHub integration until the account is unblocked so the only red on a PR means something. Both are account actions: **CRITICAL premise P-07**.

### O-12 Cost accounting per gate (S)

Add to `gate.passed` and the status table: CPU seconds, wall, REST calls, cache hit ratio, bytes downloaded, and the queue wait (slot wait time is measured today only as a 1 s poll loop). Feed `slo` from it; set the SLO windows so `min_samples` does not hide the first day.
- Unlocks: the ceiling becomes measurable per stage and per box; load-sensitive failures (KF3) become visible as a load metric, not a defect.

### O-13 Self-describing gate: `--explain` and `--why` (S)

`scripts/gate-dev --pr n --explain` prints the plan, the selection, expected time per stage from history, which caches would hit and the preflight result, without running; a red gate prints `--why`: the failing test id, the log path, the class, whether the base fails the same way. Ergonomics for sessions, coordinator and Daniel; most pieces exist in `gate_policy`, `gate_select`, `gate_status.history`, `gate_failures`.

### O-14 Gates that run anywhere: a gate executor pool (L, the 100k picture)

With O-01/O-05/O-06 a gate is a pure function of (tree, base tree, toolchain) and can run on any box: a queue of gate requests (events), N executors (cloud sessions or boxes) that claim them, proofs written to the shared store, the train and `merge-phase` verifying proofs rather than running them. At 100k PRs/day (~70 gates/min at one gate per PR) this is the only shape that scales; nothing in it is exotic once the proof is portable.

### O-15 Smaller, honest stages (M)

Structure check split (O-02); script tests longest-first (GS2) and grouped by `covers`; unit tests per unit as stages so the board shows *which* unit is red; secret scan incremental by default (history already is; the tree scan tars the whole tree each run, `gate-runner.sh:116-124`); performance tests moved out of the per-PR gate into tier 3 unless the diff touches their inputs (they measure a box the gate does not control).

### O-16 Retire what the code has outgrown (S)

Pick one budget (D-064 (f)) and amend ADR-28/ADR-33; make `gate-quiet` the dev plan it claims to be or rename it; delete `gate-impact.py`'s OWNERS table or make it the one table; fix `.gate/logs` in AGENTS.md and `local-gate.md:62`; remove the `gate_status begin` double call.

## 4. What each consumer needs from the gate

One proof object, consumed by everyone. Proposed shape (an evolution of `gate.passed` v3; fields marked **new** do not exist today):

```
gate.proof v4 {
  repo, pr, head_sha, head_tree (new), base_sha (new), base_tree (new), lane_id (new; today null unit),
  plan, selection {kind, units, tests}, stages[{name, result, duration_ms, class, cached, inputs_digest (new)}],
  missing_stages, known_defects[], failing_tests[], cached_tests[],
  toolchain_id (new), observed_versions (new), config_log_digest (new), host (new),
  artifacts {logs_uri, stages_json_uri} (new), cost {cpu_s, wall_s, rest_calls, queue_wait_s} (new),
  carried_from (new: the proof this one reuses, with the delta that justified it),
  signature (new: hash chain or signed by the executor's key)
}
```

| Consumer | Needs today (fact) | Needs for excellence | Invariants and binding | Reuse rule |
|---|---|---|---|---|
| **Session (lane)** | exit code; `GATE: PASSED/FAILED`; status comment; `/tmp` log copy | `gate.finished` wake; `--why` (test id, log, class, base-red?); `--explain` before running; expected time; what will re-run after this commit | the proof names the head it saw and the tree it proved | a docs-only or unrelated commit carries the proof automatically; the session is told so |
| **pr.ready** (`pr_ready.py`) | `gate.passed` for (pr, head sha, plan=dev); checkout HEAD == sha; plan items ticked | body completeness refused at the gate, not here; `lane_id` decided at the gate; accept a carried proof | `head_tree` equals the PR head's tree; `base_tree` is an ancestor tip of the base; `plan == required_gate_kind` | carried proof valid when `delta(head_prev, head) ∩ stage_inputs = ∅` and `toolchain_id` unchanged |
| **Train, queue** (`train.queue_entry`) | `pr.ready.evidence == gate.passed.event_id`, head == forge head, lane_id not None, no refused/ejected/conflicted for this sha | proof `base_tree` to compute the delta to the current tip; `class` of any red to never eject on env; the member's **plan union** to narrow tier 2 | head unchanged since proof; lane consistent with ownership; refusal reasons readable before queueing | a member whose proof is for (tree, base_tree) with base_tree = current tip needs no tier-2 run of its own stages, only the combination's |
| **Train, tier 2** (`engine_role.CommandGate`) | `gate-dev --sha combined`, full, cold, `^FAIL` regex | `gate-batch` union plan; a classified verdict (`gate.failed class=env` → `TrainHalt`); persistent cache dir; result cached by combined tree | tier-2 proof bound to `combined_tree` and `base_tree`; identical content yields the same proof (train already dates commits for this) | a red combined tree seen green before is a flake, not a culprit (exists); a green combined tree is reusable across identical rebuilds (new) |
| **Merge** (`merge-phase`, train merge) | `<sha>.dev.pass` on this machine (+`.db.pass`); `MERGEABLE`; `--match-head-commit` | read the proof from the store, not a file; one registry merge rule (max behind, mergeable, exact head) | exact head; `base_tree` within the allowed distance; `signature` valid | a proof made on another machine is accepted when attested (O-05) |
| **Release** (`ship-verify`, `ship-tail`, D-054 frozen) | `.dev.pass` + `.db.pass` + full `nightly=1` pass on the exact release head | the same proof object for the release head; tier 3 proof carried when the integration tip's tree is unchanged | release head exact; full battery present; frozen flag honoured | re-run only the stages whose inputs changed since the last tier-3 proof |
| **Status / board / dashboards** (`gate_status`, `slo`, `stall_report`, coordinator) | status comment per head; `engine.step.measured`; `gate.*`, `pr.*` | `gate.started` + `gate.finished`; expected durations from the ledger; superseded-head marking; cost fields; class shown | one row per running gate, bound to (pr, head, plan) | history keyed by stage × plan kind, shared off-machine |
| **Known-defect / quarantine** (`defect_detect`, `quarantine`) | script-test failures re-run on base; flakes from same-sha red+green | `base.red` signal for all test kinds; no 20-minute re-run inside tier 1; one policy for flips | a defect is bound to (test id, signature, base_tree); verified or retired every run | adjudication reused across PRs for the same (test, signature, base_tree) |
| **Daniel / coordinator** | PR comments, heartbeat, `sessions.log` by hand | the board (O-03); a visible check on GitHub (O-11); one number for cost per PR | — | — |

Invariants the proof must keep for every consumer: (1) exact head is a pointer, the tree is the key; (2) the base is recorded; (3) a red names its class and its test; (4) nothing is loosened silently (a carried proof names the proof it came from and the delta that justified it); (5) the proof travels (store, not a local file); (6) the environment that produced it is named.

## 5. Open questions for the deep-dive audit (Opus 5.5)

Where I was unsure, what needs a measurement, what I suspect but could not prove. Measure locally in a throwaway worktree; never via a PR.

1. **Where the seconds go, per stage, under no load.** I have status-table durations from PRs (structure check 15 s to 3m18s, script tests 107 s to 12m16s) but no controlled run. Measure gate-dev on 2e423b7e cold and warm on a 4-vCPU cloud box: per-stage wall, CPU, cache hits; then with `GATE_SLOTS=1` vs 3 concurrent gates. Hypothesis: structure check and script tests dominate the critical path and are the most load-sensitive; install + two builds dominate cold time.
2. **How much of the structure check is tree-deterministic.** Which of its modules read PR metadata (`--pr`: commit plan, body, comments) and which only the tree? That decides how much O-02 saves. Suspect: > 80 % is tree-only (literals, imports, manifests).
3. **False carry-over risk of O-01.** For the last 50 merged PRs, compute for each pair of consecutive heads whether `delta ∩ declared stage inputs = ∅` under narrowed inputs, and whether the real gate outcome differed between those heads. If any green→red transition happened on a delta the inputs would have ignored, O-02's narrowing is wrong somewhere.
4. **Cache hit rate in the field.** Parse `cached_tests` and `stages.json.cached` from the forge-events comments of the last 100 verdicts: hit ratio per stage kind and seconds saved. I saw 12/77/79 cached tests on #691/#690 but no denominator.
5. **Is KD1's FAIL→PASS flip ever wrong?** For every `MERGEABLE — only known base defects` verdict, check whether the PR touched the failing test's inputs. Suspect: no case yet, but the signature match is weak (160 chars).
6. **Tier-2 economics.** With `gate-batch` union plans vs `gate-dev --sha` full: time per batch of 1, 4, 8 members; and how often a base move between build and merge would have halted the train given 27/10's merge cadence (41 merges/h at peak).
7. **API budget.** Count REST calls per gate (status begin/replan/stage/final, forge-events publish with its 20-page dedupe read, pr view, defect events) and extrapolate to 40 parallel gates against the 5000/h primary limit and the secondary limits. Suspect: the dedupe read is the dominant cost and already near the edge at 40 sessions.
8. **The `eaa408de` question.** Is TR2 plan item 7 (TrainHalt on class env) merged anywhere? The #690 merge is of 0aeac030; the comment announcing `eaa408de` is after the merge. If unmerged, it is the first PR of step 4.
9. **PostgreSQL as the shared bottleneck.** Measure CREATE/DROP DATABASE latency under 3 concurrent gates (KF3 saw 30 s stalls); test whether moving the cluster out of a checkout and raising `heavy_db_slots` changes anything; count accumulated `tower_test_*` databases on the box.
10. **Who emitted `pr.ready` on #605/#607 at 14:08Z** while both lane sessions believed it was not emitted: the coordinator by `scripts/pr-ready`? That path bypasses the HEAD==sha check's intent and shows the session cannot read its PR's state; confirm from the box's claims log.
11. **Load-sensitivity as a class.** `gate-heavy-db.test.sh`, `claude-session.test.sh`, read-latency perf, `rest fake did not start` under load: list every test that reads the clock or CPU count, and decide which belong in tier 1 at all.
12. **Vercel's "Account is blocked".** Is the integration still installed on the repo, and does it count toward anything (branch protection?) or is it pure noise? Account action; Daniel.
13. **Disk and inode budget per gate run** on the box: measure `.gate/records/reports/<sha>/<run>` size with browser artifacts, `gate-builds` growth per distinct build key, and `/tmp/tower-worktrees` residue; the box hit 100 % inodes twice.
14. **Signature of the proof.** Decide the minimum: hash chain over the event log (cheap, already the `audit_chain.py` idiom for defects) vs executor keys. Suspect: the hash chain plus author-association is enough until executors are untrusted boxes.

## 6. Premises with blast radius

CRITICAL = failure changes scope, spends money, touches production or the source of truth, or needs Daniel. Non-critical ones I decided (DECIDE, THEN REPORT).

| ID | Premise | If false | Status |
|---|---|---|---|
| **P-01 CRITICAL** | The gate's proof may become content-addressed (tree + base tree), with the head sha as a pointer; a docs-only commit after a green gate carries the proof. This is the mechanism by which "RETRO stays a file" and "the gate must handle it" coexist. | O-01/O-02/O-07/O-09 collapse; the only alternative is RETRO before the final gate, which changes the padrão (brief templates) Daniel said not to change. Needs a D-NNN. | For Daniel |
| **P-02 CRITICAL** | Tier 2 may reuse member proofs and cache its own result by combined tree; D-065 (5) "tiers 2 and 3 never use cached test results" is about *test* results, not about verifying an attested proof. | O-07 shrinks to "classified verdict + union plan"; the train keeps re-proving every member in full and the 1000/day goal needs ~3× the executors. | For Daniel |
| **P-03 CRITICAL** | A visible GitHub check (token with checks/statuses scope) or disabling the Vercel integration is acceptable; both are account actions. | O-11 impossible; humans keep ignoring the only red on every PR. | For Daniel |
| **P-04 CRITICAL** | A shared cache/proof store (R2 or GitHub assets) may be used by gates; it costs storage and egress. | O-06 and O-14 impossible; every box stays cold; tier 2 stays cold. | For Daniel (money) |
| **P-05 CRITICAL** | `eaa408de` (TrainHalt on class env) is not on base; the train as merged still ejects on env failures. | If it is merged somewhere I missed, F-03's second bullet is already fixed and O-04 is smaller. | Verify (Opus Q8) |
| P-06 | The box evidence snapshot (11:37) is complete enough: no later train run, no other ejection cause. Decided: treat it as complete; anything after 11:37 is out of this audit. | A later incident changes F-03's count, not its class. | Decided |
| P-07 | The field wall times in `sessions.log.txt` are gate-dev wall as printed by `GATE TOTAL`, not status-table sums. Decided: treat them as wall (MERGE-READY comments quote the same numbers). | Medians shift by the report/hook time (~10–50 s); ranking unchanged. | Decided |
| P-08 | The paused units BD1/GS2/AR1/HD1/MQ1 will be re-planned by step 3 rather than resumed as-is; their overlaps (merge.json twice, `gate-local` edits in GS2) are inputs, not constraints. | If they resume unchanged, step 3 must sequence them before any O-02/O-10 PR touching the same files. | Decided (step 3's call) |
| P-09 | The 180 s ceiling (D-064 (f)) remains the target; I did not propose loosening it anywhere. | None: the audit never loosens thresholds. | Decided |
| P-10 | Selection narrowing (O-02) must fail closed: an undeclared input keeps `**`. | A false carry-over passes a regression; tier 3 on the integration tip is the net. | Decided |
| P-11 | The GitHub event log stays the proof's transport until a store exists; the `.pass` files are a per-machine cache of it, not a second source of truth. | merge-phase/ship-tail keep diverging from pr-ready/train. | Decided (matches EVENTS.md:190-192) |
| P-12 | This audit's numbers are from one day (27/10) under exceptional load (30–40 sessions, two base-defect waves). Decided: report them as that day, not as steady state; Opus measures steady state (Q1). | Ranking of F-05 vs F-01 could swap; both stay top-5. | Decided |

## Appendix: evidence index

### Code read (base 2e423b7e)

- Drivers: `scripts/gate-dev`, `gate-local`, `gate-quiet`, `gate-db`, `gate-batch`, `gate-noite`, `program-gate`, `pr-ready`, `train`, `run`, `stall-report`, `dashboard`, `merge-phase`, `structure-check`, `defects`, `quarantine`.
- Libraries: `scripts/lib/gate-runner.sh`, `gate-budget.sh`, `gate-fixed.sh`, `gate-isolation.sh`, `gate-db.sh`, `gate-build.py`, `gate-impact.py`, `gate-browser-summary.py`, `gate-stages.json`, `gate-areas.json`, `gate-script-tests.json`, `gate-smoke.json`, `gate-stages-baseline.json`, `gate-suite-baseline.json`, `gate_areas.py`, `gate_batch.py`, `gate_classify.py`, `gate_failures.py`, `gate_graph.py`, `gate_noite.py`, `gate_policy.py`, `gate_report.py`, `gate_result_cache.py`, `gate_select.py`, `gate_skips.py`, `gate_speed.py`, `gate_status.py`, `gate_suite.py`, `gate_test_cache.py`, `pr_ready.py`, `plan_tick.py`, `train.py`, `train_aggregates.py`, `train_git.py`, `train_ownership.py`, `train_trigger.py`, `engine_role.py`, `forge_events.py`, `forge_github.py`, `github_api.py`, `github_cli.py`, `event_contracts.py`, `slo.py`, `stall_report.py`, `coordinator.py`, `coordinator_launch.py`, `program.py`, `program_gate.py`, `defects.py`, `defect_detect.py`, `defect_router.py`, `quarantine.py`, `commit_check.py`, `ship_tail.py`, `ship_verify.py`, `release_policy.py`, `delivery.py`, `units.py`, `unit_map.py`, `config.py`, `env_manifest.py`, `toolchain_manifest.py`, `toolchain_check.py`, `preflight.py`, `test_db.py`, `hermetic.py`, `hermetic_check.py`, `session_identity.py`, `adapters/storage*.py`; `scripts/cloud/setup.sh`, `env.sh`, `preflight`, `postgres.py`, `toolchain.py`, `fonts.py`, `toolchain.json`.
- Registry: `config/registry/gate.json`, `train.json`, `battery.json`, `defects.json`, `quarantine.json`, `forge-events.json`, `github-client.json`, `slo.json`, `plan-tick.json`, `providers.json`, `session-cache.json`, `test-db.json`, `cloud.json`, `toolchain.json`, `tests.json`, `local-checks.json`; `contracts/events/gate.passed.v3.json`, `gate.failed.v3.json`, `pr.ready.v1.json`; `contracts/defects/defect.v1.json`.
- Docs: `docs/adr/ADR-24`, `ADR-28`, `ADR-33`, `ADR-34`; `docs/domain/DECISIONS.md` (D-009, D-022, D-025, D-027, D-046, D-054, D-055, D-064, D-065, D-066, D-069); `docs/process/EVENTS.md`, `STRUCTURE.md`, `RELEASES.md`; `docs/operations/local-gate.md`; `docs/padrao/v1/retro-before-merge.md`, `audit-and-plan.md`; `docs/units/GV1/*`, `TR2/*`, `TR2b/*`, `KF3/audit.md`; `docs/programs/_template/*`, `reach-1000-prs-per-day/*`; `AGENTS.md`, `CLAUDE.md`.

### GitHub evidence (read through the REST API; nothing posted)

PRs #605, #607, #615, #667, #671, #677, #680, #683, #690, #691: bodies, commits, gate-status comments, forge-events comments (`gate.passed`, `pr.ready`, `pr.refused`, `pr.ejected`), STATUS/RETRO/MERGE-READY comments, commit statuses (Vercel only; zero check runs on every head). Key timestamps (UTC): #691 run 1 13:59:30→14:03:13 (3m44s) and run 2 14:04:01→14:07:35 (3m35s), merged 14:07:48; #690 runs 14:02:39→14:04:56, 14:06:28→14:07:09, 14:09:48→14:21:04, `pr.refused` 14:12:35 (cf401301, lane null), `pr.ejected` 14:16:52 (0aeac030), merged 14:19:10, TrainHalt comment 14:20:29; #607 `pr.ejected` 14:13:02; #605 `pr.ejected` 14:14:29; #615 `pr.ready` lane null 14:17:41; #605 first green 07:00, #607 07:05, #615 07:14.

### Box evidence (branch `mod/ga1-evidence`, `docs/programs/gate-excellence/evidence/box-snapshot-20261027-1137/`)

`README.md`; `sessions.log.txt` (lines 36-44 inodes, 443-575 merge lines with wall times, 591 first train run and the 0.8/2.0 min baseline, 629-645 the 10:31-11:19 window); `night-plan.md` (items 23-28, §25 duplicate train run, §26 ejections, the 11:05/11:09/11:18/11:29 decisions); `night-metrics.log.txt` (02:20-11:09 heartbeat lines: failed_gates, known_defects_hit, inodes); `known-defects.json` (7 records incl. KF3's two load-sensitive tests); `queue-lanes.md` (lane layout, 124 queued units); `enforcement-audit-2026-10-26.md` (gate-local line references, host locks, Vercel rule); `train-run-1111.log.txt` (`EXIT 143`); `fast65-stop-verify.txt` (35 paused sessions).

### Cited evidence that does not exist on this base or machine

- `/workspace/torre/motor/sessions.log`, `/workspace/torre/motor/v3/night-plan.md`, `night-metrics.log`, `known-defects.json`, `queue-lanes.md`, `enforcement-audit-2026-10-26.md`: `/workspace` is absent in this cloud container. Incidents named in the brief are taken from the brief and from PR comments only.
- `.github/workflows/`: absent (ADR-24, no GitHub Actions). Nothing in GitHub runs the gate.
- `gh` CLI: present but its token does not authenticate; PR comments and checks are read through the GitHub REST API instead.
