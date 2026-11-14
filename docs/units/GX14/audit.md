# GX-14 audit (read-only, base `mod/roadmap-integration` at `4bc4dd04`)

Brief: GX-14 "Structure metadata judged on the gated sha, REST cut" (plan §3.3, plan-v2 wave A / T0, D-070). Every cited source was checked on the base; each exists (`commit_check.py:142,160`, `structure.py:522-534`, `decision_wait.py`, both test files, D-070 in `docs/domain/DECISIONS.md:72`, P-02 and P-46 in `docs/process/premises/`).

## Findings

| # | Where (base) | Finding |
|---|---|---|
| A1 | `scripts/lib/commit_check.py:160` | `compare/<base>...{pull["head"]["sha"]}` reads the **live** head. The gate checks out a fixed sha (`gate-local:172-195`, `root="$wt"`) and runs `structure-check --pr N` in that checkout (`gate-local:315`); a push during the gate makes the rebase verdict judge a commit the gate never tested. |
| A2 | `scripts/lib/commit_check.py:143-149` | One `commits/<sha>` call per PR commit only to read its file names; the commits page itself also lists live-head commits. A 12-commit PR costs 12 calls here. |
| A3 | `scripts/lib/commit_check.py:150-155` | `pulls/N/files` (live head, paged) is read again although the gated checkout has the files locally. |
| A4 | `scripts/lib/commit_check.py:162`, `github_api.py:122-137` | `issue_comments` returns bodies only, so `decision_wait` judges every comment, including ones posted after the gated head was pushed: a comment during the gate flips the verdict (F-15, #607). `github_api.rest` returns full items (with `created_at`); `github_api.py` is outside this unit, so the timed read lives in `commit_check`. |
| A5 | REST count, 12-commit PR, base | pull 1 + commits page 1 + 12 commit details + files 1 + push activity 1 + force-push activity 1 + compare 1 + comments 1 = **19** (≈20 in the brief). |
| A6 | `scripts/lib/structure.py:522-534` | `structure-check --pr` calls `commit_check.fetch(args.pr)` with no sha; the checkout's HEAD (the gated sha) is never passed. `structure.py:543-545` also feeds the fetched commit messages to `threshold_check`. |
| A7 | `scripts/lib/stall_report.py:57` | `decision_wait.waiting(bodies)` is also used by stall-report (live view, not a verdict). Its signature stays; the cut-off is applied before the call. |
| A8 | `scripts/lib/premises.py`, `local_checks.py`, `threshold_check.py` | Import `commit_check` but never call `fetch`; their use is unchanged. |
| A9 | GitHub activity API | Each push item carries `after` and `timestamp`: the gated head's push time is the `timestamp` of the push whose `after` is the gated sha (no extra call). |

## Tests that cover the diff (`scripts/lib/gate-script-tests.json`)
`commit-check.test.sh` (`test_commit_check.py`; covers `commit_check.py`, `decision_wait.py`) and `structure-check.test.sh` (`test_structure.py`; covers `structure.py`, `commit_check.py`). No new test file is needed; no `covers` line changes.

## Known defects / collisions
Base env failures (not this unit, GX-ENV): `claude-session.test.sh`, `root-identity.test.sh`, `config.test.sh` (`RegistryMemo.test_a_rewritten_file_is_read_again`). Running concurrently: GX-22 takes `commit_check.py` after this unit, GX-15 takes `structure.py`; nobody else edits these files now. GX-16's REST counter is not merged: the count uses a fake transport.

## Branch
The harness named `claude/gx14-structure-metadata-rest-z9hp84`; the brief names `mod/gx14` (brief standard v2 rule 1, one unit one branch, as GX-01 did). Decision: `mod/gx14`.
