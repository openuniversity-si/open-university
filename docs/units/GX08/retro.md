# GX-08 retro — test map from per-test manifests

## 1. Brief quality
- The brief said 79 tests; the base has 80 (`load()` enforces map == `scripts/tests/*.test.sh`). Migrated 80.
- The first brief asked for `# gate-covers:` headers in 79 test files. That would have changed each test's own sha256, which is a cache key input, so "keys unchanged" would have needed a header-stripping hash in `gate_test_cache.py` (GX-03's file). Found in the audit, before any code. The 15:20 plan-v2 message moved covers to sidecar manifests, which removes the problem: no `.test.sh` is touched and the key entry `{script, covers}` is byte-identical.
- `modules` had no home in the header design; in the manifest it is a field.

## 2. Audit and plan
- P-10 held: the map is built from files each unit owns; no PR edits an aggregate. P-19 held.
- The plan changed once (v1 headers → v2 manifests, commit 3). Commits were renumbered; the PR body was updated.

## 3. Execution (UTC, 27/10)
- Audit, plan, draft PR #698: first commits. Registry file, loader, `--migrate`, tests: one pass, no test failure.
- One mistake: I edited a comment in `scripts/tests/engine-capture.test.sh` that named the deleted JSON. That file is a key input, so it changed that test's key and broke the "no test file edited" rule. Caught by diffing the branch against the base before the gate; reverted by a normal commit (8b43911b). Class: a comment that names a path is still a cache input. Prevention: the stale reference stays until the owner of that test touches it (its key changes then anyway).
- One structure-check failure: literal `2` (`indent=2`, a test count) over the engine literal baseline. Fixed in the same step by removing both literals, not by raising the baseline.
- `scripts/generate all` rewrote `apps/web/tsconfig.json` in the working tree (no content diff in git); not committed.

## 4. Gate
See the PR comments: verdict of record (base-tip checkout) and the own-checkout report. Known env failures are named there.

## 5. Lessons
- Any unit that edits a test file also edits that test's cache key; a brief that asks for edits to many test files should state the key consequence. Owner: brief template (coordinator).
- `gate_test_cache.py` still mentions the deleted JSON in its docstring (GX-03's file); `units/engine-gate-plan/unit.json` and `CODEOWNERS` still list the JSON until GX-38 regenerates them (unit check warns, does not fail). Owners: GX-03, GX-38.
- A unit that adds a script test after this merges adds `scripts/tests/covers/<name>.json`; `gate_script_tests.py check` (run by `gate-script-tests.test.sh`) refuses a test without one.
