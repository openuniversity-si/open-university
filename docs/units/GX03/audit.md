# GX-03 audit: size the gate to its container

Base `4bc4dd04` (mod/roadmap-integration, GX-00/01/04 merged). Read-only findings; evidence is file:line on that base.

## Findings

1. **Script-test concurrency is a literal 8.** `gate_test_cache.run` passes `setting('script_tests_concurrency')` (registry default 8) to `gate_graph.run_commands`, whatever the machine. On a 4-vCPU container that is 2 tests per CPU on top of the other stages (GA2 Q1: cold base gate 614 s, FAILED on timing; G-08).
2. **Gate slots are a literal 3** (`gate.slots`, `gate-isolation.sh` `ou_gate_slot_acquire`), also independent of the CPUs: three gates, each with 8 script tests, share 4 vCPUs.
3. **No ordering.** `todo` is the declared order, so a long test that is declared last starts last and sets the tail of the stage.
4. **No per-test duration is recorded.** `gate_graph.run_commands` times nothing; `engine.step.measured` (forge_events `step_payload`) exists and the SLO/train code already folds it, so it is the natural store.
5. **Contracts that bind the change.** `gate_graph.run_commands` serial and parallel reports must be equal (`test_the_serial_and_parallel_reports_are_equal`), so timings go in an optional side dict, not in the results. The config change store (`scripts/config set`) is shared by every worktree of the machine, so the measurement must reset what it sets.
6. **Readers of `gate.slots`:** `gate-isolation.sh`, `gate-local` (comment only), `gate-isolation.test.sh` (asserted 3, and an alternate registry patched to 2). Generated module: `scripts/lib/generated/config_registry_gate.py`.
7. **Known base failures, not this unit:** `claude-session`, `root-identity`, `config` (`RegistryMemo.test_a_rewritten_file_is_read_again`) script tests; uid-65534 fs-encoding in cloud containers.

## Cold-gate measurement (plan D-A16, GA2 Q8)

Throwaway worktree off the base tip, empty test cache, `scripts/gate-dev --sha <base>`, idle 4-vCPU container, only `gate.script_tests_concurrency` changed (4, then 8). Numbers are in the section "Measurement results" appended below when the runs finish.

## Measurement results

Container: 4 vCPUs (`nproc` = 4), Linux, local PostgreSQL 18.6, throwaway worktrees, `GATE_TEST_CACHE_DIR` empty per run (script tests cold; the tier-1 caches of the other stages were warm after the first run unless stated). Idle except where stated.

| # | Code under test | Script-test concurrency | Slots | Gate wall | Script-test stage | Result |
|---|---|---|---|---|---|---|
| 1 | base `4bc4dd04` (`gate-dev --sha`) | 4 (config set) | 3 | 556 s | 238 s | FAILED: `gate-graph.test.sh` (report-order timing test) and `root-identity.test.sh`. **Contaminated**: my own test runs shared the 4 vCPUs (load average 22 at start); not a valid timing |
| 2 | base `4bc4dd04` | 8 (config set) | 3 | 239 s | 115 s | FAILED only on `root-identity.test.sh` (uid-65534 Python fs-encoding crash, known env failure). Integration/unit/build stages were tier-1 cache hits from run 1, so not fully cold |
| 3 | this PR (`b25f17f3`, own checkout) | 4 (derived: floor(4 x 1.0)) | 1 (derived: floor(4 x 0.25)) | 355 s | 314 s | PASSED, all stages (the known env failures did not occur in this uid-0 checkout) |
| 4 | this PR (`b25f17f3`, own checkout) | 8 (`gate.script_tests_per_vcpu` set to 2) | 1 | 308 s | 273 s | PASSED, all stages |

Reading: the script tests are partly wait-bound, so 8 workers on 4 vCPUs is about 13% faster than 4 when they have the machine to themselves (run 3 vs 4). The failure of the base gate (GA2 Q1: 614 s FAILED) came from three gates times eight script tests competing for 4 vCPUs; with one slot the gate passes on a cold script-test cache. Registry default stays `gate.script_tests_per_vcpu` = 1.0 as specified; `2` is a one-key follow-up through `scripts/config` if a later measurement on several containers agrees. `gate.slots_per_vcpu` stays 0.25 (one slot on 4 vCPUs): no run here measured two gates at once, so there is no evidence to raise it.

The D-064 (f) ceiling of 180 s is still exceeded by every cold run (308-355 s); it warns and never fails (unchanged, P-09). The wall of a cold run is dominated by the script tests; making them faster is GX-08/GX-13 territory (selective and cached script tests), not this unit.
