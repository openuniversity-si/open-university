# LT1 retro: unregistered literals refused, tests included, shrink-only list

PR #604. Brief: enforcement audit 26/10 rule 1 "no literals", fix R3. Gate run 1 on `92fa5bd8`: PASS (729 s), with one
registered known base defect.

## 1. Brief quality
- **Branch name conflicted with the session.** The brief named `mod/motor-lt1-unregistered-literals`, but the session
  may push only to `claude/lt1-unregistered-literals-9s45wa`. Resolved by using the designated branch (PR comment).
- **"Exceptions in a registry entry" didn't fit the registry types.** A registry `object` is reserved for locale text
  (`contracts/config/registry.v1.json`: `type: object` requires `x-text`). The pattern map became an ordered array of
  `{kind, pattern}`. The brief could have said "array".
- **Missing: the literal scan's scope is shared.** `config.literal_check_excludes` / `engine_files` is also the vendor
  check's scope (R1). Putting tests into the literal scan silently widened the vendor check (dozens of refusals in
  test doubles). The brief listed `config_check` and the registry entry, not their other reader.
- **Missing: the production guard (D-054) refuses any new line naming an entrypoint.** A path-keyed list of all of
  `scripts/` therefore cannot name 6 frozen files. The brief's "never loosen any allowlist" ruled out the easy fix.
- **Item 4 (docs that call the registry a `parameters` list) had no occurrence on this base.** Probably already fixed
  upstream; recorded with evidence in audit.md.

## 2. Audit and plan
- Held: the D-063 census ignores a subfolder of `scripts/lib/absolute-literals-baseline/` (the D-063/D-064 tests stay
  green). Turning tests on costs the registered-name rule nothing (0 findings).
- Broke: "the census fits in `config_check`". The structure check showed engine-config at 1,494 of its 1,500-line
  ceiling (1,690 with the census), plus an import cycle (`config_check` → `structure`/`units`, which already require
  engine-config). The plan changed: new unit `engine-literals` (`scripts/lib/literal_census.py`), plan.md updated in
  commit 3.
- Broke: "every scanned file can be listed". The production guard forced the derived exclusion
  (`production_guard.mentions`; 6 files, 121 literals), reported in the decisions comment.

## 3. Execution (times UTC, 2026-10-27)
| Time | Commit | Note |
|---|---|---|
| 06:49 | b812207f audit | prototype census measured: 3,010 offenders, 213 files |
| 06:50 | 906c6f81 plan | draft PR #604 |
| 07:07 | 47b03132 census, unit engine-literals | rework: the first draft lived in `config_check`; moved after the size/cycle finding |
| 07:25 | 9ea27cf4 gate on, list written | red on the structure check (assets) and the production guard, found after the push |
| 07:35 | 581c6387 guard-derived exclusion + assets entry | fixes both |
| 07:37 | 3d297abe docs | drafted by a sub-agent in parallel with 4, then corrected for the module move |
| 07:37 | ca862105 merge of the base | 251 commits; clean |
| 07:40 | 92fa5bd8 list follows the base | 2,929 literals, 214 files |

Failures and root-cause classes:
1. **Registry shape (`object` needs `x-text`)**: a contract rule not in the brief. Found by the tests in 1 run.
2. **The `__main__` guard placed before the new test class**: the appended tests never ran when the file was executed
   directly (unittest discovery ran them). Class: appending to a test file after its `__main__` guard. Fixed by moving
   the guard; the new test file was written guard-last.
3. **Shared scope (vendor check)**: one registry value, two readers with different needs. Class: a value read by more
   than one check. Fixed by giving the vendor check its own entry with the unchanged value.
4. **Size ceiling and import cycle**: placement chosen before measuring the unit. Class: adding code to a unit without
   reading `scripts/units measure` first.
5. **Structure check run before staging (assets)**: the asset and guard checks read tracked files and diffs, and
   commit 4's list files were untracked when I ran the check, so it passed. Commit 4 went out red; 581c6387 fixed it.
   Class: validating before `git add`. The same cause explains why commit 3 was briefly missing its fixture asset
   entry.
6. **Production guard vs a path-keyed list**: an inherent conflict between two rules, settled by a derived exclusion.
   Not a bug.
7. **Fixture tests that wrote files without staging**: the census reads `git ls-files`. Fixed with a `stage()` helper
   used by every write path in the test.

Where the time went: about 15 min auditing, about 50 min building and reworking the census (the module move was the
largest rework), and 12 min for the single gate run.

## 4. Gate
- Run 1, head `92fa5bd8`: PASS, 728.6 s total (above the 180 s ceiling, D-064 f, as a warning). The full battery ran
  because CODEOWNERS changed. Stages: script tests 567.3 s, structure check 67.3 s, secret scan (history) 6.9 s,
  secret scan (tree) 3.1 s, schema compat 2.9 s, generated drift 0.5 s, no workflows 0.02 s.
- The one red test was `scripts/tests/generate.test.sh` (`test_aggregates` Intents). Bare `node` cannot resolve
  `@ou/kernel-tables`, imported by `apps/web/src/progress/domain/intents.ts`. It is the registered known defect
  **KD-024bbecb** (open, engine-lane / engine-generate), red on base `37703996` too (reproduced in a throwaway
  worktree of the base). KD1 classified it, so the verdict is PASS.
- No timing-sensitive catalog test was hit.

## 5. Lessons
| Problem | Change that prevents it | Owner |
|---|---|---|
| Structure check passed on untracked files (assets, production guard) | `commit-check --local` / pre-push runs `structure_fast` on the pushed tree; add the asset and production-guard sub-checks for added paths (both are cheap) | engine-commit-plan (local-checks registry) |
| A registry value read by two checks with different scopes | Brief template: "list every reader of each registry entry you change (`scripts/config describe <name>` shows x-readers)". Also, the vendor check had reused the literal value without being in its x-readers: make `config.check` refuse a reader of a value that the value's x-readers does not list | engine-config |
| Code placed in a unit without measuring it | Brief template: run `scripts/units measure` for the target unit in the audit step | coordinator brief template (CO1) |
| Test class appended after `if __name__ == '__main__'` | Lint rule: no top-level definitions after the `__main__` guard in `scripts/tests/*.py` | engine-test-support |
| Path-keyed data lists vs the production guard | When step 8 brings the frozen entrypoints into the release pipeline, list their literals (121 today) | release lane (step 8) |
| `@ou` addresses unresolvable by bare node (KD-024bbecb) | The intents renderer runs through the same loader as the app (tsx/aliases) | engine-generate (KD-024bbecb) |
