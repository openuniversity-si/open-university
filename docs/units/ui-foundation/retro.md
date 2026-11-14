# U4 ui-foundation retro

## 1. Brief quality
- Wrong for this unit: "move the files into units/ui-foundation/" and "delete the old paths". S1 (P-03) keeps units logical, and `globals.css` imports the stylesheets from `src/ui`. Same reading as app-home.
- Missing: the contract entry must be git-tracked before `unit-battery` sees it.

## 2. Audit and plan
- Held: P-03, size under the ceiling, no literal sites, no visible text.
- Plan changed: no.

## 3. Execution
- Failure 1 (class: wrong working directory for the background gate, so it never ran and the base was not merged): the first gate run found the branch 12 commits behind (`rebase` check). Fixed by merging the base from the repo root and re-gating. The `countries.test.ts` and `generate.test.sh` (`intents-doc.ts`) reds are outside this unit's files; the re-gate on the merged base decides whether they remain.

## 4. Gate
See the PR comment for the stage table.
