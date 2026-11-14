# TX10 (hermetic script tests): retro

Base at the last merge: `5bc28916` (`mod/roadmap-integration`). Commits: audit `8feb60f1`, plan `9178730a` (first
session), then `f7648ccb` (Plan 3), `49fcc5c3` (Plan 4), `1740a9e2` (Plan 5), and this retro (Plan 6), with base
merges `4ecf5853` and `14470bc6`. The gate's stage table is in the PR's RETRO comment: it runs on the head that carries
this file, so it cannot be in it.

## Brief quality

- Evidence held, with two corrections recorded in [audit.md](audit.md). First, without the pin the config failure shows
  in `test_config.py` (3 errors), not at `test_config_api.py:281`. Second, 24 `*.test.sh` lack the exec bit, not 22.
- The brief's DONE says no `OU_GATE_*` reaches a test child. The plan keeps the slot contract (`OU_GATE_SLOT`,
  `_OWNER`, `_SLOTS`, now `gate.test_env_keep`), because a nested gate in a script test would otherwise wait for the
  slot its parent holds. The fixture asserts that these three are the only `OU_GATE_*`/`GATE_*` names a child sees.
- The brief names `test_config_api.py:281`. The same cause appears in nine more store-key reads, in
  `test_config_api.py` and `test_config.py`; all ten moved in one commit (fix the class).

## Premises

| Premise | Held? | Evidence |
|---|---|---|
| P-46 (cited by the brief) | not tested here | — |
| Nested gates share the parent's slot through `OU_GATE_SLOT*` (CRITICAL) | held | the gate-local suite (nested runners) passes, 59 = 59, with the scrub on |
| Slot and lock paths do not depend on `TMPDIR` | held | `gate.slot_dir` and `.gate/gate.lock`, unchanged |
| No consumer parses `/tmp/gate-local-*` | held | only `runner.test.sh:13` (changed) and sample text in `train/test_tier2.py:20` |
| A test that drops root can enter its `TMPDIR` | held | 0o755 under `gate.test_tmp_root`; the fixture checks the mode |

## Failures and their root-cause class

1. **Two sessions on one branch (process).** A second session was launched on `mod/tx-hermetic` while the first was
   still running. The first had pushed the audit and the plan 3 minutes earlier, and later stopped on a permission
   prompt. The second session's first push was refused (non-fast-forward). It stood down without pushing and dropped
   its local commit. It resumed only when the coordinator assigned #758 to it, with the first session blocked for over
   an hour.
2. **Literal census (code, mine).** `parents[2]` and a `"1s"` duration in the new test exceeded the base census. The
   prepush caught both; one became `.parent` chains, the other a named `LIMIT_S`.
3. **B8 did not reproduce on its own (test design).** 0 of 30 natural runs hit the race. The fixture forces it: a
   `kill` wrapper holds the runner after each signal until the watcher has marked the stage or died. On the old runner
   it prints `FAIL env: stage "probe" ran past gate-gc.stage_timeout_s (1s)` for a stage that failed in 0.089 s.
4. **`claude-session` past a 120 s probe limit (not root-caused).** Through `scripts/run` from a fresh worktree with no
   token, the test ran past the 120 s limit I gave it. In the main checkout it passes in 46 s run the gate's way and in
   55 s through `scripts/run`, so the cause is the worktree or the missing token, not the exec bit or the pin.

## Gate runs

See the RETRO comment on #758 (pinned gate, `scripts/gate-dev --pr 758`, on the exact head).

## Lessons

| Lesson | Concrete rule or tool change | Owner |
|---|---|---|
| A unit can be launched twice onto one branch | Before launching a lane session on an existing branch, check the last push time and the owning session's status; resume only a session that is stopped | coordinator (launcher) |
| A race fixture must force the interleaving, not hope for it | Hold the process under test at the race point (here a `kill` wrapper that can see the runner's locals), and show the fixture failing on the old code | test authors (TX program) |
| The overlay env of `gate_graph.run_commands` cannot delete a key | Scrubbing a child's environment is done in the command (`env -u`); a future `run_commands(env_remove=...)` would be cleaner | engine-gate-report |
