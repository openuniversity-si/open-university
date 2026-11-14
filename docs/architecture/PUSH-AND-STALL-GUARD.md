# Push and stall guard (X1)

D-022 says to push each commit as soon as it's done. commit-check refuses a PR when one push brought several of its commits (`scripts/lib/commit_check.py` › `push_errors`). Before X1, a session that hit that refusal stopped and waited for the owner, because the only fix was to rewrite pushed history. X1 fixes the class of problem: the batched push can no longer happen, the remedy is one command, and a stall shows up as an event. Every value it uses is in `config/registry/push-guard.json` (`scripts/config describe push-guard.<key>`).

## The hook

- `.githooks/post-commit` runs `scripts/lib/push_guard.py`. Git also runs this hook for cherry-pick, revert and the commit that concludes a conflicted merge. `.githooks/post-merge` runs it for the merge commit of a clean `git merge origin/<base>`.
- The guard pushes every unpushed first-parent commit of HEAD one at a time, oldest first, with `git push <remote> <sha>:refs/heads/<branch>`. When a push fails, the commit stays local and the next commit retries it, still one commit per push. You can also retry by hand with `python3 scripts/lib/push_guard.py push`. The guard never force-pushes, and a failure never fails the commit.
- The guard skips:
  - a detached HEAD;
  - the integration branch (`train.base_branch`) and `push-guard.protected_branches`;
  - every branch when `push-guard.enabled` is off;
  - a branch that does not track `<remote>/<branch>` itself, unless it matches `push-guard.work_branch_patterns`. A matching branch is then pushed to itself and gets that upstream. A branch that tracks the base it started from is never pushed to the base.
- `scripts/cloud/env.sh`, which setup.sh sources, sets `core.hooksPath` to `push-guard.hooks_path` when the checkout has none.
- Each push attempt is recorded as `engine.session.heartbeat`.
- To turn the hook off: `scripts/config set push-guard.enabled false` (audited and reversible), or `git config core.hooksPath <other>` in one checkout. D-022 still refuses a batched push when the hook is off.

## The remedy

`scripts/replay-branch <pr>` is what the D-022 refusal now names (`fix: scripts/replay-branch <N>`). It works as follows:

1. It builds `<head>-r<N>` from `<remote>/<base>` in a temporary worktree.
2. It cherry-picks (`-x`) the PR's own commits in order and pushes after each one. The old PR's base merges are not replayed. If the base moved, one `git merge <remote>/<base>` merge commit closes the replay.
3. It opens the replacement PR with the same title and body, plus `Supersedes #<old> ...`.
4. It comments on the old PR and closes it.

The command never rebases or force-pushes. Rerunning it resumes from the `-x` lines, so nothing is done twice. A conflict stops it and prints the steps to finish by hand.

## The stall signal

`scripts/stall-report [--emit]` prints the open PRs whose session stopped, as JSON (`pr, branch, reason, since, last_push, last_gate, last_gate_at, detail`). It computes this on demand from the forge, through the forge_events port; there is no loop and no cron. It lives beside the push guard, not in `scripts/units`, because a stall is about a session's branch, not about which unit owns a path. The reasons are:

- `no_push`: no push for `push-guard.stall_no_push_s`. A PR whose head passed the gate is excluded, because it is waiting on the merger, not on its session.
- `red_gate`: `gate.failed` with no push after it for `push-guard.stall_red_gate_s`.
- `owner_wait`: a comment waits on an owner decision (see below).

`--emit` records each stall as `engine.session.stalled`, at most once per (pr, reason, since). The gate's own verdicts (`gate.passed`, `gate.failed`) are the gate's sign of life; there is no second gate event.

## The decision-wait check

DECIDE, THEN REPORT (Daniel 2026-10-26 21:29). `scripts/lib/decision_wait.py` treats a comment line holding one of `push-guard.owner_wait_phrases` as waiting on the owner. A later line that starts with `push-guard.decision_marker` (`Decision:`) clears it. commit-check (and `structure-check --pr`) refuse a PR that is still waiting and tell the session to pick the safest reversible option, act on it, and record it in a `Decision:` line.

- Matching ignores case.
- The check skips code fences, quotes, inline code and forge_events log comments.
- A phrase that ends in `:` counts only at the start of a line.
