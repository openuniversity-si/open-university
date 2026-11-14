# TX24 plan: per-feature Python test files and rest_fake routes

Branch `mod/tx-pysplit`, PR #754, lane engine-lane, base `mod/roadmap-integration`. Decision: D-070. Premises: P-46. Audit: [audit.md](audit.md).

## Shape

- `scripts/tests/<dir>/test_<feature>.py`: one file per feature. It puts `scripts/tests` on `sys.path`, imports its fixtures from the base file (`from test_train import Fixture, ...`; a value `setUpModule` rebinds is read as `base.NAME`), reuses the base `setUpModule`, and ends with `unittest.main()`.
- The base file keeps the shared fixtures and the tests not moved.
- The wrapper runs the base file and every `scripts/tests/<dir>/test_*.py` by glob, each as its own `python3` process (audit finding 1), with `PYTHONDONTWRITEBYTECODE=1`. A new feature file needs no wrapper edit.
- Covers manifest of the wrapper: add `scripts/tests/<dir>/*.py`. Owner manifest: add `scripts/tests/<dir>/**` (then `scripts/generate codeowners`).
- `scripts/tests/rest_fake/*.py`: each module exports `ROUTES`, a tuple of `route(handler, method, parts, directory) -> bool` (True when it answered). `rest_fake.py` keeps the server, the cross-cutting checks (proxy refusal, secondary limit, GraphQL) and the 404, and loads the modules by sorted glob. Adding a route is one new file.

## Commits (dependency graph: 1 -> {2, 3, 4, 5, 6} -> 7; 2..6 are independent of each other)

| # | Commit | Files | Targeted tests |
|---|---|---|---|
| 1 | Audit and plan | docs/units/TX24/{audit,plan}.md | none (docs) |
| 2 | rest_fake route modules | scripts/tests/rest_fake.py, scripts/tests/rest_fake/{github_pulls,github_issues,compare,neon,vercel}.py, units/engine-test-support/unit.json, CODEOWNERS, covers of the 7 rest_fake users (+ `scripts/tests/rest_fake/*.py`), engine-test-support literal baseline | rest-fake-ready, forge-events, forge-rate, gate-forge-budget, claude-session, merge-phase, invoker-tooling, gate-db (each test that starts rest_fake) |
| 3 | gate_status split | test_gate_status.py, gate_status/test_{live,commit_status,final}.py, gate-status.test.sh, covers/gate-status.json, units/engine-gate-report/unit.json, CODEOWNERS, engine-gate-report baseline | gate-status.test.sh |
| 4 | planner_role split | test_planner_role.py, planner_role/test_{sole_writer,wake}.py, planner-role.test.sh, covers/planner-role.json, units/engine-coordinator/unit.json, CODEOWNERS, baseline | planner-role.test.sh |
| 5 | forge_events split | test_forge_events.py, forge_events/test_{emit,replay,loopback,gate_evidence,set_status}.py, forge-events.test.sh, covers/forge-events.json, units/engine-events/unit.json, CODEOWNERS, baseline | forge-events.test.sh |
| 6 | train split | test_train.py, train/test_{queue,batch,plan,merge,flakes,aggregates}.py, train.test.sh, covers/train.json, units/engine-train/unit.json, CODEOWNERS, baseline | train.test.sh |
| 7 | Proof and RETRO | docs/units/TX24/retro.md (proof transcript: a fixture file dropped into each directory runs with no wrapper edit, measured in a throwaway worktree) | the single final pinned gate |

Feature map (tests/asserts move unchanged; base keeps the rest):

- train/: queue (Queue, QueueIndex 9/17), batch (CombinedHead, GreenBatch, Bisection 21/81), plan (UnionPlan, CriticalPath 9/21), merge (MergeRule, VerdictLink 4/7), flakes (Flakes, Tier2 10/38), aggregates (Aggregates 4/12); base keeps Registry 1/4.
- forge_events/: emit (Emit, Read, FileLog 10/28), replay (Replay, Measured 9/24), loopback (LoopbackGitHub 8/32), gate_evidence (GateEvidence 6/19), set_status (SetStatus 5/6); base keeps Boundary, Subject 2/6; test_branch_age.py stays where it is (its own unit file).
- gate_status/: live (Live 13/31), commit_status (CommitStatus 6/15), final (Final 6/16); base keeps CallSites 3/9 and the fixtures (FakeRest, Base, stage, status_stages).
- planner_role/: sole_writer (SoleWriterAppend, RealPlanLog 6/18), wake (WakePath 8/22, with `candidate`); base keeps RoleLease 3/8 and the fixtures.

## Pending PRs (their branches are not edited; what each does after this merges)

- #740 GX-25 `test_gate_status.py`: L15 import, L80 ledger in `Base`, L99 rename stay in the base file; `class Started` (L215, 7 tests) and its import move to `scripts/tests/gate_status/test_started.py`.
- #734 LP9 `test_planner_role.py`: the L280 `RoleLease` edit stays in the base file; the 5 WakePath tests (L343, L379) move to `scripts/tests/planner_role/test_wake.py`.
- #667 BD1 `rest_fake.py` `/compare/` route: already on the base from #722 (now `scripts/tests/rest_fake/compare.py`); #667 drops its copy.

## Premises and blast radius

- P-46 (the pinned gate on the base tip is the verdict): radius whole gate; held as long as the final run is the pinned gate.
- **CRITICAL** T-a: every test still runs. Radius: four suites (148 tests). Proof: `def test_` and `self.assert` counts before = after per module (summed over base + directory), and each wrapper's `Ran N` lines summed equal the base count.
- **CRITICAL** T-b: a moved route answers byte-for-byte the same. Radius: 16 rest_fake users. Proof: every test that starts rest_fake is green after commit 2 with no test edit; route bodies move verbatim.
- T-c: the test cache still selects every affected test. Radius: gate test selection. Proof: each new directory glob is in the covers of every wrapper that covered the old file (rest_fake: all 7).
- T-d: no threshold or timeout changes. Proof: the grep in the PR body returns nothing new.

## Gate

Targeted tests per commit only; one pinned gate at the end: `OU_CONFIG_STORE=file bash scripts/cloud/setup.sh`, then `(export OU_CONFIG_STORE=file; source scripts/cloud/env.sh; unset OU_CONFIG_STORE; scripts/gate-dev --pr 754)` in the background.
