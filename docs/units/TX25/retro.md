# TX25 retro: orphan tests run; wrappers glob

PR #748, lane engine-lane, base `mod/roadmap-integration` 891b835ae. The pinned gate result on the final head is in
the PR's RETRO comment (this file is part of that head).

## Outcome

- `test_gate_gc.py` (10 tests) and `test_text_check.py` (21 tests) run in the suite through `gate-gc.test.sh` and
  `text-check.test.sh`; both were green on their first run: the lost coverage hid no defect.
- Ten wrappers name module globs (`test_<module>*.py`); file lists before and after are equal except
  `test_neon_migrate.py`, which ran twice per suite and now runs once (`neon.test.sh`).
- `scripts/lib/test_orphans.py`, called once by structure-check, refuses a test no wrapper runs, a test two wrappers
  run, and a wrapper glob that matches no test. On the base it reports exactly the three audit findings; on the head,
  none. Assertions: base 4378, head 4396 (+18, the check's own tests; no existing test file changed).

## Brief quality

Good: every cited file and line held on the base; the file ownership split with TX24 and TX26 left no collision.
Missed: the `test_neon_migrate.py` double (cloud-tail and neon). The prototype of the check found it in its first
run, before any code: a derived check is the cheapest audit tool. `scripts/prepush` (TX01) is not on this base;
the brief's fallback list of fast checks worked.

## Premises

| Premise | Held? |
|---|---|
| P-46 the verdict comes from the pinned gate on the base tip | held (pinned gate used) |
| CRITICAL: only `.test.sh` wrappers run `scripts/tests/test_*.py` | held: on the base the check reports no false orphan |
| Comment lines never run a test | held: `gate-local.test.sh:164,167` are the only comment mentions |
| Dropping `test_neon_migrate.py` from cloud-tail loses no assertion | held: the same file runs in neon, unchanged |

## Failures and their class

| Failure | Class | Fixed by |
|---|---|---|
| The first parser read `"$here/test_x.py"` as module directory `here` (6 false errors on the real repo) | code (mine) | a module directory must be a path component (`(?<![\w$-])`), with a test for `$here/` and `${here}/` |
| Literal census refused `parents[2]` in the new test file | rule | the `parent.parent.parent` form 11 tests already use |
| Registry schema refused keys without `x-unit` | rule | `x-unit` on each key (`glob`, `names`) |
| A helper named `test` on the test case was collected by unittest | code (mine) | renamed `add_test` |
| The before/after shim missed relative `$(dirname "$0")/test_x.py` paths | tool (mine) | the shim matches `*scripts/tests/test_*.py` |

## Lessons

1. Run a derived check against the real repository before writing its tests: it found the double and the parser
   bug in seconds. Rule for every TX inventory unit; owner: the program (TX40 retro).
2. 71 test files use `ROOT = Path(__file__).resolve().parents[2]`, which the literal census forbids in a new file.
   A shared root helper for `scripts/tests` would remove the trap; owner: engine-structure (literals, after TX22).
3. Pending #662 (N1) edits `scripts/tests/structure-check.test.sh`: after this merges it drops its line, since the
   wrapper globs `test_<module>*.py`.
