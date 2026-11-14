# TRAIN-DEFINITIVE — validation and remaining acceptance

## Final owner acceptance — 2026-11-02 22:19 BRT

**Outcome (c) is closed by Daniel's explicit owner decision.** Daniel accepted the measured **10.523 s ordinary
gate on `ea020515d91cf2aa0ba9f2b2c65fd072db452424`** and approximately **16.8 s cold**, and instructed this unit to stop
further speed optimization because more time on it would itself be the bottleneck. The underlying 10.523 s record
below retains its exact D-076 cold-mode flags; the owner's acceptance names the delivered ordinary gate behavior.
This closes the acceptance criterion by decision; it does not claim that these numbers are below ten seconds.
The enforced `service.job_budget_s = 10` remains unchanged. Achieving the ten-second VM performance target belongs
to a later unit, using the deployed phase data. No further speed work is required for this PR.

All requested failure families are fixed: defect-lifecycle, lessons, plan-tick, planner concurrency and PR creation.
Registry reader declarations and operation call-site metadata are complete. The latest hand-run full builder on
`f2ec86afe` judged **145 script suites: 143 executed, two reused after actual isolated-root execution, zero failures**.
Targeted current counts include service 108; control-plane 57; forge-events 288 (283 pass, five optional live skips);
planner-role 17; defect-lifecycle 4; lessons 52; plan-tick 54; PR creation 3; configuration 104; readers 8;
operation relations 42; structure 69; schema compatibility 15; hygiene 11; gate-local 65; v4 proof 15.

The final delivery gate is run for correctness with bypass disabled and the complete PR selection. Further timing
benchmarking stops here. Physical VM cutover and its phase observations are the coordinator's steps in
[rollout.md](rollout.md); this session has changed no VM or Worker secrets.

All earlier “not met by this run” statements below describe the original numerical threshold at measurement time.
They are historical evidence, superseded for acceptance by Daniel's decision above. The measured values are retained.

## Historical initial validation

Initial source implementation: `296e0160eda9918fb72d5cab5761061c2219cd6a`, base `98cf1db5de24857096abea886c0eefbd620d2e09`.
All commands below were run by hand, independently of the D-151 gate bypass. The checkout uses the pinned toolchain;
loopback suites run with network permission, a workspace rate-state path, and `PYTHONPATH` pointing to the checkout.

| Suite | Tests | Result |
|---|---:|---|
| service | 108 | pass |
| control-plane | 57 | pass |
| forge-events | 284 | 279 pass, 5 optional live-provider tests skipped |
| train | 151 | pass |
| train-role | 46 | pass |
| planner-role core file | 3 | pass |
| gate-fast | 8 | pass |
| gate-bypass | 9 | pass |
| gate-regime-lock | 13 | pass |
| battery | 32 | pass |
| train-reuse | 18 | pass |
| prepush | 32 | pass |
| config readers | 8 | pass |
| operation relations | 42 | pass |

Schema compatibility, generated drift and the structure check pass. Structure retains the existing exception regime's
literal warnings; this unit introduces no new bypass switch. The pre-push repeated literal check now honors the same
D-260 decision already honored by the local and structure checks.

## Timing

The real gate was explicitly run with `GATE_BYPASS=0`. On the implementation head, the pinned run reported these
container stage walls (parallel checks overlap):

| Stage | Seconds |
|---|---:|
| generated drift | 1.351 |
| workflow policy | 0.561 |
| PR metadata | 6.424 |
| schema compatibility | 5.844 |
| tree secret scan | 2.688 |
| history secret scan | 3.451 |
| structure | 12.664 |
| script stage | 96.529 |
| driver total | 126.065 |

That run's script stage was classified `env`: the default test-result store tried to write the read-only home. The
workspace overrides for gate runs are `GATE_CHECKOUT_ROOT`, `GATE_BUILD_CACHE_DIR`, `GATE_TEST_CACHE_DIR`,
`GATE_STAGE_CACHE_DIR`, and `OU_FORGE_RATE_STATE`. This does not excuse outcome (c): structure alone already exceeds
10 seconds, and no bypass or attested lookup is counted as the real gate running within the target.

The known planner-role stall was a fake rejected by the compatibility boundary before signaling its peer; the test
wait was coupled to a 900-second production lease. The fixture now explicitly separates role tests from adapter
compatibility tests and uses the job budget as its rendezvous bound. All three tests take 0.181 seconds by hand.
The accounting test also lacked a required train method on its counting double; the train-role suite now passes.

