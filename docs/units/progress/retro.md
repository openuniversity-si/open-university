# U3b progress: retro

PR #590, branch `mod/u3b-progress-addresses`, base `mod/roadmap-integration` at `a2c09043`. Facts with evidence; no filler.

## 1. Brief quality

- **Missing:** the brief named the unit's files only by lane ("progress") and did not say how to treat imports into units
  with no owner (`scripts/units owner` prints `-`). I decided: list them as contract gaps and do not edit them (the brief's
  own rule for targets that are not exported, applied to targets that have no unit at all).
- **Ambiguous:** "run each touched unit's `scripts/unit-battery <id>`" and "gate tier 1 is your unit's battery" vs. the
  explicit "GATE IN THIS SESSION: gate-dev" are two gates. I ran both; the merge condition is gate-dev green on the head.
- **Wrong:** the brief's commit-plan rule (3-8 commits, each with `Plan: N`) collided with the audit commit, which I
  pushed with `Plan: 0` before the checklist existed. It cannot be amended (pushed history), so it stays.
- **Premise text:** the brief's "Premises: P-03, P-13" line is accepted; the register entries exist.

## 2. Audit and plan

- Premise P-03 (addresses are stable) held: every rewritable target's unit has an address, and the `tsconfig.json` paths
  carry `@ou/<id>/*` wildcards for them. tsc passed after each code commit.
- Premise P-13 (mechanical rewrite keeps behaviour) held: the progress unit battery and the 27 unit tests are identical
  before and after (census measured by stashing the change: 5 files, 27 tests).
- **Audit error, corrected in commit 4:** the first audit counted 21 cross-unit imports and 3 gaps. `progress-contract.ts`
  has a second gap import (`uow-contract.ts`). Corrected count: 22 imports, 18 rewritable, 4 gaps. The plan changed only in
  the gap list.
- Lessons query (`scripts/lessons for-area apps/web/src/progress`): none applied.

## 3. Execution (timeline, pushed commits)

| Order | Event |
|---|---|
| 1 | Branch created from `origin/mod/roadmap-integration` (`a2c09043`). A `tsc` run and the progress battery were started in parallel; the battery reported 12.2 s over its 10 s limit under that load. |
| 2 | Sequential `tsc --noEmit` at base: exit 0, no output. Battery re-run alone: green in 7.05 s. |
| 3 | Audit pushed (`e857ab76`), then plan (`c7f2c610`). Draft PR #590 opened. |
| 4 | Commit 3, kernel imports (`f1391d0c`): tsc 0, 27 tests green. |
| 5 | Commit 4, platform/identity/db imports with the audit correction (`0ff82d39`): tsc 0, 27 tests green. |
| 6 | Commit 5, handler (`9aa3546a`), and commit 6, handler test (`0745ab74`): tsc 0, 27 tests green. |
| 7 | `scripts/unit-battery progress`: green in 7.05 s. `scripts/units check`: 104 manifests, 0 errors. |
| 8 | Gate run 1 on `0745ab74`: PASS, 530 s wall. |

Failures in execution: none in the code. Rework: the audit count (see section 2). Waits: the gate (530 s). Dead ends: none.
The first `tsc` run in parallel with the battery printed no output and exit 1; the same command run alone exited 0.
Cause not identified; not reproduced.

## 4. Gate

- Run 1 on `0745ab74`: PASS every stage (see the PR comment for the table). Wall time 530 s; the D-064 (f) ceiling is 180 s,
  so the gate printed a warning (not a failure). Largest stages: integration tests 203 s, lint 167 s, unit tests 131 s.
- Known base defects hit: none in this unit.
- The retro commit changes the head, so gate-dev is run again on the retro head before merge (merge needs a pass on the exact head).

## 5. Lessons and the rule each one would change

1. **Count imports with a command, not by reading.** The first audit missed one gap import in a second file. Change: the
   audit template for U3b runs `rg -n '"\.\./\.\./'` (or the `scripts/units addresses` importers list) and records its
   output, not a hand count. Owner: the U3b brief template (A Torre, lane owners).
2. **Do not run tsc and the unit battery in parallel when the battery has a time limit.** The 10 s limit was exceeded only
   under parallel load. Change: the battery brief says run it alone. Owner: U3a (`scripts/unit-battery`) — a note in its
   help, not a new limit; the threshold stays as registered.
3. **Name the gate for the merge explicitly.** The brief gave two gates. Change: the brief names one merge gate and one
   unit gate. Owner: the brief template.
4. **Gate ceiling.** 530 s on a 4 vCPU cloud for a mechanical change is far above the 180 s ceiling (D-064 (f)). Not a
   failure, but it spends quota on every PR. Owner: the engine performance/gate owner (M7/O1 line of work); no threshold is
   loosened here.
5. **Gap imports have no owner.** Four imports point at files no unit owns. Proposal: the units check reports unowned files
   that a unit imports. Owner: U4 (units) and the platform/testing owners.
6. **Missing `requires` edges.** `progress` imports `db-core` and `catalog-application` without declaring them in
   `requires`. Proposal: `scripts/units check` should flag an import whose target unit is not in `requires` (not verified
   whether it does today). Owner: U0 (`scripts/lib/unit_check.py`) with the progress lane for the manifest edit.
