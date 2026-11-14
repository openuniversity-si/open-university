# GX-03 retro: size the gate to its container

## 1. Brief quality
Clear and complete. Gaps: (a) it named `gate.slots` as an "optional override" but the registry has no nullable keys, so 0 now means derived (decision recorded in the key's description); (b) the brief's file list omitted `scripts/lib/gate_graph.py`, which has to time each command for the longest-first order (one optional `timings` argument); (c) "script tests start longest-first from `engine.step.measured`" gave no step name, so the unit defines `gate:script-test:<path>`; (d) a launch, a HALT and a RESUME came in the first minutes (nothing lost: no branch or commit existed).

## 2. Audit and plan
Held: no CRITICAL premise; GA-PG4 and P-36 (fewer slots, more queueing) unchanged. Broke: the plan expected the first-commit measurement to be a clean 4 vs 8 comparison. Run 1 shared the CPUs with my own test runs, so it is reported as contaminated rather than used. A second, idle pair (runs 3 and 4) replaced it.

## 3. Execution (UTC, 27/10)
- 17:58 base read; 18:05 measurement started in the background while the code was written (overlap worked: coding 25 min).
- 18:2x code + tests; first own-checkout gate failed in structure check on the literal census (class: every number written in code or tests counts; 1000, 0.25, 16, 4, 5, 2, 3 ...). Fixed as a class in one commit: timings in seconds with `timedelta` conversion, test counts built from 1, baseline shrunk with `literal_census.py --write`.
- Second own gate failed on "behind base" (base moved by 5 commits during the measurement): merged the base (merge commit).
- Dead ends: `scripts/config set` writes a change store shared by all worktrees of the machine, so the measurement briefly changed the live value of `gate.script_tests_concurrency` for this checkout (my own test of the registry default failed because of it); reset with `--default` after each measurement.
- `scripts/run test <name>` refuses non-executable test files (`gate-test-cache.test.sh`); ran them with `bash` directly.
- `gate_graph.run_commands` results must be equal between serial and parallel runs, so the timings go in a side dict, not in the results (a first attempt broke `test_the_serial_and_parallel_reports_are_equal`).

## 4. Gate
Own-checkout gate-dev: run A structure check FAILED (literal census; script tests also reported `generate.test.sh` intents-doc loader error, which passed when rerun alone and in the later runs: load-sensitive, not reproduced); run B FAILED behind base; runs C and D PASSED (355 s and 308 s cold script tests, 1 slot). Verdict of record from the clean base-tip checkout: see the PR comment. Known env failures (claude-session, root-identity, config) did not appear in the uid-0 own checkout; they appeared in measurement run 2 on the base (root-identity).

## 5. Lessons
- The literal census should be runnable per file with a hint (it already is: `literal_census.py`); a GX-wide brief line "run `python3 scripts/lib/literal_census.py` before the first gate" would have saved a 140 s gate run. Owner: brief template (A Torre).
- `scripts/config set` for a local experiment should offer a per-process override (an env var per key, like `GATE_SLOTS`) so measurements never touch the shared store. Owner: config unit.
- `scripts/run test` should run a registered test file whatever its mode bit. Owner: gate/test infra (GX-ENV).
- Measurements need an "idle" guard: the gate could refuse to report a wall when the load average at start is high. Owner: GX-25 (ETA).
