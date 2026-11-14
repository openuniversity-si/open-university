# GATE-FAST: audit (measured)

Decision: D-076. Premises: P-56, P-43, P-53. Machine: the cloud container of this session, 4 vCPUs (`nproc`), the
same class the train and the owner sessions run on.

## 1. Sources

- The ledger (issue #548 through the `forge_events` port): 117 tier-1 `gate.passed`/`gate.failed` v4 verdicts with
  per-stage `started_at` and `duration_ms`, read by `scripts/lib/gate_timing_report.py --ledger` (29/10 19:00 UTC).
- One measured cold run on this container, before any change of this unit: `OU_GATE_COLD=1` with a fresh
  `GATE_BUILD_CACHE_DIR` and `GATE_TEST_CACHE_DIR`, `scripts/gate-local --dev --sha 9830863ab5fe` (PR #802's head,
  pinned to the base tip 13ba2b0e25f1): every stage, the full script suite (109 tests), the one gate on the box.
- The per-test durations of that run (`engine.step.measured gate:script-test:*` in the pinned tooling's local log).

## 2. The cold run, stage by stage (seconds from the start)

| Stage | Ends at | Own time |
|---|---:|---:|
| prerequisites (metadata, secrets, structure, drift, schema) | 14 | 11 (structure check) |
| install (frozen lockfile) | 16 | 2 |
| suite union | 99 | 83 |
| unit tests (1,790 tests) | 147 | 130 |
| integration tests (651 tests) | 156 | 140 |
| lint | 166 | 149 |
| typecheck | 191 | 26 |
| **script tests (109 tests)** | **266** | **250** |
| build (test engine), browsers, build (production) | 294 | 13 + 13 + 14 |
| e2e smoke | 325 | 29 |
| performance tests | 355 | 30 |
| **wall** | **359** | |

The script tests are the critical path: they start with the install and end 75 s after the last web check. Their 109
tests add up to **971 test-seconds** on 4 workers that share the 4 vCPUs with suite union, unit, integration and lint.
The longest: `forge-events` 110 s, `claude-session` 92 s, `config` 78 s, `push-guard` 48 s, `structure-check` 48 s,
`gate-db` 43 s, `train-reuse` 40 s, `train` 39 s.

## 3. The ledger (117 tier-1 verdicts, stage wall = first stage start to last stage end)

| Set | n | wall p50 | wall p90 | script tests p50 | p90 |
|---|---:|---:|---:|---:|---:|
| all | 117 | 141 s | 358 s | 110 s | 315 s |
| with web stages | 57 | 210 s | 405 s | 112 s | 323 s |
| scripts only | 60 | 121 s | 296 s | 107 s | 285 s |
| no cache hit (the cold shape) | 69 | 204 s | 366 s | 152 s | 350 s |

Per stage p50 / p90: script tests 141 / 743 s, integration 147 / 366 s, unit 116 / 348 s, suite union 73 / 180 s,
lint 50 / 167 s, typecheck 30 / 130 s, structure check 55 / 87 s. The ledger's p90 critical path is 1,026 s.

Selection: **107 of 118 verdicts ran the web battery `full`**; 11 were `scoped`. The reason on engine PRs is
`gate.full_battery_globs`: any change under `scripts/lib/**`, `scripts/gate*`, `config/**`, `units/**` or
`CODEOWNERS` runs all 1,790 unit tests (#802: "full-battery class: CODEOWNERS"), although the area plan of such a PR
asked for `unit tests` only because a handful of web tests read a scripts file (TX20, `gate_web_readers`).

## 4. Where the ~12 min comes from

1. **Work, not waiting**: a cold verdict burns ~1,000 CPU-seconds of script tests plus ~500 of web checks, on 4 vCPUs.
   The measured cpu of #802's cold verdict was 685 s for 220 s of stage wall (3.1 cores busy): the box is saturated, so
   more workers on the same 4 vCPUs cannot halve it.
2. **Nothing reused**: `--cold` (D-075) ran with an empty per-test store and an empty stage store, so every selected
   test ran even when its inputs were byte-identical to a passed run. After each train merge the next PR is
   re-verdicted cold from zero: 10 PRs = 10 full cold runs in a row (D-075's resync).
3. **One gate per box**: `gate.slots_per_vcpu` 0.25 gives `slot 1 of 1` on 4 vCPUs. A re-verdict that arrives while
   another gate runs waits for the whole of it: 6 min of work becomes 12 min of wall.
4. **Full web selection on engine PRs** (section 3): ~130 s of unit tests that no changed file can affect.
5. Defect seen on the way: `cost.wall_s` and `cost.queue_wait_s` of the v4 proof are epoch seconds (1.79e9), not
   durations (`gate_proof.cost`); the timing report reads stage times instead. Recorded, not fixed here.

## 5. Order of attack (largest slice first)

| # | Lever | Slice it removes | Commit |
|---|---|---|---|
| a | content-addressed reuse at tier 2 and under `--cold` | every unchanged test of a re-verdict (item 2) | 3 |
| b | web selection by readers for tooling paths | ~130 s of unit tests on engine PRs (item 4) | 4 |
| c | script tests sized to the box (longest first, workers per vCPU) | the tail of the critical path | 5 |
| d | concurrent verdicts of distinct PRs, admission serialized | the slot wait (item 3) | 6 |

Before/after on the same input is in [retro.md](retro.md).
