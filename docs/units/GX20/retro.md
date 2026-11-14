# GX-20 retro — carry-over by delta (the RETRO case)

PR #739, branch `mod/gx20`, base `mod/roadmap-integration` a698f542 at launch, 9fa02090 after the catch-up merge. Times UTC (BRT = UTC−3).

## 1. Brief
- **Wrong key names.** The brief fixes `gate.carry_over_enabled` / `gate.carry_over_areas` in a new `config/registry/gate-carry.json`. `config.check` (`scripts/lib/config.py:510-514`) refuses a key that does not start with its file owner, and `gate.json` belonged to the running GX-16. Decided: `gate-carry.carry_over_enabled` / `gate-carry.carry_over_areas` (audit §7). Lesson: a brief that names a registry key must name it as `<file owner>.<key>`; the brief template (A Torre) should derive the key from the file it names.
- **Unreachable acceptance item.** "carries every other stage with `carried_from {…}`" needs the proof builder to read the run, but `gate_proof.py` (and `gate_report.py`) were closed to GX-20, and neither had a seam reading anything from the run except the stage records. The GX-39 stub `gate_carry.carried(logs)` was never called by anyone. Delivered: `gate_carry.fields(logs)` and `carry.json`. The one-line seam `payload.update(gate_carry.fields(logs))` in `gate_proof.proof_payload` is still owed by the owner of that file. Lesson: a seam stub must ship together with its call site (GX-39 pattern). A stub nobody calls is not a seam (owner: the program planner, plan §5 seams).
- **"Fixture PR … `pr.ready` fires on it" cannot be done under the pinned gate before merge.** The verdict of record runs base-tip tooling, which has no carry. The advisory head-tooling run publishes no events, and its `gate_version` (the head `scripts/` tree) differs from the pinned proof's. So the first real carry can only happen on a PR gated after GX-20 merges. That is the "done means running" step the coordinator activates after the merge (§6).
- Clear and useful: the D-B6/D-B7 rows, the file fences, the known-defect list.

## 2. Audit and plan
- Premises: P-42 (GA-P01) held. The structure check is launched before the plan hook (`gate-local:362-369`), so no carry can skip it, and D-B6 needed no code. P-43 held: the carry reads only forge events, never `.pass` markers. GA-P10 is implemented as "every unknown is a normal gate" and tested.
- **Broken plan assumption:** `gate_carry.py` was listed in `units/engine-gate-report`. Importing it from `gate_policy` (engine-gate-plan) created a plan→report dependency, which is a cycle because report already requires plan. The structure check caught it. Fix: move `gate_carry.py`, its registry and its tests to `engine-gate-plan`, and read `OU_GATE_PROOF` directly instead of importing `gate_proof`. With that done, `pr_ready.py` (commit-plan) could reuse `gate_carry.delta`/`is_ancestor`, so the sub-agent's duplicated git calls were removed before commit 5. Lesson: GX-39 put the carry stub in the report unit while its only caller is the plan. A stub's unit should be the unit of its first caller (owner: GX-26/units).
- Plan unchanged otherwise: 6 items. Item 5 ran in a sub-agent beside item 4.

## 3. Execution (commit times UTC)
| Time | Commit | Plan |
|---|---|---|
| 03:20 | b5330101 audit skeleton, draft PR #739 opened via REST (no rate limit), STATUS posted | 1 |
| 03:23 | 8bf1389c audit | 1 |
| 03:23 | 15f25a56 plan | 2 |
| 03:27 | 0c85d935 registry + gate_carry decision + 17 tests | 3 |
| 03:31 | 2fa76d98 plan hook + classification of delta(H0, head) + 5 classification tests | 4 |
| 03:31 | be07fe67 pr_ready carried-proof rule + 4 tests | 5 |
| 03:36 | 2cccf955 merge of base 9fa02090 (32 commits; conflicts in `units/engine-gate-report/unit.json` and `scripts/tests/gate-local.test.sh`) | — |

Failures, each with its root-cause class:
1. Literal census (structure check): 12 bare numbers in the new module and test (`[:12]`, `indent=2`, `'f' * 40`, `parents[2]`). Class: engine code may not contain bare numbers (LT1). All of them were fixed in one pass by deriving the values (`len(sha)`, full shas, `.parent` chains). No baseline was written, since writing one would be a loosening.
2. Unit cycle (structure check): described in §2.
3. `gate-local.test.sh` asserts every unowned hook is a no-op, so filling `plan.sh` meant changing that test. GX-11 had changed the same line for `tier`, which caused the merge conflict. Resolved to `for h in prereq`.
4. `scripts/run test gate-areas` fails on the base too, because `scripts/tests/gate-areas.test.sh` is not executable (mode 644 on a698f542). It was run with `bash`. Not fixed here (GX-18's file): an env/structure lesson for GX-26.

No dead ends. The time went to reading `gate-local` and the proof builder (~10 min) and to the two structure findings (~8 min).

## 4. Gate
- Run 1 (pinned, head be07fe67, tooling a698f542): **PASSED**, 7/7 stages, no known defects hit; `gate.passed` 037a16b8 published; pr.ready not emitted (item 6 unticked, expected). Total 193.6 s, of which the `script tests` stage took 151.5 s. That is over the 180 s ceiling, which is report-only (D-064 f). The advisory head-tooling run: FAILED structure check only because the base had moved 32 commits (rebase rule). Its plan hook printed `carry: normal gate (no passed v4 dev proof on an earlier head of this PR)`, which is correct: the only proof was on the same head.
- Final run: on the RETRO head after the base merge. Its numbers and KD ids are in the MERGE-READY comment of PR #739.
- Measured stage time of the carried RETRO plan, from run 1's stage times plus local runs of the selected tests: always-stages 22.7 s summed (structure check 12.5 s, the longest), plus `lessons` 2.3 s and `coordinator` 1.5 s. Total ≈ 26.5 s of stage time (≤ 30 s), against 193.6 s for a full re-gate. A delta touching `docs/process/EVENTS.md` selects exactly `event-contracts.test.sh` (0.8 s), tested in `test_gate_carry.Classify`.

## 5. Lessons
| Problem | Change that prevents it | Owner |
|---|---|---|
| Brief names a registry key the registry refuses | Brief template derives keys from the owning file name (`<owner>.<key>`) | A Torre (brief template) |
| Seam stub with no call site; proof field unreachable | A seam unit ships the stub and its call site; `gate_proof.proof_payload` adds `gate_carry.fields(logs)` | GX-28 / proof-builder owner (next unit on `gate_proof.py`) |
| Stub placed in the wrong unit, causing a cycle | A stub lives in the unit of its first caller; `structure-check` already catches the cycle | GX-26 |
| `gate-areas.test.sh` not executable | `local-checks`: a `scripts/tests/*.test.sh` without the x bit is refused | GX-26 / local-checks owner |
| The carry cannot be proven before merge under the pin | First real run after merge: a RETRO-only commit on any PR gated by tooling ≥ GX-20's merge must print `carry: delta plan` and publish a verdict with carried stages | coordinator, right after the merge |