## Outcomes

- (a) Implemented: owner-checked release, process-group cleanup, generation-checked restart recovery, deadline lease;
  coordinator verification on the actual VM remains open.
- (b) Implemented: one bounded budget, outer elapsed-time alarm, bounded child and reporting reserve, explicit negative
  results. Claim, head-check, child, cleanup and report phases are retained. Actual VM timing remains open.
- (c) **Closed by owner decision, 2026-11-02 22:19 BRT**: Daniel accepts 10.523 s ordinary and approximately
  16.8 s cold. The ten-second VM target remains for a later unit; the runtime budget is unchanged.
- (d) Implemented: one queued deploy path, changed-tree check, secret-preserving upload, bounded retry and supersession;
  first bootstrap and proof of the next automatic deploy require the coordinator.
- (e) Implemented: consumer inventory, required environment file, named claim/result/heartbeat/journal auth failures;
  coordinator must provision/update all holders without printing values.
- (f) Implemented: terminal closed-PR barriers, explicit reopen, TTL and deadline expiry, owner-checked results, bounded
  deploy retries and stale runner retirement. Control-plane persistence and behavior are covered by the Node suite.

## Delivery boundary

Outcome (c) no longer blocks readiness: it is explicitly accepted by the owner. The remaining external action is
coordinator cutover of the VM/Worker, following [rollout.md](rollout.md). No bypass is used as timing evidence.

The brief also names `scripts/gate-wait`, which is absent on this base and branch. GATE-API audit F8 explicitly
records that client as retired. Its old parallel verdict-waiting path is not restored. The current gate command is
synchronous; readiness and merger remain the existing `pr-ready` event and train, once acceptance is actually met.

## Historical full real-gate failures on 6d7e31d0 — resolved

The full real gate ran with all workspace cache overrides and ended red (pinned driver 134.509 seconds; the whole
wrapper, including head-tooling advisory, 292.514 seconds). It exposed two metadata omissions in this PR: five
missing registry reader declarations and stale operation call-site/census data. Both were corrected; their hand-run
suites pass 8 and 42 tests respectively.

Other red full-gate suites: `defect-lifecycle`, `lessons`, `plan-tick`, `planner-role` concurrency tests and
`pr-creation-path`. They are not hidden by the successful targeted runs above. The compatibility/creation failures
were checked against the unchanged base `98cf1db5` in its pinned checkout; their individual results are recorded in
the diary. The planner core's 3 passing tests do not claim the entire planner-role script passes. Those failures were subsequently fixed in this PR, including the remote-ref race classification and catalog-derived
creation guard. No pre-existing failure family remains handed off. Daniel later closed performance acceptance.

## Published measurements — continuation

These runs use `GATE_BYPASS=0` and the implementation head as tooling (`OU_GATE_PINNED=off`);
no whole-gate verdict or attestation shortcut answers them. Per-test content proofs are reported explicitly.
The timestamps below are BRT (UTC−03:00). Cold script execution is separate from a fresh driver run.

### Cold full-script run with concurrent manual-suite contention — 2026-11-02T20:40:05-03:00

Source: `8fea03ba706a413737ada56b7a504969fc49c381`. Exit: 0. **Full driver total: 218.390 s**. All 145 script suites passed. This run rebuilt script evidence; contention makes it unsuitable as a standalone speed claim.

