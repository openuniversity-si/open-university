# GK1 retro

## 1. Brief quality
- "Full battery" was loose: the failing run was `gate-dev` with the full plan, where `script tests` run in parallel and `join_steps` in `gate_fixed_stages` folds their failure into `failed`. The cause was the same (`failed` as a skip guard) but the line that skipped `e2e smoke` was the `$failed -eq 0` before the e2e run, and the mode matters because known defects are adjudicated only for `forge-events.tier1_gate_modes` (`dev`).
- Good: the goal was measurable and named the class. Missing: the brief did not say the unit manifest (D-067 (6)) and CODEOWNERS must follow a new `scripts/lib` file.

## 2. Audit and plan
- Held: one flag is the cause; known defects are decided only after the run; `.stage.json` must not be reused for skips.
- Changed: planned a `gate_unless_blocked` wrapper for every guard; in execution a gate-wide blocker is right only for install and DB classify, while the browser inventory blocks just the e2e run (a global block would also have skipped performance tests). `gate_skip` got a stage-local blocker argument.
- Missed in the plan: unit ownership of new files (structure check) and the generated CODEOWNERS.

## 3. Execution (commit times, local clock)
06:12 audit+plan, 06:13 skip helpers, 06:14 report, 06:17 gate-local, 06:35 manifest, 06:40 CODEOWNERS. Failures and classes:
- Test variable collision: my scenario helper reused the test file's `failed` counter, which showed as a bogus "1 failed" and looked like the base defect. Class: shared mutable name in a sourced-script test. Found by reading the missing FAIL line, not by a rerun.
- A mutation check (inventory guard back to `failed`) confirmed the new checks fail when the fix is undone.
- An accidental `git checkout` on `scripts/gate-local` during the mutation check reverted my edit; recovered from the stash entry, nothing pushed was lost. Class: mutation on the working tree. Use a copy next time.
- Structure check refused `gate_skips.py` (no unit) and then CODEOWNERS drifted after the manifest edit: one class (new file in a unit-owned tree), two gate runs.
- The second class was seen once only; the first gate run's 555 s `script tests` stage was cold cache.

## 4. Gate
Three `gate-dev --pr 577` runs. 1: structure check (unit ownership), script tests (gate-local.test.sh, KD-024bbecb, KD-4db6e693). 2: generated drift CODEOWNERS plus the two known defects. 3: PASSED on 9272533a; the only reds were KD-024bbecb and KD-4db6e693, which the report adjudicated as known. This dev plan is scoped without web changes, so `e2e smoke` was not in the plan; the e2e case is proved by the hermetic tests (`gate-local.test.sh` scenarios, `test_gate_report_skips.py`), not by a real browser run. Total 176 s on the last run.

## 5. Lessons (change, owner)
1. A new file under `scripts/lib` fails structure check and then CODEOWNERS: add a line to the gate-lane brief template ("new files join a unit manifest; run `scripts/generate codeowners`") or make `scripts/generate --check` part of `commit-check --local` (owner: gate-lane, LR1 local checks).
2. Sourced-script tests share variable names with the helpers they call: keep scenario helpers in functions with `local` variables, and prefer a counter name like `_t_failed` in tests (owner: gate-lane).
3. LR-8ad89017 (gate-local.test.sh reads the shared config store): this unit set `OU_CONFIG_STORE=file` on the alternate-registry check; the lesson can be applied (owner: gate-lane).
4. Known defects are decided after the run and cannot be told at schedule time: any future stage guard must read a dependency, not `failed`. The `no stage waits on the verdict flag` check in `gate-local.test.sh` enforces it (owner: gate-lane).
5. Mutation checks go in a throwaway copy, never on the working tree (owner: every lane).
