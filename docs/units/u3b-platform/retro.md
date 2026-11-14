# U3b platform: retro

Whole unit, from the brief to the accepted gate. Facts with evidence; timeline from the branch commits.

## 1. Brief quality
- Missing: the brief named the branch `mod/u3b-platform-addresses`, but the harness's designated branch is
  `claude/u3b-platform-addresses-2pmkl1`. The push rule allows only the designated one, so the work went there. Cause:
  two instructions in one brief. Lesson: the launcher should name one branch.
- Ambiguous: "rewrite every import that crosses a unit boundary" did not say what to do with Node-run files. The
  decision came from evidence (the Node-run closure), not from the brief. Lesson: the U3b brief should name the
  Node-run constraint (`apps/web/package.json` `node scripts/*.ts`, `next.config.ts`) explicitly.
- Wrong: the brief's examples assume every importer can use `@ou/*`. For this lane 147 of 196 specifiers cannot, so
  the expected count (all cross-unit imports) was wrong for this lane.

## 2. Audit and plan
- Premise P-03 (addresses are generated and resolve) held: all 50 candidate specifiers validated with
  `unit_addresses.resolve` before any edit.
- Premise P-13 (no address reaches into another unit's file) held: `unit_addresses.check` clean after every commit.
- Node-run closure premise: my audit used only the 27 `node scripts/*.ts` entries, not `next.config.ts`. This was
  wrong and cost commit 6 (see section 3). The plan was changed in the PR body, not in plan.md.

## 3. Execution, failures and root causes
| time (UTC, 27 Oct) | commit | event |
|---|---|---|
| 06:2x | `b336abc9` | audit document (pushed, green) |
| 06:2x | `eeb071d3` | plan document (pushed, green) |
| 06:3x | PR #593 opened as draft | |
| 06:3x | `4598a43c` | db-contexts (31 specifiers; battery green) |
| 06:4x | `2f2be176` | db-catalog-io/-store (6; batteries green) |
| 06:4x | `701e3c12` | db-media (7; battery green) |
| 06:4x | `f62fe76b` | db-operations (1; battery green) |
| 06:4x | `a957702a` | platform-runtime (5 specifiers): **battery red** (`types`), pushed by mistake |
| 06:5x | `dc356457` | corrective: `host/vercel.ts` restored to its relative import; battery green |
| 06:5x | `1fa3eab1` | merge of base `c0e748c8` (engine-wrappers U4), no conflicts |

**Failure 1 (root cause class: incomplete closure of Node-run entries).** `host/vercel.ts` is loaded by
`apps/web/next.config.ts` through Next's config transpile (a Node `require`), which does not read tsconfig paths.
The `types` stage failed with `MODULE_NOT_FOUND`. My audit closure used only the 27 package.json script entries. The
class fix is to add every config file Node loads (here `next.config.ts`) to the closure, and to run the unit battery
before each push. The corrective commit reverts only that file's one specifier. Closure recomputed: 336 files, 57 lane
files; no other changed file was affected (checked by intersecting the branch diff with the closure).

**Failure 2 (process failure, my chain).** My push chain used `unit-battery ... | tail -1` and `set -e`. A pipe hides
the battery's exit status, so the red battery did not stop the push. Class fix for this lane: run each battery without a
pipe and test `$?`. Owner of the shared chain: me (this session). Recorded here; I did not add a gate check for it.

**Failure 3 (small).** One accidental re-run of `apply.py` on already-rewritten files. It was a no-op (`git status`
clean). Cause: the script is not idempotent-guarded. Not fixed; the script was never committed.

**Known miscount.** The plan estimated 16 db-contexts specifiers; the real count was 31 (the audit counted per
unit, the plan counted by hand). Corrected in the PR body. Cause: the plan counts were typed by hand.

**Base merge carries `Plan: 7`.** Merge `1fa3eab1` has a `Plan: 7` trailer (copied from the chain template), which
would tick the retro item early. Pushed, so not rewritten.

## 4. Gate
- Run 1 on `1fa3eab1`: PASS, exit 0, wall 443.5 s. Stages: structure check 60.0 s, unit tests 134.8 s (1763 tests in
  266 files), lint 163.0 s, integration 169.6 s (651 tests in 44 files), typecheck 22.8 s, build test and production
  ~21 s each, e2e browsers 25.1 s (40 passed), performance 47.8 s (20 tests), smoke DB 2.8 s.
- The D-064 (f) ceiling warning (443 s > 180 s) is a warning, not a failure. Its owner is the gate performance stage (H0).
- No known base defect was hit (the timing-sensitive tests passed on this run).

## 5. Lessons (concrete change, and owner)
1. Unit closure must include every Node-run entry, not only package.json scripts. Change: the unit battery's
   Node-entry list (`units` tooling, owner U0/U3a) should derive from `next.config.*`, `drizzle.config.*` and
   `package.json` scripts together. Owner: U3a/U0 (units tooling).
2. Batteries must not run behind a pipe in any chain. Change: brief template for U3b: "run `scripts/unit-battery <id>`
   and check `$?`". Owner: launcher / lane brief template.
3. One branch name per brief. Change: the brief template states the designated branch once. Owner: launcher.
4. Counts in the plan come from the audit scan, not by hand. Change: the audit tool prints the per-unit count and the
   plan template links to it. Owner: U3a addresses tool.
5. Plan commit trailers: a merge commit must not carry `Plan: N`. Change: the trailer template excludes merges.
   Owner: commit-check (K1 / structure owner).
6. Node-run constraint (146 then 147 specifiers) needs a resolver on the Node path. Change: a tooling item to add an
   `@ou/*` resolver for Node (tsx or a loader hook). Owner: tooling-db / engine-config owner (not this lane).
