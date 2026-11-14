# GX-09 RETRO

Unit: `gate.passed|failed` v4 readers (plan-v2 §4). PR #723, branch `mod/gx09`, base `mod/roadmap-integration` d101b73c (0 behind throughout).

## 1. Brief quality

- Clear on ownership and fences (train.py, contracts, producer); the plan-v2 row and E11 made the train-queue case unambiguous.
- Ambiguous: the harness named a different branch (`claude/gx09-*`) than the brief (`mod/gx09`); the brief won (named PR head). The registry entry `gate-contracts.gate_passed_version` says "GX-09 sets 4", contradicting plan-v2 (producer switch is GX-10). Left at 3; recorded in the STATUS comment.
- Missing: the brief did not say that GX-38 had pre-claimed `scripts/tests/test_gate_v4_readers.py` in `units/engine-gate-report/unit.json`, nor that the LT1 literal census scans tests. Both cost a corrective commit.
- The brief's acceptance "one shared accepted-versions source" was the real design content; the audit found the readers were already version-agnostic (type-only selection after `ForgeEvents.read` validates), so the risk was implicit acceptance, not breakage.

## 2. Audit and plan

- Premises held: P-42 (GX-09 only reads the binding), P-34 (all reads through the port), "readers accept every locked version" (`event_contracts.py:5`) became the helper's rule.
- Plan unchanged in shape (5 items); commit 4 needed a second commit (structure correction, below). No sub-agents: commit 4 imports commit 3 (real edge), each step under 15 minutes.

## 3. Execution (UTC, commit times)

| Time | Commit | Note |
|---|---|---|
| 00:25 | 8af69597 audit skeleton | draft PR #723 opened, STATUS posted within ~2 min of launch |
| 00:27 | 8efa404a audit | readers table with file:line |
| 00:27 | d8a2c36c plan | |
| 00:29 | 98a63cac `gate_verdicts.py` + readers | plan-tick 19, slo 27, push-guard OK |
| 00:30 | e7d776a3 test_gate_v4_readers | 8 tests OK; mutation (accept only v3) → 7 failures + 1 error |
| 00:33 | 24867ed3 test belongs to its pre-claimed unit, no literals | see failures |

Failures, each with its class:
1. `structure-check`: test file claimed by two units (engine-commit-plan, engine-gate-report). Class: a new file's owner was assumed instead of looked up (`rg <path> units/`). The pre-claim existed (GX-38).
2. `structure-check`: 12 LT1 unregistered-number findings in the new test (SHAs `'x' * 40`, versions 3/4, durations, `parents[2]`). Class: test fixtures written with numeric literals; fixed by deriving versions from the contracts (`version_with`), SHAs and stage time from the plan-tick fixture, durations via `timedelta(minutes=1)` and registry values. Searched the rest of the diff: no other new literal.
Both escaped the pre-push `structure_fast` local check (it does not run the literal census or the unit-overlap check); found by running `scripts/structure-check --pr-body` before the gate, so the gate never saw them.

## 4. Gate

- One pinned run on 24867ed3: tooling pinned to d101b73c, PASSED; 7 stages PASS; script tests 84/84 PASS (full battery: CODEOWNERS is a full-battery class), 0 cached, no known defect adjudicated (none of KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3 hit); total 136.3 s (ceiling 180 s). Advisory head-tooling run PASSED (43.2 s). gate.passed 8b4361946805 recorded; pr.ready withheld (item 5 open) as designed.
- A second pinned run on the RETRO head (docs only) gives the MERGE-READY verdict.

## 5. Lessons

| Problem | Change that prevents it | Owner |
|---|---|---|
| Duplicate unit claim of a pre-claimed path | brief template: list pre-claimed paths of the unit (from GX-38) next to "Files"; or `structure_fast` runs the unit-overlap check (it is cheap) | brief author (A Torre); `local-checks.json` owner (engine-commit-plan) |
| LT1 literals in a new test discovered late | add the literal census of changed files to `local-checks.json` (budget allows: census of a few files is ms); brief template note "tests are scanned by LT1: derive values" | engine-commit-plan / structure owner |
| Registry description promising a step to the wrong unit ("GX-09 sets 4") | descriptions name the plan step, not a unit id that a later plan can move; fix the text when GX-10 flips it | GX-10 (gate-contracts entry) |
| Readers selecting by literal type with implicit version acceptance | `gate_verdicts` is now the one source; `forge_events.apply`/`gate_slow` and `train.queue_entry` still select by literal type (not GX-09's files) | GX-20 / GX-30 may adopt `gate_verdicts.TYPES` |
