# HD1 retro (2026-10-27)

## 1. Brief quality
- It named `scripts/gate-db.sh`, but that file does not exist; the stage list is `scripts/lib/gate-db.sh`, sourced by `gate-local`.
- It said hermetic mode should run "the SAME migrations ... with the same assertions" on a local Postgres. The brief did not cover the fact that `apps/web/scripts/lib/database-target.ts` refuses the `pr` target unless the host is a direct `*.neon.tech` endpoint with `sslmode=require`, database `tower_v1` and role `tower_v1_app`. So goal (a) cannot be done inside the files the brief assigned; it needs an app change (a new local target) owned elsewhere.
- One hour from launch (13:31 UTC) to the green deadline (14:30 UTC), for a two-goal unit plus audit, plan, retro and the agent-tree ceremony. Goal (a) did not fit.
- Branch conflict: the session was told to use `claude/hd1-po3rd3` and the brief said `mod/hd1`. I used the brief's branch.

## 2. Audit and plan
- Premise P-a (neon_pr's assertions depend only on the URI) was **broken**. The URI is also validated by the app's migration tool against the Neon shape. I found this at 14:08 by running `db:migrate --target pr` on a throwaway local database. Reading `database-target.ts` during the audit would have shown it in about a minute: the audit stopped at the Python layer.
- Plan change at 14:15: commit 4 split into 4a (app `hermetic` target) and 4b (db_hermetic.py), recorded in plan.md. The draft of 4b is not pushed, because it would be a WIP commit.

## 3. Execution timeline (UTC)
- 13:31 launch. 13:35 audit.md pushed. 13:38 plan.md pushed, draft PR #677.
- 13:40-14:06 commit 3. Dead ends:
  - The class guard in the new test matched its own file.
  - A bare `wait` in cleanup hung on a fake that outlived its pid variable.
  - `pkill -f <pattern>` killed the session's own shell twice (exit 144), because the pattern was also in the shell command line.
- Found during commit 3: gate-db.test.sh was already failing on base with `ModuleNotFoundError: gate_select`. Root cause class: a fixture that copies a hand-kept file list drifts. Fixed by copying the whole lib.
- 14:00 STATUS comment. 14:06 commit 3 pushed. 14:08 hermetic blocker found. 14:09 plan change and base merge pushed.

## 4. Gate
- Run 1 (head 166098c4): `schema compat` failed because `delivery.test_fake_start_attempts` was removed without a revision marking it deprecated. Class: contract evolution (expand, then contract). Fix: the key stays, marked `deprecated`, at 8741414e. The run was stopped after this failure.
- Run 2: see the RETRO PR comment for the final result.

## 5. Lessons (change, owner)
- **The audit must follow a value to its final consumer, across languages.** For a URI, that means the app tool that validates it. Change: an audit-template line, "trace each value the unit swaps to where it is validated" (owner: PD2, padrao v2 brief template).
- **Removing a registry key is a contract change.** `scripts/commit-check --local` (pre-push) could run `schema_compat.py` on the registry diff (about 3 s) so the gate does not discover it (owner: config/registry owner, local-checks.json).
- **Never `pkill -f` with a pattern that is also in the calling command.** Use pids from `ps`. Change: a session tooling note in AGENTS.md "Rules" (owner: A Torre).
- **Copy whole directories in shell fixtures, not hand-kept lists.** The other suites with hand lists (e.g. invoker-tooling) are candidates (owner: engine-test-support).
- **Brief template: check the deadline against the scope.** A one-hour slot for a cross-layer unit should be split at brief time (4a app target, then 4b gate) (owner: coordinator CO1).

## GX-07 landing (27/10, base tip ef01174d)

- Merged the base twice (54e05d45, then GX-04 #693 ef01174d): both clean, `scripts/generate` produced no diff.
- The base-tip verdict (D-A3) failed gate-db, invoker-tooling and merge-phase with "rest fake did not start". Root cause: a
  script test's Python has the pinned tooling's `config` module loaded first (`scripts/lib/hermetic/sitecustomize.py`),
  and its registry does not know `delivery.test_fake_ready_max_s`, a key this tree adds. Reproduced with
  `PYTHONPATH=<base>/scripts/lib/hermetic`. Fix inside HD1's file: `rest_fake.py` reads the keys through the subject
  tree's own `config.py` as a child (1b58c223). Class: under the pinned gate, a tree that adds a registry key cannot read
  it through an in-process `config` import in a script test; read it with `python3 <tree>/scripts/lib/config.py get`.
  Owner: GX-05 (pinned gate) should say so in the script-test conventions.
- The same verdict then failed only `root-identity.test.sh` ("Fatal Python error: init_fs_encoding" as uid 65534). It fails
  identically on an untouched checkout of the base tip in this cloud container: environment, not HD1.
