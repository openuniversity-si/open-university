# GX-19 RETRO

## 1. Brief quality
- Branch name conflict: the brief said `mod/gx19`, the session designated `claude/gx19-stage-timeouts-eviction-dpnzge`; the designated one was used (one branch, one PR).
- The brief's `gate.stage_timeout_s` map cannot exist: the registry meta-schema allows `object` parameters only for locale text (`x-text`). Resolved as an array of `{stage, timeout_s}` with a `*` entry.
- "Others 300 s" would be a false red for install, builds, e2e and performance on a cold run; those got explicit 600-900 s entries (GA-PG5: never shorter than the field p99). The p99 numbers were not available to this session; raising an entry is the rollback.
- Not stated, and costly: the literal census counts numbers in **tests** too (only 0, 1, -1 allowed) and unit tests may not read the wall clock.

## 2. Audit and plan
- Held: GX-38 pre-claimed every path; no manifest or CODEOWNERS edit was needed. `timeout(1)` cannot wrap shell-function stages (`run_script_tests`, `secret_tree`), so a bash watchdog replaced it (plan assumed `step` could simply wrap).
- Broke: `gate-local.test.sh` asserted every hook is a bare `:`; narrowed for exit (and later merged with GX-05's pin change).

## 3. Execution
- Commits 1-5 as planned (audit/plan, registry, gate_gc.py + exit hook, runner timeout, atomic publish).
- Failure class 1: structure check refused 24 literals (124, 5, 8, 3 in the runner; every number in my test). Root cause: new constants written inline. Class fix in one commit: three new registry keys (`kill_grace_s`, `timeout_exit_code`, `log_tail_lines`), one `gate_gc.py limits` call for the shell, tests deriving every number from the registry or fixture shape, wall time taken from `step`'s own stage.json.
- Failure class 2 (same commit family): the hermetic rule refused `time.time()`/`monotonic()` in a test.
- Failure class 3: PR body checklist needs `- [ ] 1. ...` (with a period); my first body used `1 `.
- Waits: the pinned gate runs the stages of the base tip; two full gate runs (own checkout report-only + base tip verdict) were started per round. The registry read through the base tooling (coordinator note) was fixed by GX-FIX-registry (#715); base merged afterwards with one conflict in `gate-local.test.sh`.

## 4. Gate
Runs: (a) structure check red on literals (class 1), (b) red on PR body format, (c) the run after merging #715; the numbers are in the PR comments.

## 5. Lessons
- Brief template: say that tests are in the literal census and under the hermetic rules, and that registry `object` params are text-only (owner: gate-excellence brief author).
- A shared helper for "read a stage's limits from the registry in shell" now exists (`gate_gc.py limits`); other stage-level settings should use the same shape instead of new constants (owner: engine-gate-run).
- `scripts/structure-check` and `literal_census.py` run in about 5 s locally: run them before the first push for any new script (owner: author; already in BRIEF STANDARD v2 item 4).
