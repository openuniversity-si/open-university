# GX-11 retro

Unit: the gate tier is explicit (derived, D-B5) and every cache and the KD1 switch key on it; D-065 (5) made true. PR #733, branch `claude/gx11-tier-explicit-4nhdog`, base fbc09f28 (did not move during the unit).

## 1. Brief quality
- Clear on ownership, fences and the D-B5 rule. Missing or wrong:
  - It names the key `gate.cacheable_tiers` living in `gate-tier.json`. The registry requires the file's namespace (`x-owner`), so the key is `gate-tier.cacheable_tiers` (D-B8 "only the namespace changes").
  - It says "move `tier1_gate_modes`' x-readers". But the closed `gate_report.py` still reads that key and passes it in. The key can't leave or lose that reader until GX-26, so it stays registered (deprecated) as the fallback the brief itself asked for (GX-13's reads).
  - It names `mod/gx11`, while the harness requires the session's designated branch. I followed the GX-39 precedent: still one branch.
  - It doesn't mention how the tier reaches the Python stages without editing `gate-local`. An environment variable was the only channel, and an environment variable leaks (section 3).
  - `scripts/run test gate-result-cache` (an acceptance line) can't run: the file isn't executable. Reported as a CANDIDATE.
  - The container had no toolchain (the SessionStart setup had not run). Gate run 1 aborted at preflight.

## 2. Audit and plan
- Premises held: P-43 (no box-local reuse at tiers 2 and 3); the seams of GX-38/GX-39 removed every collision (no edit to gate-local, gate_report, gate_result_cache, gate_proof or gate_adjudicate was needed).
- Plan changes:
  - D-B5 became four registry keys (`gate-tier.battery`, `per_pr`, `batch`, `working_tree`) read by `gate_tier.derive`. The literal census refuses bare tier numbers and its baseline only shrinks per area. The registry has no object type except for text, so a table key was refused too.
  - A sixth code change (the binding, see section 3) was added under Plan 4.
- Decisions recorded on the PR:
  - working tree → tier 1;
  - the result cache keeps its dev-only mode set on top of the tier (no mode gains a cache);
  - noite derives tier 1 (CANDIDATE).

## 3. Execution (container clock, 28/10)
| Time | Commit | Note |
|---|---|---|
| 01:50 | 58375cb6 | audit skeleton; draft PR #733 + STATUS |
| 01:53 | e9540e9a | audit |
| 01:54 | 0b6a4c2e | plan |
| 01:55 | f7d7c353 | gate_tier + registry. **Pushed with 4 structure errors** (number literals 2/3) |
| 02:11 | 88459adb | tier hook; the census fix rode along. The registry now holds the D-B5 keys |
| 02:14 | cff14729 | per-test cache guard, `key_parts`, child-env clear |
| 02:23 | 1ddb90c6 | OU_GATE_TIER bound to its tooling (class fix of the leak) |

Failures and their root-cause classes:
1. **Literal census after push (f7d7c353).** `scripts/commit-check --local` reported 0 refusals, but its `structure_fast` doesn't run the absolute-literal census; only `scripts/structure-check` does. Class: the local pre-push check is weaker than the gate's structure stage. Afterwards I ran `scripts/structure-check` before every push.
2. **Session stall, about 10 min.** A stray `cat >> /dev/null` in a compound shell command read stdin forever. Own error, no code impact.
3. **Env leak (gate run 2, class code).** The new hook exported `OU_GATE_TIER=1` in the invoker. The pinned base tooling (pre-GX-11) doesn't clear it, so the head's tests of the mode fallback (`defect-detect`, `forge-events`) saw an explicit tier. Clearing the variable for children inside `gate_test_cache.run` only protects runs whose tooling already has GX-11. Class fix: the value names the tooling that derived it (`<tier>@<scripts/lib>`), and any other checkout ignores it, whatever runs it. I reproduced the failure on the old code and verified the fix with the variable unbound, bound to another checkout, and unset.
4. **Toolchain absent.** Bootstrap `scripts/cloud/setup.sh` took about 7 min (documented path, not a workaround).

Sub-agents were not used: the work was about 6 small, serial edits on files that depend on each other through `gate_tier`. Spawning would have cost more context than it saved (stated in plan.md).

## 4. Gate (pinned `scripts/gate-dev --pr 733`, tooling fbc09f28)
| Run | Head | Result |
|---|---|---|
| 1 | cff14729 | aborted at preflight (`FAIL env: missing toolchain: python … postgres`, `GATE-CLASS: gate preflight env`) |
| 2 | cff14729 | FAILED, class code: 2 script tests (failure 3 above); script tests 147.7 s, total 189.9 s (over the 180 s ceiling, report-only). Advisory head-tooling run PASSED in 29.3 s, since the head tooling clears the variable for children |
| 3 | 1ddb90c6 | **PASSED**: 7/7 stages; 86 selected script tests, 83 cached, 0 failed; total 80.9 s; no known defect adjudicated; advisory PASSED 27.8 s |

The retro commit (docs-only) was re-gated before MERGE-READY.

## 5. Lessons (change, owner)
- `commit-check --local` should run the absolute-literal census (it takes about 33 ms in `no_registered_literals`, but that check covers only *registered* literals). Add the census to `config/registry/local-checks.json` so a pre-push catches what the gate's structure stage refuses. Owner: GX-15 (local_checks).
- A value one gate process hands to the next through the environment must say who it belongs to. `OU_GATE_BASE_SHA` (GX-38 proof hook) has the same exposure: it is exported in the invoker and inherited by the pinned tooling and by the code under test. Owner: GX-10/GX-28 (proof). Brief template: "seam values passed by env are bound to their producer".
- The brief template should name the registry namespace rule (`<file>.<key>`) and that objects are only allowed for text keys. Owner: the planner (brief template).
- A gate-change unit's own pinned verdict runs the head's hooks with the base's stages. Briefs for hook owners should say that this mixed state is what the verdict of record tests. Owner: the planner.
- `scripts/run test` should accept non-executable tests, or a check should refuse them (CANDIDATE posted). Owner: GX-26 or an env unit.
- Noite passes `--pr` only for comments and so derives tier 1 (CANDIDATE posted). Owner: whoever owns `gate_noite.py`.

## Acceptance evidence
- Observable: the real stage command (`gate_test_cache.py run`) on 5 real script tests, one warm store, in this container:
  - tier 1, second run: 0 ran, 5 cached;
  - tier 2: 5 ran, `cached: []`;
  - tier 3: 5 ran, `cached: []`;
  - the store kept its 5 markers (nothing written at tier 2/3);
  - tier 1 again: hits.
  - Unit test `TierTest.test_a_tier_2_run_on_a_warm_store_runs_every_test_and_records_nothing`.
- The verdict `tier` comes from the derived tier (`gate_tier.current`, `Current` tests). KD1 keys on `forge-events.adjudicated_tiers` (`Adjudicated.test_the_kd1_switch_keys_on_the_tier_not_the_mode`). The old key still works without a tier (`test_without_a_tier_the_modes_passed_in_still_decide`).
- Rollback `gate-tier.cacheable_tiers=[1,2]` is documented as D-NNN-only in its registry description; `[1]` restores per-PR-only adjudication via `forge-events.adjudicated_tiers`.
