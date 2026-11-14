# TX22 retro: literal baselines derived from the base census

PR #745, branch mod/tx-literals, lane engine-lane, base 891b835ae. Brief: TX-PROGRAM (Daniel 28/10 00:57/00:58), plan
revision 2. Size M, about 86 min.

## Delivered

- `scripts/lib/literal_census.py`: `check(root, base)` computes the allowed counts from the census of the merge-base of
  `base` (else `literals.base_ref` = `origin/mod/roadmap-integration`); paths unchanged since the merge-base reuse the
  current census, the others are read in one `git cat-file --batch`. Per unit, kind and value, the rule is the same.
  Errors name every grown `file:line` (file order) and the registry fix. No base ref: one exact error, fail closed.
- The committed engine list (`scripts/lib/absolute-literals-baseline/engine/`, 32 files, 2829 entries, 2327 test
  literals) is no longer read or written (`write`/`--write` gone); it stays, equal to the census, with
  `literals.baseline` and `literals.baseline_description` deprecated, until this PR is the base (expand step); the
  contract step deletes them (plan.md).
- Runtime on this checkout: 1.24-1.29 s (was 1.23 s with the list).

## Brief quality

Good: exact files, the CRITICAL premise as fixtures, the runtime bound, and the pending-PR line. One premise of the
evidence was broader than this unit: the overlap counts (`scripts.json` by 7 PRs, `app.json` by 4, `catalog/platform/ui`
trios) are the **apps/web D-063 list** at the top of the same folder, written by the TypeScript census of
`tooling-literals` (tooling-lane), not by `literal_census.py`. One lane per PR keeps it out of this unit.

## Premises

- Held (CRITICAL): the same fixtures fail before and after (new literal in a new file, a file that gains one, a value
  moved to another unit), and a move inside one unit passes; measured on the real repo in throwaway worktrees.
- Held: `git diff --no-renames --name-only <merge-base>` names every changed scanned path (renames would hide the old
  path: `--no-renames` is required, covered by `test_lt1_a_renamed_file_keeps_its_literals`).
- Held: fixture checkouts without the literals registry stay unjudged (structure-check.test.sh green).
- Broken (scope): "the baselines" of the evidence include the apps/web list; recorded in audit.md.

## Failures and root-cause class

1. `literals.test.sh` red on the first run of the new tests: the derived check found `2` spelled twice in
   `test_literal_census_derived.py` (code: the old tests relied on their committed list entry). Fixed by composing the
   source instead of a count. The check proved itself on its own tests.
2. Evidence run: lines listed in AST order (`engine_role.py:218, :83`). Class code (breadth-first walk). Fixed with a test.
3. Pinned gate run 1 (head 4f5f2212): `schema compat` red, `literals.baseline` and `literals.baseline_description`
   "removed without a revision that marked it deprecated" (D-068 (3), expand then contract). Class code: this PR
   removed two registry keys in one step. Fixed by marking both deprecated (readers: plan.md); a later revision removes
   them. No other key of this PR was removed (searched the diff of `config/registry/`). The fast checks before each
   push do not run `scripts/schema-compat`; it should be one of them.

## Gate runs

1. Pinned gate-dev on 4f5f2212 (offline file config store, as the brief sanctions): FAILED at schema compat (above);
   every other stage passed; 383 s total, 350 s of it script tests (over the 180 s ceiling, report-only).
2. Pinned gate-dev on af251d4e: FAILED at structure check, 1247 errors from the **base's** `literal_census.py` (the
   pinned tooling): with `literals.baseline` present again (deprecated) it read the deleted list. In run 1 the key was
   absent, so the base check skipped itself (ConfigError) and only schema compat was red. Class **contract**: the pinned
   base tooling (P-46) and D-068 (3) cannot both accept a one-step removal of a gate check's data. Decided: expand then
   contract (plan.md); the list is restored equal to the census, unread by the new code.
3. Pinned gate-dev on 8f2e7224 (expand head, base f1af963d merged in): PASSED, 157.5 s; `pr.ready #745 head=8f2e7224
   lane=engine-lane`.
4. Pinned gate-dev on the head that corrects this retro: the MERGE-READY comment.

## Lessons

- A census check should never need a committed copy of its own output: derive it from the base (T2). Owner: every
  inventory check; next candidate is the apps/web D-063 list (tooling-literals, tooling-lane), the same change in
  `apps/web/scripts/lib/absolute-literals.ts` + `structure.py` `check_absolute_baseline`.
- Add `scripts/schema-compat --base origin/mod/roadmap-integration` to the fast checks before a push that touches
  `config/registry/` (owner: TX01 `scripts/prepush`, PR #742).
- A change to the data contract of a check the pinned gate runs (a list, a registry key it reads) is always two PRs:
  expand (new code ignores the old data, data kept valid for the base tooling, keys deprecated), then contract. Briefs
  that ask to delete such data in one PR should say so. Owner: the TX program planner; candidate rule for
  `docs/process/STRUCTURE.md`.
- A brief's overlap evidence should name the writer of each file (`scripts/units owner`), so a unit is not sized on
  files of another lane. Owner: the TX program planner.
