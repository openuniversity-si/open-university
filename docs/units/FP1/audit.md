# FP1 audit (read-only, 2026-10-27)

Brief: enforcement audit 26/10, rule 3 "merge commits only; no rebase, force-push or history rewrite", fix R2. Branch protection is unavailable on this plan (HTTP 403), so the server blocks nothing; the gate must.

## What exists (evidence)
- `scripts/lib/commit_check.py` (gate file, D-025). `fetch(number)` reads `/activity?ref=refs/heads/<head>&activity_type=push` and keeps only `before`, `after`, `timestamp`. `push_errors` judges only pushes whose `after` is one of the PR's commits, so a `force_push` activity (a separate `activity_type`) is never read and never refused. `check()` is called by `scripts/lib/structure.py --pr` (the gate's `structure check` stage) and by `scripts/commit-check --pr|--fixture`.
- `fetch` reads `pull['head']['ref']` but not the base; nothing compares the head with its base, so a rebased branch (new commits replayed on a newer base, no merge commit) passes, and so does a branch that never brought the moved base in.
- X1 (merged): `scripts/lib/push_guard.py` pushes each new first-parent commit alone and never force-pushes; `scripts/lib/replay_branch.py` (`scripts/replay-branch <pr>`) is the sanctioned remedy of a bad push history: a new branch, cherry-picks one push per commit, one `git merge <remote>/<base>`, supersedes the old PR. `push_errors` already names it.
- LR1 (merged): `scripts/commit-check --local` runs `config/registry/local-checks.json` checks from `.githooks/pre-push` (`scripts/lib/local_checks.py`, handlers take a `Context` with the pushed refs). `one_push_per_commit` counts commits; no check looks at whether the remote sha is an ancestor of the pushed sha, so a local `git push --force` after a rebase is not stopped before it leaves.
- Tests: `scripts/tests/test_commit_check.py` (fixture per refusal + one clean PR, no network) via `commit-check.test.sh`; `scripts/tests/test_local_checks.py`. `scripts/lib/gate-script-tests.json` maps `scripts/lib/commit_check.py` and `scripts/lib/local_checks.py` to them.
- Registry: `train.base_branch` names the integration branch; `push-guard.remote` the remote. No other value is needed: the rules read the PR's own base from the forge.
- `scripts/lessons for-area scripts/lib/commit_check.py scripts/commit-check`: no lesson applies.

## GitHub REST facts used
- `GET /repos/{repo}/activity?ref=...&activity_type=force_push` lists force pushes with `before`, `after`, `timestamp`, `actor`.
- `GET /repos/{repo}/compare/{base}...{head}` gives `behind_by` and `merge_base_commit.sha`. A branch that brought its base in with `git merge` has a PR commit whose non-first parent is that merge base.

## Gaps (scope)
1. `force_push` activity on the PR head ref is not refused.
2. A head behind its base with no merge commit of the base (a rebased or never-updated branch) is not refused.
3. (class fix, D-069 item 9) the pre-push local check does not stop a non-fast-forward push before it leaves the machine.

## Not in scope / not duplicated
The one-push-per-commit rule (D-022) and its remedy stay as X1/LR1 shipped them. No branch protection (403, a plan purchase is money: not ours).
