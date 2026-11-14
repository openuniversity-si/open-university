# FP1 retro (brief to accepted gate)

## 1. Brief quality
- Clear on the two rules and the remedy (`scripts/replay-branch`). Ambiguous on rule 2: "behind the base and contains no merge commit of the base" also matches a PR that is already merged (the base is then ahead of the head). Found by running the new rule against merged #576 over REST, before the gate.
- Branch name conflict: the brief named `mod/motor-fp1-force-push-refuse`; the cloud session is pinned to `claude/fp1-force-push-refuse-vlt37h`. Decided for the session branch and recorded it in a PR comment.
- The brief template still carries the old "tick the body by PATCH" line, while AGENTS.md says the tick comes from `Plan:` trailers (`scripts/plan-tick`). Followed both: trailers on every commit, and the body PATCHed to match `plan-tick`.

## 2. Audit and plan
- Premises held: `/activity?activity_type=force_push` and `compare/<base>...<head>` answer through the same REST client (checked live on #585: `behind_by 0`, merge base a2c09043, no force pushes). No new tunable was needed. The remote name is read from `push-guard.remote`, and `commit_check.py` was added to its `x-readers`.
- Plan change: one extra commit under item 4 (88f9f05a). It skips a head that is its own merge base (a merged PR). No other change. Sub-agents were not used: two functions and one handler did not justify the context cost, and the plan says so.

## 3. Execution (UTC 2026-10-27)
| Time | Commit | Note |
|---|---|---|
| 06:45 | b80fbf2c audit, 6d2a8c82 plan | PR #585 opened as a draft after the first push |
| 06:48 | fc1e2674 force-push rule | 11 tests green |
| 06:50 | 25dfa495 rebase rule | 13 tests green; live check on #585 clean |
| 06:52 | 88f9f05a merged-head exemption | Live check on #576 refused it; class: a predicate checked only against open-PR fixtures. Fix: a fixture for the merged case |
| 06:54 | 6a4be7b9 `no_history_rewrite` | 16 local-check tests green; the pre-push hook ran it on its own push |
| 06:56 | c724a5c2 docs, 68fe9e82 base merge (U4 #597) | Merge commit through the post-merge hook, one push |
No waits, no dead ends. Quota went mostly to reading `commit_check`, `local_checks` and `push_guard` and to one gate.

## 4. Gate
- Run 1 on 68fe9e82: PASSED in 433 s wall time. Stage times: script tests 305.3 s, structure check 57.6 s, secret scan history 5.7 s, tree 2.1 s, schema compat 2.0 s, generated drift 0.4 s, no workflows 0.02 s. Over the 180 s ceiling (D-064 f; a warning, not a failure).
- Known defect hit: `scripts/tests/generate.test.sh` (KD-024bbecb, `ERR_MODULE_NOT_FOUND` in `apps/web/scripts/intents-doc.ts`). Excused by the gate; not caused by this PR.
- Run 2 runs on the retro head (docs only), from the per-test cache.

## 5. Lessons
1. A rule that compares a PR with its base must also be tried on a merged PR. Change: the commit-check fixtures now carry a merged-head case. Lesson for future base-relative rules (owner engine-commit-plan): replay a new forge predicate against one open and one merged PR over REST before the first push.
2. The brief template and the cloud session can name different branches. Change to the launch brief template (owner: coordinator, CO1): name the work branch only once, taken from the session.
3. The brief template's "tick via PATCH" contradicts D-065 V4 trailers. Change to the brief template (owner: coordinator): drop the PATCH line and point to `scripts/plan-tick`.
