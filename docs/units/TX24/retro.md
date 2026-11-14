# TX24 retro: per-feature Python test files and rest_fake routes

PR #754, branch `mod/tx-pysplit`, base 891b835ae. Commits: audit+plan, rest_fake routes, gate_status, planner_role, forge_events, train, this proof and retro.

## Proof

Counts (`grep -c 'def test_'` / `grep -c 'self\.assert'`), base before vs base file + directory after:

| Module | Before | After (base + files) | Wrapper runs (`Ran N` lines) |
|---|---|---|---|
| train | 58 / 180 | 1/4 + aggregates 4/12, batch 21/81, flakes 4/26, merge 4/7, plan 9/21, queue 9/17, tier2 6/12 = 58 / 180 | 1+4+21+4+4+9+9+6 = 58, all OK |
| forge_events | 40 / 115 | 2/6 + emit 10/28, gate_evidence 6/19, loopback 8/32, replay 9/24, set_status 5/6 = 40 / 115 | 2+10+6+8+9+5 = 40 OK, plus test_branch_age 12 OK |
| gate_status | 28 / 71 | 3/9 + commit_status 6/15, final 6/16, live 13/31 = 28 / 71 | 3+6+6+13 = 28, all OK |
| planner_role | 17 / 48 | 3/8 + sole_writer 6/18, wake 8/22 = 17 / 48 | 3+6+8 = 17, all OK |

A new feature is one file (throwaway worktree at 68c1b7c6, wrappers unchanged by `git diff --quiet`): a `test_zz_fixture.py` dropped into each of `train/`, `forge_events/`, `gate_status/`, `planner_role/` ran (`TX24 fixture ran in <dir>`, `Ran 1 test ... OK`) inside the unchanged wrapper. A feature file that fails to import turns the wrapper red (`set -e` in the loop), seen when the first fixture imported a `setUpModule` the forge_events base does not define.

A new route is one file: `rest_fake/zz_fixture.py` answered `GET /tx24-fixture` with `{"route": "one new file"}`, `rest_fake.py` unchanged.

rest_fake equivalence: the old `rest_fake.py` and the new one answered 27 requests (every route, both 404 paths, GraphQL, unknown path, a proxy-refused write) with the same status and body, and left the same case files (`requests.log`, `reads`, `content-writes`, `merged`, `deleted`, `views`, comments, neon.json). The tests that start it: rest-fake-ready, forge-events, forge-rate (28), gate-forge-budget (9), claude-session (12), merge-phase (39 ok), invoker-tooling (6), gate-db (23 passed), all green.

Selection: `gate_script_tests.select` picks train.test.sh for `scripts/tests/train/test_zz_fixture.py`, gate-status.test.sh for `scripts/tests/gate_status/test_new.py`, and all 8 rest_fake users for `scripts/tests/rest_fake/zz_fixture.py`.

Coverage: the hermetic check judges nested files (`hermetic_check.judged('scripts/tests/train/test_queue.py', ...) == 'py'`); the asset inventory has a TX24 entry naming the five directories; each wrapper's covers names `<dir>/*.py`; each owner manifest names `scripts/tests/<dir>/**`.

## Brief quality

Good: exact file list, the pending PRs with line numbers, the counting rule. Two premises did not hold on the base: `scripts/prepush` (TX01) is absent, and the asset inventory covers `scripts/tests/*`, not `scripts/tests/**` (TX00 is still in #742). The brief also missed that `test_train_role.py` imports module names from `test_train.py` (`from test_train import REPO, ROOT, Fixture, config, engine_role, forge_events, train`), so the base file is an API, not only a host of tests.

## Premises

- P-46 (pinned gate on the base tip): held; the final gate is the pinned path.
- T-a (every test runs): held, table above.
- T-b (routes answer the same): held, 27-request comparison.
- T-c (selection unchanged or wider): held; claude-session's covers gained `rest_fake.py` and `rest_fake/*.py`, which it lacked although its test starts the fake.
- T-d (no threshold or timeout change): held; the grep shows only moved lines (`gate.status_min_interval_s`, `WAIT_S`) in pairs, and the plan's own sentence.

## Failures and root-cause class

1. f8895c68 (rest_fake) alone fails `structure-check`: the nested route files had no asset inventory entry. Class: **env/process** (brief premise false, plus check order). `.githooks/post-commit` pushes at commit time, so the worktree check I ran after committing came one step late. Fixed in 8c7ade47 (the TX24 entry); from then on every fast check ran before the commit. Lesson (owner: TX-PROGRAM, the brief template): say that the post-commit hook pushes, so "fast checks before every push" means before every commit; and gate a brief's "since TX00" claims on the base actually holding them.
2. First forge_events split: `NameError: NEXT` in two files. Class: **code** (my one-shot splitter only read `NAME = ...`, not `A, B, C = ...`). Fixed the splitter for every tuple and annotated assignment and redid the split; the other modules were already green, so no other missing name existed. Lesson: a mechanical move is proven by running it, which the per-commit targeted test did before the commit.

## Gate runs

Targeted only while working (per commit, listed above). One pinned gate on the final head; its result is in the MERGE-READY comment.

## Cost

train.test.sh takes about 17 s instead of 14.5 s: seven more `python3` processes, each importing the train modules. No threshold is near; a shared in-process runner is the next step if the gate's total time asks for it (owner: TX25, which owns the other wrappers).

## Pending PRs

- #740 GX-25: `class Started` and its import go to `scripts/tests/gate_status/test_started.py`; the L80 ledger in `Base` and the L99 rename stay in `test_gate_status.py`.
- #734 LP9: the L280 RoleLease edit stays in `test_planner_role.py`; the 5 WakePath tests go to `scripts/tests/planner_role/test_wake.py`.
- #667 BD1: drop its `/compare/` copy; the route is `scripts/tests/rest_fake/compare.py`.
