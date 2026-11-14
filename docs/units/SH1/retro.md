# SH-1 retro

## 1. Brief quality
- Wrong: `apps/web/tsconfig.json` is not a generated aggregate on base; `apps/web/tsconfig.paths.json` is (target `addresses`). Handled by deriving the generated set from `generate.targets`.
- Missing: the brief did not say the new contract must be locked (`contracts/events/schemas.lock.json`) nor that `lock` is outside the file allow-list; both are consequences of the own change.
- Conflict: harness branch `claude/sh1-...` vs brief `mod/sh1`; the brief won, recorded in the first STATUS.

## 2. Audit and plan
- Held: manifests are read at a commit by `UnitOwnership.manifests`; per-member files come from `workspace.changed_files(base, sha)`.
- Broke: plan numbering. The PR body plan listed 7 items while commits are cut as 5 deliveries plus the retro; `pr metadata` refused until the body matched the `Plan: N` trailers.

## 3. Execution (timeline, commits)
- 12:45 skeleton, 12:47 audit+plan, 12:50 registry+contract, 12:55 key module, 12:57 train.py call.
- Failures and class: (a) push guard: `x-readers` named a file that did not exist yet (ordering of commits: a registry key's reader must exist in the same commit; fixed with a stub module); (b) `unit_check`: new production file needs a unit claim (own dependency, added in the same commit); (c) event-contracts test: new contract not locked (found by the pre-push test, fixed in the next commit); (d) literal census: PR numbers 2 and 3 in tests (LT1; fixed with fixture ids, class fixed for every occurrence at once).
- Dead end: none; no time lost beyond the amend cycles above.

## 4. Gate
- Run 1 on c151c66a: unit tests 1790 passed (280 files), script tests passed, only `pr metadata` failed (class code: plan items 6, 7 not ticked), 273.6 s against the 180 s ceiling (script tests 163 s, unit tests 111 s; report-only). No KD hit.

## 5. Lessons
- A brief that adds a registry key with `x-readers` should say "land the reader file in the same commit"; owner: brief template (A Torre).
- A new event contract needs `scripts/lib/event_contracts.py lock` and `scripts/generate`; add both to the brief template's "own dependencies" list; owner: engine-events.
- `plan-tick` could print the expected item list from the trailers when the body differs; owner: engine-commit-plan.
