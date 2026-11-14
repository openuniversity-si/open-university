# TX10 (hermetic script tests): plan

From [audit.md](audit.md). One lane (engine). Base `ee091f9d5`.

## 1. Commits (a chain: 3, 4 and 5 share TX10's new test file, so one writer does them in order; each is green alone)

| # | Plan item | Files | Change | Targeted tests |
|---|---|---|---|---|
| 1 | audit | `docs/units/TX10/audit.md` | done (`8feb60f1`) | – |
| 2 | plan | this file | – | – |
| 3 | private `TMPDIR` and scrubbed gate state | `scripts/lib/gate_test_cache.py`, a new `config/registry/test-isolation.json` (+ `scripts/lib/generated/config_registry_test_isolation.py`), a new `scripts/tests/test_gate_test_cache_env.py` + `scripts/tests/gate-test-cache-env.test.sh` + `scripts/tests/covers/gate-test-cache-env.json`, `units/engine-gate-report/unit.json` (the new production files), `CODEOWNERS` (regenerated) | each test gets a private `TMPDIR`: 0755, under `test-isolation.tmp_root`, removed after the run. The test's command is `env -u <name>… TMPDIR=<dir> bash <test>`, because the overlay merged into the gate's environment cannot delete a key. Removed: every name with a prefix in `test-isolation.scrub_prefixes`, except the `test-isolation.keep` list (the slot contract), plus `test-isolation.scrub_names` and the forge count file (`github-client.count_file_env`). The `todo` line stays as the base has it; the wrapper is a new line after it (#683, §3) | `gate-test-cache.test.sh`, the new wrapper, `forge-events.test.sh`, `gate-local.test.sh` (nested gates keep their slot) |
| 4 | the runner | `scripts/lib/gate-runner.sh`, `scripts/tests/gate-local/runner.test.sh` (the one path assertion), new cases in `test_gate_test_cache_env.py` | no copy to `/tmp/gate-local-<stage>.log`: the FAIL line names `$log`, the run's persistent log. A failed stage-record write fails the stage and names the path. B8: the watcher writes `$log.timedout` only when its `sleep` completed | `gate-local.test.sh` (59 = 59), the new wrapper, `gate-classify.test.sh` |
| 5 | `scripts/run test` | `scripts/run`, new cases in `test_gate_test_cache_env.py` | `test` needs the file, not the exec bit; it runs `bash <file>` with `OU_CONFIG_STORE=file` (unless set) and the hermetic harness first on `PYTHONPATH`, the gate's own setup | `run.test.sh`, the new wrapper, `scripts/run test config` with no token from a fresh worktree (no `.tower/config-cache`) |
| 6 | gate + RETRO | `docs/units/TX10/retro.md` | the pinned gate on the exact head; RETRO comment | the gate |

Critical path: 2 → 3 (25 min) → 4 (20 min) → 5 (10 min) → the gate (~9 min for the pinned and report-only runs) → 6, about 75 min against the measured M of 86.

## 2. Premises

| Premise | Blast radius | Status |
|---|---|---|
| A nested gate in a script test shares its parent's slot through `OU_GATE_SLOT`/`_OWNER`/`_SLOTS` | **CRITICAL**: scrubbing them deadlocks every nested gate on a one-slot container | verified, `gate-isolation.sh:66-67`; kept by the registry keep-list; the new test asserts that the slot names survive |
| Slot and lock paths do not depend on `TMPDIR` | a private `TMPDIR` would split the slot dir | verified: `gate.slot_dir` (registry) and `.gate/gate.lock` |
| `$logs` is the run's persistent report dir | the FAIL line's path must stay valid after the run | verified, `scripts/gate-local:280` |
| No consumer parses `/tmp/gate-local-*` | dropping the copy | verified: only `runner.test.sh:13` (changed here) and sample text in `train/test_tier2.py:20` |
| Tests that drop root need to enter their `TMPDIR` | a 0700 dir breaks root-identity and claude-session (seen on #742's evidence run from a 0700 path) | the dir is created 0755 under `/tmp` |

## 3. Pending PRs

- #683 (GS2) edits `gate_test_cache.py`. Its docstring `:19` and `record_seconds`/`longest_first` additions land after `record()`, and its `todo` hunk is already superseded on the base by `longest_first(…, durations)`.
- At its next base merge it takes the base `todo` line. TX10's wrapper is on the following line, so it merges untouched, and #683 keeps only what the base does not already have.

## 4. Final gate

`OU_CONFIG_STORE=file bash scripts/cloud/setup.sh`, then `(export OU_CONFIG_STORE=file; source scripts/cloud/env.sh; unset OU_CONFIG_STORE; scripts/gate-dev --pr 758)`, the sanctioned offline path. Both the pinned and the report-only run must be green: TX10 adds a script test, and the pinned verdict does not run added tests (TX backlog X22).
