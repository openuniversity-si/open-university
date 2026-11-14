# GX-FIX-forge-rate-2 — gate traceability (gate-progress)

Daniel's ask: step-by-step monitoring of a gate run. That means the current stage, per-test progress N/M, elapsed vs expected time, the last error, cached vs run tests and a stall signal. Rule: **no per-test GitHub write, ever.**
Incident: a stall of 10 to 19 minutes in `script-tests` was invisible. It sat after the tests had run, inside `record_durations`, which made one GitHub comment per test.

## 1. Current state (verified)

| Piece | Where | What it does |
|---|---|---|
| Stage wrapper | `scripts/lib/gate-runner.sh:55-69` `step()` | `gate_status stage-start`, then the run, then writes `<logs>/<stage>.stage.json` `{name, result, exit, seconds, started_at}`, then `gate_status stage-end`. |
| Status hook | `scripts/lib/gate-runner.sh:9-12` `gate_status()` | Runs only after `begin` has created `<logs>/status.json`. Errors go to `<logs>/status.log` and never fail the gate. |
| Live panel begin | `scripts/lib/gate_status.py:255-268` `begin()`; called at `scripts/gate-local:287,383` (PR runs only) | Builds the plan and expected seconds per stage (`history()`, :59). Forced publish of the comment, plus a `pending` commit status. |
| Live panel event | `gate_status.py:271-283` `stage_event()` | Marks a stage running or passed/failed (reading `<stage>.stage.json`). Unforced `push()`. |
| Throttle | `gate_status.py:241-252` `push()` | Skips the publish when `now - last_publish < gate.status_min_interval_s` (15 s, `config/registry/gate.json:447`). |
| Final | `gate_status.py:286-299` `final()`; `render_final` :123 | Forced final edit (verdict, stages, cached-test list) plus a `success`/`failure` commit status. |
| Script tests | `scripts/gate-local:347` calls `gate_test_cache.py run ... --logs`; `gate_test_cache.py:203-233` `run()` | Computes the keys and cache hits, runs the misses through `gate_graph.run_commands`, builds the results in test order, then `record_durations` (:231). |
| Runner | `scripts/lib/gate_graph.py:135-156` `run_commands()` | Fills `timings[label]` per command as it ends. There is no per-completion callback: nothing is visible until all tests end. |
| Stage output | `gate_test_cache.py` main (~:264) | Writes `<logs>/script-tests.json` `[{test, result, cached, key, source, tail}]` once, at the end. |
| Durations write | `gate_test_cache.py:107-117` `record_durations()` | Now one `publish()` of all `engine.step.measured` events. That kind is in `forge-events.file_kinds`, so `RoutingAdapter` (`forge_events.py:150-185`) appends it to the local JSONL (`FileAdapter`, :106, dir `forge-events.local_log_dir` = `.gate/events`). |
| Durations read | `gate_test_cache.py:98-104` `measured_durations()` | `port.read(repo, None)`. `RoutingAdapter.read` (:170) reads the **main** adapter as well (default `github`, `forge-events.json:74`), so it still pages the repository channel's comments. |
| Rate client | `scripts/lib/forge_rate.py:82-135` `Limiter`; `github_api.py:59-62` `_limiter` | Session state file `{writes[], blocked_until, total, refused}` (`github-client.write_state_path`). It counts **writes only**, per session, not per run. Reads are not counted. |

Gaps: the panel's granularity is the stage. `script-tests` runs as a single black box from stage-start to stage-end. There is no N/M, no last error until the end, no stall signal, and no count of what a run cost on GitHub.

## 2. Options

T = gate wall seconds, S = stages in the run, N = script tests, C = comments on the forge-events repository channel. "Today" = 1 comment create + ≤ min(2S, ⌈T/15⌉) edits + 1 final edit + 2 commit statuses. Every option below is measured against today.

