# TX24 audit: per-feature Python test files and rest_fake routes

Base: `origin/mod/roadmap-integration` at 891b835ae (2026-10-28). Principle T1: a unit adds a file, it does not append to a shared one.

## Brief evidence, re-verified on the base

| Claim | Holds? | Evidence |
|---|---|---|
| `scripts/tests/test_train.py` most edited | yes | 21 commits since 2026-10-24 (`git log --since=2026-10-24 -- scripts/tests/test_train.py`), 938 lines |
| `test_forge_events.py` | yes | 20 commits since 2026-10-24 (brief said 15: more since), 527 lines |
| `test_gate_status.py` | yes | 10 commits, 362 lines; #740 (mod/gx25, open) appends `class Started` |
| `test_planner_role.py` | yes | 3 commits, 377 lines; #734 (mod/lp9, open) appends WakePath tests |
| `scripts/tests/rest_fake.py` shared | yes | 12 commits since 2026-10-24, 401 lines; 16 tracked files under `scripts/tests/` name it (`git grep -l rest_fake -- 'scripts/tests/*'`) |
| `/compare/` route already on base (#722) | yes | `scripts/tests/rest_fake.py:154` (GX-22 comment) |
| Wrappers list files by hand | yes | `train.test.sh:5`, `forge-events.test.sh:5` (also `test_branch_age.py`), `gate-status.test.sh:4`, `planner-role.test.sh:5` |
| `scripts/prepush` (TX01) on base | **no** | absent; the brief's fallback list of fast checks is used |

## Counts on the base (the invariant every split keeps)

`grep -c 'def test_'` / `grep -c 'self\.assert'` per file:

| File | tests | asserts | Run in gate |
|---|---|---|---|
| test_train.py | 58 | 180 | `Ran 58 tests ... OK` (14.3 s) |
| test_forge_events.py | 40 | 115 | `Ran 40 tests ... OK` (16.8 s), plus test_branch_age.py `Ran 12 tests` |
| test_gate_status.py | 28 | 71 | `Ran 28 tests ... OK` (0.6 s) |
| test_planner_role.py | 17 | 48 | `Ran 17 tests ... OK` (2.1 s) |

Per class (tests/asserts), from `ast`:

- train: helpers FakeClock:46, FakeForge:56, FakeGate:117, Fixture:147 (0 tests); Queue:230 5/5, QueueIndex:267 4/12, CombinedHead:322 5/19, GreenBatch:375 13/51, Bisection:549 3/11, UnionPlan:576 4/12, CriticalPath:651 5/9, MergeRule:687 3/5, VerdictLink:723 1/2, Flakes:735 4/26, Tier2:808 6/12, Aggregates:877 4/12, Registry:926 1/4.
- forge_events: FakeClock:29; Emit:55 6/17, Read:106 3/7, FileLog:137 1/4, Replay:154 5/17, Measured:221 4/7, LoopbackGitHub:263 8/32, GateEvidence:392 6/19, Boundary:475 1/3, Subject:485 1/3, SetStatus:493 5/6.
- gate_status: FakeRest:26, Base:69 (0 tests); Live:87 13/31, CommitStatus:210 6/15, Final:273 6/16, CallSites:330 3/9; `status_stages` helper :357 (used by CallSites only).
- planner_role: FakeClock:43, LockingForge:53, StandInLog:74, Remote:121 (0 tests); SoleWriterAppend:156 5/16, RealPlanLog:226 1/2, RoleLease:244 3/8, WakePath:295 8/22; `candidate` helper :287 (WakePath only); `WAIT_S` module global set in `setUpModule` :38 and read at :180, :254, :261.

## Findings that shape the design

1. Every wrapper runs each file as a script (`python3 file`), never `python -m unittest`: a test directory named like a `scripts/lib` module (`train/`, `forge_events/`, `gate_status/`, `planner_role/`) would be imported as a namespace package by `-m unittest` path names and shadow the real module. Running files as scripts with `scripts/lib` inserted first keeps the regular module winning (a namespace portion never beats a regular module).
2. Shared fixtures stay in the base file; feature files import them (`import test_train as base` style). `WAIT_S` is rebound by `setUpModule`, so a moved reader must read it through the base module, not a copied name.
3. `rest_fake.py` is always started as a subprocess (`test_forge_events.py:272`, `test_forge_rate.py:164`, `test_claude_session.py:94`, `test_gate_forge_budget.py:62`, `rest-fake-start.sh`), never imported, so route discovery happens in its own process by file path. `scripts/tests/rest_fake/` next to `rest_fake.py` does not shadow it (a module file beats a namespace directory in the same path entry).
4. `_dispatch` (`rest_fake.py:125-263`) is one if-chain. Cross-cutting checks (proxy refusal :131, secondary limit :139, GraphQL :141) must stay first; the route matchers after them are disjoint by method and path shape, so their order does not change an answer.
5. Covers manifests: `scripts/tests/covers/{forge-events,forge-rate,gate-db,gate-forge-budget,invoker-tooling,merge-phase,rest-fake-ready}.json` name `scripts/tests/rest_fake.py`. A route file must be covered by the same set, else a route change would select fewer tests (an uncovered path runs the whole suite, a path covered by one manifest runs only that test).
6. Hermetic check (`scripts/lib/hermetic_check.py:104-110`) judges any `test_*.py` under `tests.check_roots` (`scripts/tests/` prefix), so nested files are judged with no change. Units: `scripts/tests/**` is in `units.test_globs` (`config/registry/units.json:159`); a test file belongs to at most one unit, so each new directory gets one `scripts/tests/<dir>/**` glob in its owner's manifest (engine-train, engine-events, engine-gate-report, engine-coordinator, engine-test-support).
7. `gate-status.test.sh` lacks `PYTHONDONTWRITEBYTECODE=1`; importing the base file from a feature file would write `scripts/tests/__pycache__`. The four wrappers set it.
