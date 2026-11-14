# engine-test-support: retro (U4)

1. **Brief.** Asked for a move, a contract, a zero-literal check and a green battery. Missing: the engine units have no
   address form, so "move" and "contract" are unreachable (the battery's contract step needs an address); the 10 s
   battery limit cannot hold for 14 serial shell suites (60 s). The brief did allow keeping files in place.
2. **Audit and plan.** P-03 held (units logical). Plan did not change. The contract slot was left empty on purpose
   (filling it turns the battery red); the surface is recorded in audit.md.
3. **Execution.** Failures: `gate-isolation` (2) and `invoker-tooling` (2) failed on base. One root-cause class: tests
   build a hand-picked partial copy of the repo that lags the library (missing `contracts/`, `gate_select.py`,
   `adapters/`). Fixed in both unit files in one commit; the same shape remains in `gate-db.test.sh` and
   `gate-local.test.sh` (other units). No dead ends; about 1 h wall from launch to gate.
4. **Gate.** One run on c80c7e94: PASSED in 410 s (script tests 288 s; ceiling 180 s exceeded, a warning). It printed
   `FAIL scripts/tests/generate.test.sh` (`intents-doc.ts` node error), not a file of this unit, yet recorded the pass.
5. **Lessons.** (a) A shared helper that copies a repo tree from a manifest, for tests, so lib growth cannot break
   them (owner engine-hermetic-tests). (b) Battery should run script tests in parallel and carry a per-test budget
   (owner engine-battery). (c) The gate should not record a pass while a script-test stage prints FAIL (owner
   engine-gate-run). (d) Brief template: say what an engine unit's contract entry is when no address exists
   (owner engine-units).
