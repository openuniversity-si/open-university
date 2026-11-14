# U3b identity: retro

Whole unit, from the launch brief to the accepted gate. Facts with evidence.

## 1. Brief quality

- **Branch name conflict.** The brief said work branch `mod/u3b-identity-addresses`; the harness said develop on
  `claude/u3b-identity-addresses-wvxbes`. I used the harness branch (the one the session may push to) and did not
  create the brief's branch. Lesson for the brief template: one branch name, the one the session can push.
- **Stale wave state.** The brief's "wave state" and "update" paragraphs listed parallel sessions as in flight; the
  base had already merged most of them (U3a, U2, U1, K1, T1, LR1, CO1). I checked `git log origin/mod/roadmap-integration`
  and built on what was merged, as the queue rules say. Lesson: the brief should say "U3a merged at <sha>" instead of
  a list that ages.
- **Unit tool format.** The brief named `scripts/units addresses` without saying it is a shell wrapper with
  `--json` (I first ran it through `python3`, which failed). Lesson: the brief should give the exact invocation of
  each tool it names.
- **Unowned files were not anticipated.** The brief assumed every target is addressable. Three identity files import
  `platform/db/testing/*`, which no unit owns, so they have no `@ou` address. The brief has no rule for an unowned
  import target. Lesson: U0's ownership check should flag unowned files that other units import (owner: U0/U4).
- **Node-run exception not anticipated.** `domain/intents.ts` is loaded by `pnpm intents:generate` under plain Node.
  The U3b precedent (commit `3c0ffb84`) covers it, but the brief did not mention it. Lesson: the brief template should
  name the Node-run files of the unit (owner: the U3b brief author; mechanism: a registry list of Node-run paths,
  owner: engine-units).

## 2. Audit and plan

- **Premises held.** P-03 (stable addresses) and P-13 (exclusive ownership): every target file has exactly one owner,
  the unit the import names (`scripts/units owner`), and the generated map resolves each address to the same file
  (type-check and tests green after each commit).
- **Premise that changed the plan.** The audit found the Node-run exception. The plan was written with it already
  (plan.md, "Known base defects" and the commit graph), so no replan was needed.
- **Plan change.** None after commit 2. Commit 4 was sized by the audit's count (12 sites), but the three unowned
  `platform/db/testing` lines were found only when grepping leftovers after commit 4; they were left relative and
  listed in the PR body, not rewritten. Recorded as a deliberate exception, not a plan change.

## 3. Execution (timeline)

Times are from the session; each commit is one push.

| Step | What | Result |
|---|---|---|
| launch | branch check, `origin/mod/roadmap-integration` at `a2c09043` | U3a merged |
| audit | `scripts/units addresses --json`, ownership of 16 target files, battery and vitest baseline | 31 sites, 0 contract gaps, 1 Node exception |
| commit 1 | audit.md pushed (`a9dc334c`) | ok |
| draft PR | #583 opened as draft (REST tool) | ok |
| commit 2 | plan.md pushed (`d84c64ad`) | ok |
| commit 3 | kernel rewrite, 17 lines (`37925f70`) | battery ok, 75/75 |
| commit 4 | platform/db/site rewrite, 12 lines (`494e72a8`) | battery ok, 75/75; leftover grep found 3 unowned lines |
| arch check | `node scripts/check-architecture.mjs` | 0 violations |
| gate-dev run 1 | on `494e72a8` | see section 4 |

Failures and rework: none in the code. One process slip: my first `scripts/units` call used `python3`; corrected at
once, no rework of files.

Waits: the background gate wrapper reported completion while the gate itself was still running; the status file
gets its `exit` line only when the gate exits. The Monitor was armed on that line.

## 4. Gate

Filled after the final gate run (see the PR comment with the stage table).

## 5. Lessons and owners

| Problem | Change that would have prevented it | Owner |
|---|---|---|
| Brief named a branch the harness did not allow | brief template: one branch, the pushable one | brief author |
| Stale parallel-session list in the brief | brief cites merged shas, not "in flight" lists | brief author |
| Unowned import target without a rule | U0 ownership check reports unowned files imported by a unit | U0 / U4 owner |
| Node-run file imported through `@ou` would fail | a registry list of Node-run paths the rewrite must skip; the check fails the rewrite if one is added | engine-units |
| `scripts/units` invoked as Python | the brief gives each tool's exact command | brief author |
