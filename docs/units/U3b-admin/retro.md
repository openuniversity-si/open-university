# U3b admin: retro

Unit: `admin-domain`, `admin-server` (lane `admin-lane`). PR #607. Branch `claude/u3b-admin-addresses-p08vs1`.
Covers the whole unit from the brief to the gate. Times are UTC from `git log`.

## 1. Brief quality

- Missing: the branch name. The brief said `mod/u3b-admin-addresses`; the session's designated branch was
  `claude/u3b-admin-addresses-p08vs1`. The designated branch was used; the brief should name one branch.
- Ambiguous: "rewrite every import that crosses a unit boundary". It did not say what to do with files the Node-run
  tooling loads (Node cannot read tsconfig `paths`). The merged U3b precedents (`3c0ffb84`, `a0cccfff`) answered it;
  the brief should cite them.
- Wrong: "`gh api` for the PR" while the session has only the GitHub MCP tools for PRs. The PR was opened with
  `mcp__github__create_pull_request`.
- Wrong: the brief asked for "a PR comment" for each step; no comment tool was named for this session. Comments go
  through the GitHub MCP tools.

## 2. Audit and plan

- Premises P-03 (validated, high) and P-13 (inferred, medium) held: every rewrite resolved (`tsc` ok), and the lane
  owns both units (`scripts/units who`).
- The plan changed once in substance: the Node-run closure was first computed from every file under `apps/web/scripts`,
  including vitest test files. That marked 73 specifiers in 15 files as Node-run, but the closure reached the admin
  server only through `test/fixtures/admin-catalog.ts`, imported by the Node script `factory-bench.ts`. The first
  dry run also wrongly included the test files. Fixed by starting the closure from the non-test Node entry points.
  The corrected closure reached the same 15 files: the server files are Node-run through `factory-bench.ts`, so the
  plan's "domain only" assumption was wrong and the rule was applied to the whole closure.
- A rewrite is kept relative only when the Node closure reaches it. This is recorded as a contract gap for the tooling
  owner, not a silent exception.

## 3. Execution

Timeline (UTC, from `git log`):

| time | event |
|---|---|
| 06:44-06:50 | Audit: base read, `scripts/units addresses --json`, dry run of the rewrite script (no file written). Baseline battery run twice (the first attempt exited 127 because `/usr/bin/time` is absent; the second attempt of the loop exited silently, see lesson 3). |
| 06:50 | Rewrite applied to 15 files (58 specifiers). Audit commit `4d5b3124`. |
| 06:52 | Plan commit `f0469cfe`. Draft PR #607 opened. |
| 06:53:16-06:53:35 | Five rewrite commits, one push each (`07115ee1`, `92fbf7db`, `86d58228`, `3638d22a`, `df9a18b6`). |
| 06:54 | Census commit `29b042b1`. |
| 06:57 | Gate run 1 failed. The base had moved (`c0e748c8`, PR #597). Merge commit `51b03247` (merge, not rebase) of the moved base. |
| after 06:57 | Gate run 2 on `51b03247`: PASSED, 501 s wall (the commit time of the merge is 06:57:17). |

Failures and root causes:

- Gate run 1: structure-check, the vendor check reported "baseline gains" for 34 sites in files this PR does not touch.
  Class: env (base drift). Evidence: with the base ref passed correctly (`origin/mod/roadmap-integration`) the same
  check on the head returns 0 errors; after merging the moved base, the second gate passed the structure check.
  Not proven: why run 1 read a base that did not agree with the vendor catalog. The gate's base ref was not recorded
  in the log I read.
- My own mistake in the first vendor-check probe: a path was passed where the function expects a git ref, so the
  baseline came back empty and every site looked new. Found by reading the function (`shrink_errors` calls
  `git show <base>:<path>`).

Rework: the closure computation (see section 2). Dead end: the classifier call (section 4).

## 4. Gate

- Run 1 on `29b042b1`: FAILED at structure check (class code as labelled by the gate; see above). Wall 108 s.
- Run 2 on `51b03247`: PASSED every stage. Wall 501 s, above the 180 s ceiling (D-064 (f)): the gate prints a warning.
  Stage times in `.gate/` logs (gitignored); the summary is in PR #607 comments.
- The DB classifier (`scripts/lib/gate_policy.py classify`) answered "Cannot classify actual PR diff; full database
  gate required" and set `db=1`. The diff touches no DB path (`git diff --name-only` has no `db`, `drizzle` or
  `migrat` file), but the classifier could not confirm it from the PR. A full gate-db needs the Neon credentials,
  which this session must not use. The PR is therefore left open, not merged.

## 5. Lessons

1. Closure for Node-run code: compute it from the non-test entry points only. Owner: the rewrite tooling of the unit
   program (U3b precedent). Action: the script in this lane's scratchpad is not committed; a committed resolver for
   `@ou/*` on the Node path is the real fix (tooling owner, D-069 item 7).
2. Brief: name the branch once and cite the precedents for Node-run exceptions. Owner: the maestro brief template.
3. A background battery wrapped in a subshell with `source scripts/cloud/env.sh` exited without writing its output.
   Action: `scripts/unit-battery` should exit non-zero with a message when it writes no report. Owner: U3a
   (`scripts/unit-battery`).
4. The gate's vendor check compares against a base ref that can move between a gate run and its base. Action: the
   gate should record the base SHA it used in its summary, so a run 1 failure can be traced. Owner: gate owner
   (`scripts/gate-local`).
5. The DB classifier fails closed when the PR diff cannot be read, and then requires the full gate-db. Action: when
   the PR fetch fails, classify from the local `git diff` against the base and print that the fallback was used.
   Owner: `scripts/lib/gate_policy.py`.
6. The unit battery's `over_limit` (10 s) is hit on this 4 vCPU machine before and after the change (types 15-18 s).
   Not loosened. Action: owner O1 / the battery budget owner to decide how the cloud machine is measured. Recorded in
   `docs/units/U3b-admin/census.md`.
