# BASEFIX-shellcheck: audit

## Brief
The base `mod/roadmap-integration` (tip `c003303d0`) fails its own pinned gate (GX-05):

- `shellcheck`: 31 findings in 11 test files and `scripts/lib/gate-isolation.sh`.
- `script tests`: `scripts/tests/claude-session.test.sh` and `scripts/tests/gate-db.test.sh` (gate-db flaky).
- `Neon PR acceptance` (inside script tests).

Goal: the base green on its own gate. No new feature, no loosened timeout, threshold or assertion.

## Cited sources (verified on c003303d0)
All twelve files of the brief exist. The shellcheck stage is `scripts/gate-local:373`; its file list is the gate's.
`Neon PR acceptance` is not a gate stage name on this base: it is the acceptance step `gate-db.test.sh` drives through
`scripts/gate-db` (stub `neon-pr accept`), so it shares that suite's verdict.

## Reproduction (this machine, 2026-10-28 15:13 UTC)
`scripts/gate-local --sha c003303d0b1cb8455013c61ff9fa875138a1efad`, exit 1, 1108.8 s:

| Stage | Result | Class |
|---|---|---|
| shellcheck | FAIL (25.8 s) | env |
| script tests | PASS (307.0 s), `claude-session` and `gate-db` both PASS this run | - |
| unit tests | FAIL: `ou-addresses.test.ts` TX32 timed out at 5000 ms | code |
| capture regression | FAIL: killed at `gate-gc.stage_timeout_s` (300 s) | env |
| e2e + a11y | FAIL: killed at 300 s | env |
| all other stages | PASS | - |

Caveat: I ran the targeted script suites of my shellcheck edits on the same machine while this gate ran, so the unit
timeout and the two 300 s kills were measured under extra load. They are not in the brief's 12:06 measurement. The
head's own gate (step 4) is run with nothing else on the machine and settles whether they are load or base defects.

## Shellcheck: the version is not pinned
`shellcheck` is not in the toolchain (`config/registry/toolchain.json`, `.toolchain/bin`); the gate uses whatever is on
`PATH`. This machine has 0.9.0. With the gate's own file list:

- 0.11.0 (vendor release, run from the scratchpad): 32 findings, exactly the brief's 12 files (18 SC2016, 6 SC2031,
  3 SC2015, 2 SC2034, 2 SC2155, 1 SC2167). The brief's machine ran 0.10 or later.
- 0.9.0: the same 32 plus 7 more: SC2119 x3 (`ou_test_db_ensure` called without its optional URL in `gate-local`,
  `scripts/cloud/setup.sh`, `scripts/cloud/env.sh`) and SC2317 x4 (`runner.test.sh`'s deliberate `date` stub, which
  0.10+ reports as SC2329 and the file already disables under that code).

The head must be clean under both, or the gate stays red on any machine with the other version. The unpinned tool is
a D-027 gap (the environment is code); it is a lesson for the env owner, not fixed here.

## Findings by kind
- SC2016 (18): two different things. (a) Literal patterns given to `grep` that contain a `$` (`hooks`, `preflight`,
  `verdict`): the finding is a false alarm, but double quotes with `\$` pass the very same string and say so.
  (b) `bash -c '... "$1"' _ arg`: in `gate-db` and `gate-result-cache` the child shell does nothing a function in the
  test shell cannot do (the `check`/`step` harnesses run functions); in `budget` and `hook-pin` the child shell is
  the point (it sources a library away from the test), so the finding is wrong there and gets one reasoned directive
  each (budget: one helper replaces three copies).
- SC2031 / SC2167 (`gate-worktree-resources`): `source gate-isolation.sh` inside `$( )` and `( )`, repeated per call.
  Sourcing it once in the test shell (it only defines functions and one path) removes both.
- SC2015 (`gate-heavy-db`): `A && fail || expect "$?"` becomes an explicit `if`.
- SC2155 (`gate-isolation.sh`, `merge-phase`): declare and assign separately; merge-phase uses the port
  `rest_fake_start` already returned instead of reading the port file again.
- SC2034: `verdict`'s `scen_failed` is now asserted (both scenarios must leave the verdict red); `rest-fake-start.sh`'s
  `rest_fake_port` is that file's output to the sourcing suite (its header says so), so the finding is wrong there.

## The two suites
- `gate-db.test.sh`: 23/23 in the base gate and once standalone (553 s standalone: it waits for the host-wide gate
  slot while another gate holds it; inside a gate it inherits the parent's slot). Earlier failures on record:
  hand-kept lib list (HD1, GX-01), `forge_events` import (GX-29), `rest fake did not start` (BD1).
- `claude-session.test.sh` (`test_claude_session.py`): 13/13 in the base gate and once standalone (16 s). On record:
  load-sensitive psql (`drop database` 30 s) and GX-ENV machine-identity failures (`docs/programs/live-planning/audit.md`
  L6, `docs/programs/gate-excellence/audit-1-fable.md`).
The failure modes are investigated under load in the plan's steps 4 and 5.

## Root causes (found after the plan; each reproduced on demand)
- **Gate runner watcher race** (gate-db, gate-local). `gate_run_limited` (`scripts/lib/gate-runner.sh`) TERMed the
  watcher subshell the moment a stage ended. A signal that lands on a subshell bash has just forked, before it resets
  the traps it inherited, runs the caller's EXIT trap there. Through the real `step` with an instant stage, the
  caller's work dir was deleted 4/300 times. In `gate-local` that trap is `finish` (verdict, record removal, checkout
  and logs removal). gate-db runs five nested gates of instant stub stages, and a stray `finish` removes `$logs`, so a
  later stage (`Neon PR acceptance`) cannot write its record. That is the brief's "Neon PR acceptance" line: it is the
  dumped output of a red gate-db, not a separate failure. The gate-db event on the base (KD-6bdaf1ee, 15:04 UTC) kept
  only the tail line, so its failing check is not on record; the mechanism is the reproduced one. The same race
  failed `gate-local.test.sh` (`runner started_at`: the record's directory was gone) in a full script-test run here.
- **claude-session, shared stamp** (KD-c9225259, 06:04 UTC): `AssertionError: (N, b'{"github": ...}') != None` at the
  shared-stamp equality check. Any network-mode preflight in the checkout writes that cache by design
  (`credentials.py`). Reproduced 3/3 with a concurrent preflight.
- **claude-session, swept database**: its throwaway database sat idle from `setup.sh` to its assertion (1.7 s to 12.2 s
  of each run), and every gate ends with `gate_db_sweep`, which dropped idle throwaway databases. Reproduced 2/2. The
  class is in `test_db.residue()`: "no live backend" was taken for "abandoned", so any test's database could be swept
  between create and use (`test_test_db.py` too, and its own sweep test could drop other suites' databases).