| Stage | Wall seconds / reuse |
|---|---:|
| no GitHub Actions workflows | 0.650s |
| generated drift | 2.030s |
| secret scan | tree) (4.050s |
| secret scan | history) (6.220s |
| pr metadata | 6.560s |
| schema compat | 12.290s |
| structure check | 30.010s |
| script tests | 201.450s |

Acceptance (c): not met by this run.

### Fresh tree/stage analysis with exact per-test reuse — 2026-11-02T20:44:41-03:00

Source: `f2a66c3fff98e0f826cb7b8491d76bb738da314f`. Exit: 0. **Full driver total: 21.394 s**. The 145 scripts were already validated by input key; structural analysis and deterministic stages were cold.

| Stage | Wall seconds / reuse |
|---|---:|
| no GitHub Actions workflows | 0.540s |
| generated drift | 1.020s |
| secret scan | tree) (1.890s |
| secret scan | history) (3.120s |
| pr metadata | 5.310s |
| script tests | 3.700s |
| schema compat | 6.060s |
| structure check | 13.100s |

Acceptance (c): not met by this run.

### Ordinary full gate with content-keyed reuse — 2026-11-02T20:45:09-03:00

Source: `f2a66c3fff98e0f826cb7b8491d76bb738da314f`. Exit: 0. **Full driver total: 15.344 s**. All 145 script suites reused exact input keys. Structure still recomputed because its raw diagnostics were not error-free.

| Stage | Wall seconds / reuse |
|---|---:|
| no GitHub Actions workflows | 0.190s |
| generated drift | cached: tier-1 result 97ad06a27311f5191505 |
| schema compat | cached: tier-1 result 0f0d1fdfeba9488da717 |
| secret scan | history) (2.470s |
| secret scan | tree) (2.680s |
| pr metadata | 3.540s |
| script tests | 2.180s |
| structure check | 11.430s |

Acceptance (c): not met by this run.

### Ordinary full gate with publication profiler — 2026-11-02T20:45:30-03:00

Source: `f2a66c3fff98e0f826cb7b8491d76bb738da314f`. Exit: 0. **Full driver total: 15.782 s**. Profiling adds overhead. Publication itself measured 1.314 s; this is diagnostic evidence, not acceptance.

| Stage | Wall seconds / reuse |
|---|---:|
| no GitHub Actions workflows | 0.530s |
| generated drift | cached: tier-1 result 97ad06a27311f5191505 |
| schema compat | cached: tier-1 result 0f0d1fdfeba9488da717 |
| secret scan | history) (1.910s |
| secret scan | tree) (2.450s |
| pr metadata | 3.470s |
| script tests | 2.280s |
| structure check | 11.830s |

Acceptance (c): not met by this run.

The hand-run full script builder on `8fea03ba706a413737ada56b7a504969fc49c381` judged 145 suites: 143 executed, two reused after actual isolated-root execution, zero failures, 229.09 s wall under concurrent gate contention. On `f2a66c3fff98e0f826cb7b8491d76bb738da314f`, all 145 exact-key results were judged in 0.88 s with zero failures. Neither builder number is a full-gate timing.

### definitive-source-analysis-cold — 2026-11-02T21:27:41-03:00

Source: `eb4fb75c6ab25bc2bc27bb913981f242bf689f98`. Exit: 0. **Full driver total: 22.508 s**.
Real ordinary gate: bypass disabled; implementation-head tooling; no whole-gate attestation or verdict reuse.

Script suites: 145 judged; 145 by exact content key; 0 executed; 0 failures.

| Stage | Wall seconds / reuse |
|---|---:|
| no GitHub Actions workflows | 0.470s |
| generated drift | 1.310s |
| secret scan | tree) (2.480s |
| secret scan | history) (3.300s |
| pr metadata | 5.910s |
| script tests | 3.890s |
| schema compat | 7.220s |
| structure check | 13.780s |

| Driver phase | Wall seconds |
|---|---:|
| prepare | 2.014 |
| stages | 14.092 |
| publish | 5.981 |
| startup before prepare | 0.220 |
| cleanup after answer | 0.201 |

This is a local container driver measurement, not a deployed VM job measurement. The enforced VM budget also covers claim, head-check, cleanup and result transport.

Acceptance (c): this run does not meet ten seconds.

### definitive-prose-reuse — 2026-11-02T21:28:23-03:00

Source: `ac3458e03283ab82096a5ca3f06cb029f5e07666`. Exit: 0. **Full driver total: 16.348 s**.
Real ordinary gate: bypass disabled; implementation-head tooling; no whole-gate attestation or verdict reuse.

| Stage | Wall seconds / reuse |
|---|---:|
| no GitHub Actions workflows | 0.400s |
| generated drift | 1.150s |
| secret scan | tree) (2.810s |
| secret scan | history) (3.990s |
| pr metadata | 4.810s |
| schema compat | 5.180s |
| structure check | 7.190s |

| Driver phase | Wall seconds |
|---|---:|
| prepare | 1.990 |
| stages | 7.502 |
| publish | 6.449 |
| startup before prepare | 0.231 |
| cleanup after answer | 0.176 |

This is a local container driver measurement, not a deployed VM job measurement. The enforced VM budget also covers claim, head-check, cleanup and result transport.

Acceptance (c): this run does not meet ten seconds.

### definitive-fresh-publication-profile — 2026-11-02T21:29:18-03:00

Source: `21413c2f0624a48770d0b0688dc0f5cdfcea699b`. Exit: 0. **Full driver total: 21.492 s**.
Real ordinary gate: bypass disabled; implementation-head tooling; no whole-gate attestation or verdict reuse.

| Stage | Wall seconds / reuse |
|---|---:|
| no GitHub Actions workflows | 0.400s |
| generated drift | 0.900s |
| secret scan | tree) (2.330s |
| secret scan | history) (3.190s |
| schema compat | 5.560s |
| pr metadata | 5.780s |
| structure check | 9.440s |

| Driver phase | Wall seconds |
|---|---:|
| prepare | 1.864 |
| stages | 9.753 |
| publish | 9.456 |
| startup before prepare | 0.238 |
| cleanup after answer | 0.181 |

This is a local container driver measurement, not a deployed VM job measurement. The enforced VM budget also covers claim, head-check, cleanup and result transport.

Acceptance (c): this run does not meet ten seconds.

### definitive-trigger-filter-cold — 2026-11-02T21:36:03-03:00

Source: `704371cd927d1e4c108507d3e393ff3bca2d7fa5`. Exit: 0. **Full driver total: 19.099 s**.
Real ordinary gate: bypass disabled; implementation-head tooling; no whole-gate attestation or verdict reuse.

Script suites: 145 judged; 145 by exact content key; 0 executed; 0 failures.

| Stage | Wall seconds / reuse |
|---|---:|
| no GitHub Actions workflows | 0.170s |
| generated drift | 1.160s |
| secret scan | tree) (2.320s |
| secret scan | history) (3.760s |
| pr metadata | 6.010s |
| script tests | 3.780s |
| schema compat | 7.300s |
| structure check | 14.060s |

| Driver phase | Wall seconds |
|---|---:|
| prepare | 1.915 |
| stages | 14.363 |
| publish | 2.428 |
| startup before prepare | 0.230 |
| cleanup after answer | 0.163 |

This is a local container driver measurement, not a deployed VM job measurement. The enforced VM budget also covers claim, head-check, cleanup and result transport.

Acceptance (c): this run does not meet ten seconds.

### definitive-trigger-filter-reuse — 2026-11-02T21:37:01-03:00

Source: `7d371be0713cf26fbe359bf5b6c928d86028686f`. Exit: 0. **Full driver total: 11.161 s**.
Real ordinary gate: bypass disabled; implementation-head tooling; no whole-gate attestation or verdict reuse.

| Stage | Wall seconds / reuse |
|---|---:|
| no GitHub Actions workflows | 0.380s |
| generated drift | 1.460s |
| secret scan | tree) (3.080s |
| secret scan | history) (3.280s |
| pr metadata | 4.180s |
| structure check | 5.100s |
| schema compat | 4.910s |

| Driver phase | Wall seconds |
|---|---:|
| prepare | 1.833 |
| stages | 6.577 |
| publish | 2.329 |
| startup before prepare | 0.217 |
| cleanup after answer | 0.205 |

This is a local container driver measurement, not a deployed VM job measurement. The enforced VM budget also covers claim, head-check, cleanup and result transport.

Acceptance (c): this run does not meet ten seconds.

### definitive-local-fold-cold — 2026-11-02T21:44:05-03:00

Source: `625db97493e1a7e0189fcb838e694c4acd73cd4a`. Exit: 0. **Full driver total: 16.790 s**.
Real ordinary gate: bypass disabled; implementation-head tooling; no whole-gate attestation or verdict reuse.

Script suites: 145 judged; 145 by exact content key; 0 executed; 0 failures.

| Stage | Wall seconds / reuse |
|---|---:|
| no GitHub Actions workflows | 0.220s |
| generated drift | 1.380s |
| secret scan | tree) (2.340s |
| secret scan | history) (3.210s |
| script tests | 2.810s |
| pr metadata | 5.790s |
| schema compat | 6.240s |
| structure check | 12.150s |

| Driver phase | Wall seconds |
|---|---:|
| prepare | 1.807 |
| stages | 12.440 |
| publish | 2.172 |
| startup before prepare | 0.204 |
| cleanup after answer | 0.167 |

This is a local container driver measurement, not a deployed VM job measurement. The enforced VM budget also covers claim, head-check, cleanup and result transport.

Acceptance (c): this run does not meet ten seconds.

### definitive-local-fold-reuse — 2026-11-02T21:44:57-03:00

Source: `944bd84a14301bad9af7cdaafa2f2ad89d0d7a08`. Exit: 0. **Full driver total: 12.292 s**.
Real ordinary gate: bypass disabled; implementation-head tooling; no whole-gate attestation or verdict reuse.

| Stage | Wall seconds / reuse |
|---|---:|
| no GitHub Actions workflows | 0.380s |
| generated drift | 1.530s |
| secret scan | history) (3.470s |
| secret scan | tree) (3.840s |
| structure check | 6.000s |
| pr metadata | 4.940s |
| schema compat | 5.640s |

| Driver phase | Wall seconds |
|---|---:|
| prepare | 2.108 |
| stages | 7.511 |
| publish | 2.202 |
| startup before prepare | 0.234 |
| cleanup after answer | 0.237 |

This is a local container driver measurement, not a deployed VM job measurement. The enforced VM budget also covers claim, head-check, cleanup and result transport.

Acceptance (c): this run does not meet ten seconds.

### definitive-schema-and-prose-profile — 2026-11-02T21:46:13-03:00

Source: `b384e4c612ff0362c935172119f6883c72e2f670`. Exit: 0. **Full driver total: 12.498 s**.
CPU profiling enabled; diagnostic overhead is included, not acceptance evidence. Real ordinary gate: bypass disabled; implementation-head tooling; no whole-gate attestation or verdict reuse.

| Stage | Wall seconds / reuse |
|---|---:|
| no GitHub Actions workflows | 0.420s |
| generated drift | 0.820s |
| secret scan | tree) (3.050s |
| secret scan | history) (3.150s |
| pr metadata | 5.170s |
| structure check | 7.140s |
| schema compat | 6.030s |

| Driver phase | Wall seconds |
|---|---:|
| prepare | 1.972 |
| stages | 7.643 |
| publish | 2.480 |
| startup before prepare | 0.227 |
| cleanup after answer | 0.176 |

This is a local container driver measurement, not a deployed VM job measurement. The enforced VM budget also covers claim, head-check, cleanup and result transport.

Acceptance (c): this run does not meet ten seconds.

## Timing qualification — full stage selection

Inspection of the ordinary reports on `944bd84a14301bad9af7cdaafa2f2ad89d0d7a08` (12.292 s) and the
preceding timing-only heads shows `carry: ... script tests`: the normal delta plan carried that stage from
the preceding full successful gate. Those ordinary totals are real, but are not evidence that the complete
stage set and all 145 content keys were judged inside ten seconds. Earlier wording about no whole-verdict
lookup does not exclude this separate stage-carry mechanism; it must not be read as an acceptance claim.

Acceptance measurements from here explicitly use `GATE_BYPASS=0 OU_GATE_COLD=1 OU_GATE_PINNED=off`.
`OU_GATE_COLD=1` disables carry and forces the complete PR selection. The repository's D-076 cold definition
still permits exact content-key test/stage results; it does not mean an empty proof cache. Raw execution of
the scripts is reported separately and remains above ten seconds. No cold run with an empty proof cache
is claimed to meet the target. A clarification was pending at measurement time. Daniel subsequently accepted the measured performance and
closed outcome (c) at 22:19 BRT; that decision supersedes the pending performance-definition question.

### definitive-complete-selection-source-cold — 2026-11-02T21:53:04-03:00

Source: `c8aa93c3d0166c1b40e0e89ff080e0779128dd68`. Exit: 0. **Full driver total: 16.770 s**.
Real ordinary gate: bypass disabled; implementation-head tooling; no whole-gate attestation or verdict reuse.

Flags: `GATE_BYPASS=0`, `OU_GATE_COLD=1`, `OU_GATE_PINNED=off`.

Script suites: 145 judged; 145 by exact content key; 0 executed; 0 failures.

| Stage | Wall seconds / reuse |
|---|---:|
| no GitHub Actions workflows | 0.470s |
| generated drift | 1.370s |
| secret scan | tree) (3.500s |
| secret scan | history) (4.310s |
| schema compat | 3.650s |
| pr metadata | 5.240s |
| script tests | 3.070s |
| structure check | 12.280s |

| Driver phase | Wall seconds |
|---|---:|
| prepare | 1.915 |
| stages | 12.621 |
| publish | 1.786 |
| startup before prepare | 0.264 |
| cleanup after answer | 0.184 |

This is a local container driver measurement, not a deployed VM job measurement. The enforced VM budget also covers claim, head-check, cleanup and result transport.

Acceptance (c): this run does not meet ten seconds.

### definitive-complete-selection-content-reuse — 2026-11-02T21:53:41-03:00

Source: `4f4e24350df9618d2d58ab962965656732b0ab58`. Exit: 0. **Full driver total: 10.818 s**.
Real ordinary gate: bypass disabled; implementation-head tooling; no whole-gate attestation or verdict reuse.

Flags: `GATE_BYPASS=0`, `OU_GATE_COLD=1`, `OU_GATE_PINNED=off`.

Script suites: 145 judged; 145 by exact content key; 0 executed; 0 failures.

| Stage | Wall seconds / reuse |
|---|---:|
| no GitHub Actions workflows | 0.380s |
| generated drift | 1.300s |
| secret scan | tree) (3.560s |
| secret scan | history) (3.960s |
| schema compat | 3.380s |
| structure check | 4.890s |
| script tests | 2.770s |
| pr metadata | 4.860s |

| Driver phase | Wall seconds |
|---|---:|
| prepare | 2.251 |
| stages | 6.193 |
| publish | 1.949 |
| startup before prepare | 0.242 |
| cleanup after answer | 0.183 |

This is a local container driver measurement, not a deployed VM job measurement. The enforced VM budget also covers claim, head-check, cleanup and result transport.

Acceptance (c): this run does not meet ten seconds.

### definitive-independent-keys-source-cold — 2026-11-02T22:10:54-03:00

Source: `12f35e978bf015b3ccb2d844f7f00f183b92af56`. Exit: 0. **Full driver total: 16.935 s**.
Real ordinary gate: bypass disabled; implementation-head tooling; no whole-gate attestation or verdict reuse.

Flags: `GATE_BYPASS=0`, `OU_GATE_COLD=1`, `OU_GATE_PINNED=off`.

Script suites: 145 judged; 145 by exact content key; 0 executed; 0 failures.

| Stage | Wall seconds / reuse |
|---|---:|
| no GitHub Actions workflows | 1.010s |
| generated drift | 1.310s |
| secret scan | tree) (4.090s |
| schema compat | 4.000s |
| secret scan | history) (5.300s |
| script tests | 3.480s |
| pr metadata | 6.570s |
| structure check | 12.680s |

| Driver phase | Wall seconds |
|---|---:|
| prepare | 1.770 |
| stages | 13.042 |
| publish | 1.677 |
| startup before prepare | 0.275 |
| cleanup after answer | 0.171 |

This is a local container driver measurement, not a deployed VM job measurement. The enforced VM budget also covers claim, head-check, cleanup and result transport.

Acceptance (c): this run does not meet ten seconds.

### definitive-d076-cold-fresh-build — 2026-11-02T22:12:14-03:00

Source: `ea020515d91cf2aa0ba9f2b2c65fd072db452424`. Exit: 0. **Full driver total: 10.523 s**.
Real ordinary gate: bypass disabled; implementation-head tooling; no whole-gate attestation or verdict reuse.

Flags: `GATE_BYPASS=0`, `OU_GATE_COLD=1`, `OU_GATE_PINNED=off`.

Script suites: 145 judged; 145 by exact content key; 0 executed; 0 failures.

| Stage | Wall seconds / reuse |
|---|---:|
| no GitHub Actions workflows | 0.590s |
| generated drift | 1.700s |
| secret scan | tree) (3.780s |
| schema compat | 4.260s |
| secret scan | history) (5.320s |
| structure check | 5.480s |
| pr metadata | 5.970s |
| script tests | 4.200s |

| Driver phase | Wall seconds |
|---|---:|
| prepare | 1.996 |
| stages | 6.660 |
| publish | 1.368 |
| startup before prepare | 0.326 |
| cleanup after answer | 0.173 |

This is a local container driver measurement, not a deployed VM job measurement. The enforced VM budget also covers claim, head-check, cleanup and result transport.

Acceptance (c): this run does not meet ten seconds.
