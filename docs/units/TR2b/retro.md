# TR2b retro: lane_id in pr.ready (PR #691)

## 1. Brief quality
- Clear scope, cause and fences; the TR2 audit (F2/F3) pinned the exact line. Good.
- Missing: that `pr_ready` (unit `engine-commit-plan`) importing the train modules (unit `engine-train`) needs a declared `requires`. Found by the local structure-check, not the gate.
- Conflict: the brief standard says branch `mod/<unit>`; the session harness pins `claude/pr-ready-lane-id-psxbof`. Kept the harness branch (one branch, one PR).
- Conflict: "first commit within 5 minutes" vs "audit.md and plan.md are commits 1 and 2". Chose the deadline; audit/plan landed as commits 3 and 4.

## 2. Audit and plan
- Premises held: manifests in the base (A3), contract already allows a string lane (A4), every value registered (A5). P-13 (one lane per unit) unchanged.
- Plan change: item 2 (unit `requires`) added before the PR opened, from the structure-check FAIL.

## 3. Execution (UTC)
| Time | Commit | Step |
|---|---|---|
| 13:46 | — | start, read pr_ready/train_ownership/units |
| 13:49 | 16fc6448 | derivation + 5 targeted tests (18 tests OK, test_train OK) |
| ~13:55 | — | PR #691 opened (draft) |
| 13:58 | adc41253 | `engine-train` in `engine-commit-plan` requires |
| 13:58 | 343f539b | audit.md |
| 13:59 | 51bce93f | plan.md |
| 13:59–14:03 | — | gate-dev |
- One failure class: undeclared cross-unit import (U2). Fixed in one commit; no other occurrence (only `pr_ready.py` changed imports).
- No sub-agents: the change was three files and one dependency chain; spawning would have cost more than it saved.
- Design: the lane rule is one method (`UnitOwnership.lane_of`) next to `refusals()`, so the producer and the train share it. Manifests read at the merge base so a head cannot pick its own lane.

## 4. Gate
- 1 run on 51bce93f: PASSED, 234 s (over the 180 s ceiling, warning only: script tests 121 s, structure check 82 s). No known defect hit.
- Re-run on the retro head (docs only) for the exact-head pass.

## 5. Lessons
| Problem | Change | Owner |
|---|---|---|
| Cross-unit import discovered after the first push | Brief template: when a fix imports another unit's module, name the `requires` line to add; or have `commit-check --local` run the U2 import check (already in structure-check, ~1 s via structure_fast misses it). | engine-structure / brief author |
| Branch-name and first-commit rules contradict the harness/deadline | Brief standard v2: "the harness-designated branch wins"; allow audit/plan after a deadline-bound first commit. | padrao (PD2) |
| Retro commit forces a second gate run | Let docs-only `docs/units/**` commits after a pass reuse it, or write the retro before the gate and amend with gate numbers in the comment. | gate owner (needs a D-NNN) |
