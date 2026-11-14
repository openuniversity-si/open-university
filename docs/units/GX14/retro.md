# GX-14 retro

PR #702, branch `mod/gx14`, base `mod/roadmap-integration` (4bc4dd04 at start, 60392c0c after GX-42 #703 merged). Times are UTC on 27/10. This file is committed before the final verdict run, so the final numbers are in the PR's RETRO and MERGE-READY comments.

## 1. Brief quality
- Accurate: every cited line existed (`commit_check.py:142,160`, `structure.py:522-534`). The "≈20 calls" estimate matched: the base code costs 20 calls on the same fake with 13 live commits (19 with 12).
- Missing: the brief did not say how the gated sha reaches `structure-check`. `gate-local` (GX-38's file) passes only `--pr`; the answer is that the gate runs structure-check inside its detached checkout of the gated sha (`gate-local:194-195,315`), so that checkout's HEAD is the gated sha. A one-line pointer would have saved the search.
- Missing: the brief did not say that the LT1 literal census judges test files too and that only 0, 1 and -1 are free, while the baseline is frozen for every unit except GX-38/GX-39. This affects every T0 unit that adds a test.
- Ambiguous: the brief named branch `mod/gx14` while the session harness named `claude/gx14-…`. I followed the brief (as GX-01 did).
- Ambiguous: "comments older than the gated head's push": I decided that a comment at the same second counts, and that a comment with no time, or a gated sha with no known push, is judged as before (fail-closed).

## 2. Audit and plan
- Premises held: P-02 (pushes, comments and compare still come from GitHub; only file names and the commit list of the gated sha come from local git, which holds that same sha). P-46: the verdict is about the gate's checkout.
- Plan change: commit 5 also changed `commit_check.fetch` (a `head=` argument). Reason: a hand run of `structure-check --pr N` from an unrelated checkout must not judge that checkout's HEAD. So fetch takes HEAD only when it is on the PR commits page. The file set is the same as the plan's.
- No sub-agents: the steps were sequential (3 and 4 share `commit_check.py`, and 5 needs 4's signature). Each one was a single small file set.

## 3. Execution
| UTC | Step |
|---|---|
| 18:23 | audit (Plan 1) pushed, draft PR #702 |
| 18:24 | plan (Plan 2); comments judged up to the gated push (Plan 3) |
| 18:26 | fetch on the gated sha, REST cut (Plan 4) |
| 18:30 | structure-check passes the gated sha + LT1 class fix (Plan 5); base 60392c0c merged |

Failures:
1. A test boundary error in my own test (15:05:00 ≤ cutoff 15:05:00). Class: test expectation, not code. It was fixed before commit.
2. **Incident (not green on its own): commits 3 and 4 were pushed with new number literals** (`[:7]`, `split(.., 2)`, `[:3]` in code, and 12/13/5/6/7/40 in tests). The LT1 census refuses these in the structure check. Root cause: the pre-push local checks (`no_registered_literals`, `structure_fast`) do not run `literal_census`, so I found it only when I ran `structure-check.test.sh` at commit 5. Class fix in commit 5: no new number literal anywhere in the diff. Steps, calls and the PR number are named (`STEPS`, `CALLS`, PR 1). Strings use `partition`. The census equals the list again, and the baseline is untouched.
3. The first verdict run aborted in 3 s with `FAIL env: missing toolchain: …`: a fresh `git worktree` of the base tip has no `.toolchain/` (gitignored). The remedy was to symlink the checkout's pinned `.toolchain` into the worktree. This was not a code failure.

## 4. Gate
See the PR's RETRO comment for the verdict runs (base-tip tooling) and the own-checkout run (report-only), with numbers.

## 5. Lessons
| Problem | Change that prevents it | Owner |
|---|---|---|
| The census found number literals only after a push | Add `literal_census.check` restricted to the pushed diff's files to `config/registry/local-checks.json`. It is AST-only and fast enough for the 5 s budget. | engine-structure (GX-15/GX-21 slot) |
| A base-tip worktree has no toolchain | Document `ln -s <checkout>/.toolchain <worktree>/.toolchain` in the D-A3 protocol, or make `gate-local` resolve the toolchain from the main worktree (`git rev-parse --git-common-dir`). | GX-05 (pinned gate) |
| The brief did not say how the gated sha reaches a stage | For every stage that reads the forge, the brief template names how the stage learns the gated sha | program brief template (A Torre) |
| `github_api.issue_comments` drops `created_at` | Add a timed variant in `github_api` and retire `commit_check.timed_comments` | owner of `github_api.py` |
