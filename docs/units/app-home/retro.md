# U4 app-home retro

## 1. Brief quality
- Wrong for this unit: "Move the unit's files into units/app-home/" and "delete the old paths". S1 (P-03) records that units stay logical and `src/app` must stay for Next routes; the brief itself says "in the physical form S1 recorded", which resolved it, but the rest of the text reads as a physical move. A per-unit line "form: logical" would have saved the reading.
- Missing: how the bare address works (`contract.entry`) and that the entry must be git-tracked before `unit-battery` sees it.
- Branch name in the brief (`mod/u4-app-home`) differed from the session's designated branch; the designated one was used.

## 2. Audit and plan
- Held: P-03 (no file moves), size under the ceiling (748/1500), no literal sites for these files.
- Surprise, in the audit: the unit had nothing to migrate for literals or text. Production files spell no copy; only fixture pages carry words. The plan turned "move text" into "lock zero visible text with the scope list".
- Plan changed: no. Commits 1-5 went as planned; one lint fix commit was added to step 3.

## 3. Execution
| Time (BRT) | Step |
|---|---|
| audit commit | docs only, 59487b3f |
| plan commit | 152b4c5e, PR #603 opened as draft |
| contract + test | f6322990 |
| text scope | 41a450aa |
| generated | 8d4eaadd |
| lint fix | 83e1620c |
- Failure 1 (class: lint rule not run before pushing): `@typescript-eslint/no-non-null-assertion` in the new test (4 sites). Same pattern searched in the unit: none elsewhere. Fixed in one commit.
- Failure 2 (not mine, base): `scripts/tests/generate.test.sh`, `apps/web/scripts/intents-doc.ts` cannot resolve `@ou/kernel-tables` under bare node (`release/domain/intents.ts` imports by address). Reproduced on a throwaway worktree of the base; owner is the release-domain/U1 area.
- Dead end: none. Wait time was the gate (6 to 10 min wall each).

## 4. Gate
| Run | Wall | Result |
|---|---|---|
| 1 | 578 s | lint red (my test), generate.test.sh red (base) |
| 2 | 311 s | generate.test.sh red, e2e smoke missing (stage skipped after the script-test failure) |
| 3 (after merging the moved base) | 626 s | PASSED, generate.test.sh listed as a known base defect |
Ceiling warning (D-064 f, 180 s) printed each time; not this PR's.

## 5. Lessons
- A new test file must be linted before the push: add `eslint <changed files>` to the unit battery's step list for TypeScript units (owner: engine-battery).
- `contract.entry` must be tracked before the battery runs: say so in `docs/architecture/UNITS.md` (owner: engine-units).
- The first gate run did not classify generate.test.sh as a base defect while the third did: the base re-run depends on the worktree state; make `defect_detect` print why it did not classify (owner: engine-defects).
- Briefs for logical units should state "no file moves" in the scope line (owner: engine-coordinator brief template).
- Residual: 7 test files of other units (`site`, `test/int`, `test/site`) still import app-home files by relative path (robots, sitemap, to-metadata, catalog-guard), so `unit.addressable` stays false; their owners rewrite them (never edited here).
