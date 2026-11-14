# U4 engine-commit-plan: retro

1. **Brief.** It asked to move files and set a contract entry, but the unit is Python/shell under `scripts/` and has no `@ou` address form (`unit_addresses.py`);
   the brief's own fallback (keep in place) applied. Missing: the contract slot cannot be verified without an address, so it is left empty. Wrong: the branch name
   (`mod/u4-...`) differed from the session's designated branch; the designated one was used.
2. **Audit and plan.** P-03 held (files stay logical). P-05 held: no `x-literal-sites` entry names the unit. Unexpected finding: the battery was RED at 12.3 s
   (limit 10 s), which became the real work; the plan was written after that finding, no later change.
3. **Execution.** Timeline (UTC): 06:49 audit, 06:49 plan, 06:52 tests in-process, 06:52 manifest battery, 06:55 merge of base, gate. Root cause class of the one failure:
   tests that start an interpreter per case (cost ~0.5 s each, 9+ cases). Fixed for every occurrence in the unit's tests (commit-check, plan-tick, pr-ready CLIs);
   the remaining subprocesses are the git fixtures and one `config.py get` CLI check. No dead ends. One tool misstep: a background subshell inside a background command
   never wrote its log; rerun as a plain background command.
4. **Gate.** 1 run, PASSED, 140.3 s (ceiling 180 s): structure check 48.0, schema compat 1.8, secret scan 2.0+1.2, generated drift 0.4, script tests 1.2. No known timing-sensitive defect hit.
5. **Lessons.** (a) Tests should call `main(argv)` in-process; a lint/gate check on `subprocess` + `sys.executable` in tests would prevent the class (owner: engine-hermetic-tests).
   (b) Brief templates for non-TS units should say up front that the contract slot waits for an address form (owner: units/U3a). (c) Battery margin is 14%; a plan-tick git fixture
   cache would widen it (owner: engine-commit-plan).