| Option | GitHub writes / reads per run (delta) | Effort | Shows |
|---|---|---|---|
| **A** Local append-only `progress.jsonl` in the run's logs dir, one line per finished script test | **0 / 0** | S | N/M, cached vs run, ms per test, result, the last failure, the time of the last line (a stall is visible with `tail -f`). |
| **B** The throttled panel adds a `script-tests N/M (k cached, last fail X)` sub-line read from A | 0 / 0 if it is refreshed only on stage events. ≤ ⌈T_st/15⌉ extra edits if test completions trigger the unforced `push()`. Still bounded by the 15 s interval, never per test | S-M | N/M and the last error on the PR while the run is going. |
| **C** `gate_progress.py tail [--logs L]`: CLI reading A plus `status.json` / `*.stage.json` | 0 / 0 | S | Current stage, N/M, elapsed vs expected (stage history and per-test durations), the last error, in a terminal or agent session. |
| **D** Stall detector: no new A line for X s (X from the expected per-test time × k), then a stack dump of the stuck test (py-spy, or `faulthandler.dump_traceback_later` in Python stages), written to `<logs>/gate-progress.stall.txt` | 0 / 0 (optional: one forced panel edit per stall, ≤ 1 per stall) | M | A stall signal, plus where it is stuck (stack). This would have caught the incident in seconds. |
| **E** A forge event per test (`engine.step.*` to issue comments) | **N writes + reads per append** (the old tooling cost ~80 writes plus ~20 reads each) | S | Remote per-test history. **Rejected**: it breaks the rule and caused the incident. |

## 3. Recommendation

Make the local file the single source of progress (A). Every viewer (panel, CLI, stall detector) reads that file and never GitHub. Anything that reaches GitHub stays at today's stage-throttled cadence.
Ship the per-run forge counter and the local-only script-tests stage now, and A first in the mini-program. They are cheap, cost 0 GitHub calls and make the next stall diagnosable after the fact.
Then build B, C and D as the gate-progress mini-program, in that order (D is the one that turns an invisible stall into a signal).

## 4. Split

### IN THIS UNIT (this PR, implemented)

1. **The script-tests stage reads and writes only the local file log.** `measured_durations` reads only the log that stores `engine.step.measured` (`ForgeEvents.read(kinds=...)`). `record_durations` dedupes against that log's own window (`ForgeEvents.publish` through `RoutingAdapter.route`). Cost: 0 GitHub calls for 80 tests (test `gate-forge-budget`).
2. **Forge cost counter**: `forge: W writes, R reads`.
   - `gate-local` names a per-run count file in the logs dir (`github-client.count_file_env`). `github_api` appends one line per request to the production API.
   - `gate_report` prints the line at the end of the run, against `gate.forge_writes_per_run_max` / `gate.forge_reads_per_run_max`. The final panel shows it as "before this edit".
   - A script test that leaked to the real forge (H2 in audit.md) now shows up in this count.

Decision (recorded in the PR): `progress.jsonl` (option A) moves to the future list. A line per test as it finishes needs a per-completion hook in `gate_graph.run_commands` (`scripts/lib/gate_graph.py:135-156`), and that file is outside this unit's file list. Building it here would widen the unit. Writing the file at the end would not show live progress.

### FUTURE traceability mini-program (gate-progress; list only)

- Live panel N/M sub-line read from `progress.jsonl` (option B), within `gate.status_min_interval_s`.
- `scripts/lib/gate_progress.py tail`: current stage, N/M, elapsed vs expected, the last error, cached vs run (option C).
- Stall detector with a stack dump (py-spy / faulthandler) when there has been no progress line for X s (option D), plus a registry key `gate.progress_stall_s`.
- Expected time per test from the local measured log only (`.gate/events`), used for "elapsed vs expected" and for X in D.
- **`<logs>/progress.jsonl`** (option A, first item): one line per script test as it finishes, `{test, result, cached, ms, n, m, at}`. Cached hits are written first. It needs an `on_done` hook in `gate_graph.run_commands`. It is local only, and a failed write never fails the gate.
- Progress lines for the other long stages (e2e, unit) on the same schema.
- `gate-noite` report: the slowest tests and the stalls taken from `progress.jsonl`.

Naming: everything here is "gate-progress". "gate-trace" belongs to GX-29.

## 5. GitHub cost per gate run

| | script-tests stage | Rest of the run (PR mode) |
|---|---|---|
| Before (old tooling) | ~N writes (one comment per test, ~80) + ~20 reads each, plus the duration read (⌈C/100⌉ pages) | Panel: 1 create + ≤ min(2S, ⌈T/15⌉) edits + 1 final edit + 2 statuses |
| After (this unit) | **0 writes, 0 reads** (durations live in the local file log only; measured on the fake: 80 tests, 0 calls) | Unchanged panel cadence. B adds at most ⌈T_st/15⌉ throttled edits. The run prints its real `forge: W writes, R reads`. |

