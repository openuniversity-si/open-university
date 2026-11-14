# Postmortem 2026-10-26: performance tests measured under parallel load

Blameless. Owner of the fix: PR H0 (#502), "performance tests run alone in their own gate stage". Standard: D-069
items 5 (hermetic, deterministic tests), 9 (fix the class, not the instance) and 14 (performance budgets in config).
Gate change under D-065, cited per D-025.

## What happened

- **#497** (gate-dev, 4 vCPU cloud VM): `apps/web/test/int/read-latency.int.test.ts` failed "lists 10,000 courses in
  under a second" and "lists 10,000 redirects in under a second" at 1126, 1266 and 1277 ms against the 1000 ms budget.
  Run 3 of 3 passed. The file alone on the same head passed 3 of 3.
- **#489** (F17) was blocked by the same tests at 1534 and 2583 ms. In the same runs, unit tests that walk the whole tree or
  spawn subprocesses ran past vitest's 5000 ms per-test timeout and passed alone:
  `scripts/lib/check-architecture.test.ts` "enforces every architecture rule on the real tree" (5.96 s),
  `scripts/tower-catalog.test.ts` "names the missing variable without printing the file, and passes the secret on a
  descriptor" (6.2–6.5 s) and "uses exported credentials when no env file exists, and does not send them to a refused
  host" (5.7 s), and `scripts/lib/absolute-literals.test.ts` "the census of the production tree equals the exception
  list" (5.4–5.9 s).

- **#502** (H0's own first gate-dev run, before this file's last commit): `scripts/lib/catalog-cli/commands/media.test.ts`
  "delegates the installed symlink to tower-catalog media without calling itself" (spawns the bash wrapper and Node)
  timed out at 5401 ms in the parallel unit suite. It joined the heavy convention in the same PR.

None of these was a regression in the code under test. The cost of the reads and the work of the tree walks did not change
between the red and green runs.

## Why

A wall-clock assertion measures the machine as well as the code. D-064 (f) made gate-dev parallel to stay under its
180 s ceiling: the database lane (integration tests, `maxWorkers: 4`), lint then typecheck, unit tests
(`maxWorkers: 2`), the suite union and the script tests all run together on the same 4 vCPUs. A budget of 1000 ms, or a
5000 ms per-test timeout, then depends on what else is scheduled in that second. That is a property of the gate
schedule, not of the test. Two more files had the same shape and had not failed yet: `incremental-compile.test.ts`
(two 2000 ms budgets) and `projections.int.test.ts` (a 2000 ms repeat-publish budget).

## The class fix

1. **A stage that runs alone.** `performance tests` (`pnpm test:perf`: vitest projects `perf`, then `perf-int`, one
   worker each) starts in `scripts/gate-local` after `gate_fixed_join` and a final `join_steps`. Every suite, both
   builds, the database lane and the browser stages have finished by then. It held `/tmp/tower-perf.lock` until WR1, which replaced the host lock with per-worktree resources; the
   `gate.slots` limit is the CPU guard across gates. It is part of DEVELOPMENT (gate-dev and the nightly), of the `web-check` area group,
   of the stage baseline and of the nightly area map. Its line prints the stage's own duration.
2. **Conventions in the registry.** `config/registry/battery.json`: `*.perf.test.ts` (no database) and
   `*.perf.int.test.ts` (an isolated database clone per file, as in int) assert elapsed time. `*.heavy.test.ts` walk
   the whole tree or spawn subprocesses. `vitest.config.ts` reads them: the unit and int projects exclude them and the
   perf projects include only them. The perf projects keep the timeouts of the project each file came from. No timeout
   or threshold changed.
3. **The budget in config.** `budgets.admin_list_read_ms_max` = 1000 ms in `config/registry/budgets.json`, read by
   `read-latency.perf.int.test.ts`. It is the same value, and no retry or best-of-N was added.
4. **Moved, not lost.** The three timing files moved whole, so their other assertions moved with them. The five
   heavy cases (the four of #489 and the media symlink case of #502) moved to `*.heavy.test.ts` files, and the bash wrapper block moved whole because every case in it
   spawns bash and Node. `gate-suite-renames.json` maps each baseline identity to its perf row, and the suite union
   now runs over unit, int, perf and perf-int.

## How it is enforced

Retired by D-298 (VAZÃO F45); the record below is how it was enforced while the vitest product lived here.

- `scripts/lib/perf_tests.py`, a structure-check module (the `structure check` stage): a test file under
  `battery.timing_scan_roots` that compares a `performance.now()`, `Date.now()` or `process.hrtime` delta, or a name
  bound to one, with a budget (`toBeLessThan`, `toBeGreaterThan`, their `OrEqual` and `not` forms, or `assert`)
  must follow a registered convention. `vitest.config.ts` must read the conventions. Timeouts, deadlines, past
  timestamps, recorded samples and plain clock reads are not flagged. Proof: `scripts/tests/test_perf_tests.py` ›
  "test_elapsed_time_assertions_in_a_parallel_suite_fail", "test_ordinary_timeouts_and_clock_reads_pass",
  "test_repository_has_no_timed_test_in_a_parallel_suite". On the tree before H0 it names exactly read-latency,
  incremental-compile and projections.
- `scripts/lib/gate_suite.py` (the `suite union` stage) applies `perf_tests.listing_errors` to the real vitest
  listing: a convention file in unit or int, or a plain file in a perf project, fails the union. Proof:
  `test_perf_tests.py` › "test_listing_puts_conventions_only_in_perf_projects".
- The heavy convention has no static signature (a subprocess or a tree walk is ordinary in a unit test). A new heavy
  test is named `*.heavy.test.ts` when it runs near the timeout. The listing check keeps the named ones out of the
  parallel suites.

## Follow-ups

- **B1 (performance budgets against a baseline, plan v3.1 delta).** The perf stage is where B1 measures. Each file
  should emit `engine.step.measured` (M2's port; `scripts/lib/forge_events.py` does not exist yet). The baseline
  should come from those events, and a regression over the registered tolerance should fail. The 2000 ms literals of
  incremental-compile and projections move to `config/registry/budgets.json` with B1, and a budget may only tighten.
- **Machine load across gates.** Up to `GATE_SLOTS` gates share a machine (D-064 (b)). The perf lock serializes
  their measurements, but another gate's build can still run alongside them. The train's runner (M3) should give the
  perf stage a quiet slot when slots are scheduled per machine.
- **Heavy detection.** If heavy tests keep timing out, record each test's duration in the listing and flag one past
  a registered share of its timeout.

## Preventing check

D-298 (VAZÃO F45) retired `perf_tests.py`: the vitest product, its `performance tests` stage and the conventions it
enforced left with Open University (D-111, D-113), so the rule sent a timing test to a stage that no longer exists.
The engine's script tests run under the hermetic layer (D-069 item 5): a test takes its time from the injected
clock, which starts at a registered instant and moves only when the test advances it, so it measures its logic, never
the machine's load.

- check: scripts/lib/hermetic.py
- test: scripts/tests/test_hermetic.py::test_the_clock_starts_at_the_registry_instant_and_moves_only_when_advanced
