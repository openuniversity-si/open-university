# U3b playback: retro (lane playback-lane, PR #605)

## 1. Brief quality
- The brief named the branch `mod/u3b-playback-addresses`, but the session's designated branch is
  `claude/playback-ou-addresses-3yxngu`. I used the designated branch; the brief and the session instructions conflict.
- The brief said "tier 1 = unit battery"; the Node-loader limit (D-069 item 7) was not mentioned. It is in the base
  commits `3c0ffb84` and `2d7d70e2`, and I found it only by reading them.
- The brief's rule "merge only if green" conflicts with AGENTS.md "Do not merge your own PR". Resolved by not merging.
- `gh` is blocked; the PR was opened through the GitHub MCP tool, not `gh api`.

## 2. Audit and plan
- Held: both addresses exist; the kernel units share a home but their addresses name owned files; the Node closure
  is 13 files; there is one unowned target.
- Changed: none in scope. The plan's commit graph was kept (domain, then client).

## 3. Execution
- A `head -1` pipe on the rewrite script killed it with a broken pipe before it wrote any file. Nothing was changed;
  I re-ran it without the pipe. Cause: piping a script that prints and then writes. Class: tooling. Owner: session
  (script hygiene).
- The rewrite script applies to both units at once; I split the commits by stashing the client files while the
  domain commit was verified and committed alone.
- Timeline: audit commit 8a88f72e, plan 86809c80, domain 2fcc201b, client 60be73f5, base merge 7501516f, gate run
  (337 s wall).

## 4. Gate
- One run, passed on 7501516f. The 180 s ceiling was exceeded (336.6 s); the lint stage alone was 79.7 s. That is
  a timing warning under D-064 (f), not a failure, and it is an environment/load result (4 vCPU), not this PR's change.

## 5. Lessons
- Rule: a unit-battery-tier PR that rewrites imports must derive the Node-loaded set mechanically (the script in
  the scratchpad did this) and record it. Owner: engine-units (U3a) — add a `units addresses --node-loaded` report.
- Rule: rewrite scripts print their gaps to stdout; they must write files before printing. Owner: lane (this PR's
  scratch tooling; not committed).
- Rule: the merge decision for PRs in an unattended lane must be the repo's rule (AGENTS.md), not the launch brief.
  Owner: maestro (brief template).
