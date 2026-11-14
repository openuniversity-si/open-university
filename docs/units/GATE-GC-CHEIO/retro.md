# GATE-GC-CHEIO — retro

## 1. Brief quality

- Branch: the brief said `mod/gate-gc-cheio`; the session was assigned `claude/gate-gc-folder-retention-0kcjxm` and
  must not push elsewhere. The assigned branch was used (one branch, one PR, #777).
- "Re-measure the table": the table is the box's (`/workspace/torre`); this cloud container has no such path
  (`ls -d /workspace/torre` → `No such file or directory`). The box's numbers are quoted as the brief's, the
  container's own are measured with their commands beside them, and the files per run are measured on this unit's own
  gate runs (section 4).
- "review_by, in the same shape as gate-gc.reports_keep": `reports_keep` has no such field and the registry
  meta-schema forbids one (`additionalProperties: false`). The review date went into `x-source`.
- "Respect the existing gate.lock if it names one": it never does (`exec 9>"$lock"`, nothing writes a sha, a waiter
  truncates it). Honoured anyway, and the running gate's own sha comes from the exit hook instead.
- "Test (a) failing alone": disabling the folder collection fails every test that asserts a folder-bound removal (6 of
  18), and none of the 12 others; run alone, (a) fails. Both are recorded in the PR body.

## 2. Audit and plan

- Held: one function, one hook line, two keys. The readers were few and all read their own newest run, except
  `gate-dev --why <path>`.
- Broke, caught by the composition test before the first push: ranking shas by the sha directory's own mtime. The
  per-(sha, mode) removal runs first and touches that directory, so every pruned old sha looked newest and the newest
  shas were removed. Recency is now the newest run inside the sha. Mutation: restoring the sha-directory mtime fails (a)
  and (b).

## 3. Execution

Commits 1-5 as planned, each pushed alone by the post-commit push guard.

Decisions taken in scope, with their reason, as they happened:

1. Assigned branch over the brief's (session rule: never push to another branch).
2. `OU_CONFIG_STORE=file` for setup, commit-check and the pre-push hook while GitHub answered 429 for ~25 min (the
   shared config store is read over REST; the file store is this checkout's log). Gate runs waited for the limit to
   clear instead.
3. Keys from the train's own registry (16 = `train.batch_size` × `train.queue_growing_batches`; 8 = one batch), not
   from the palliative's 12 — audit step 3.
4. `/proc` became the registry key `gate-gc.proc_dir` (the literal census refuses an absolute path), read lazily so
   `gate_gc.py limits`, called once per stage, does not read it.
5. Liveness from three sources (own sha, held lock naming shas, open descriptors/working directories) and one floor
   (nothing at least as recent as a sha a gate writes, nothing touched since the collection began). A reader holding an
   old sha protects only that sha, never the floor: otherwise one `less` on an old log would suspend the bound.
6. `gate-dev --why` on a removed run says it is gone (it used to say "did not reach its report").

## 4. Gate

- Run 1, `scripts/gate-dev --pr 777`, head `bf0c51c0`, 21:01-21:07Z, pinned to the base tip `edf15a1d`: FAILED in
  328 s. Two red stages, neither from this change: `pr metadata` (plan item 5 not ticked yet; it is this commit) and
  `script tests` (`scripts/tests/rule.test.sh: No such file or directory`, a test the base added after this branch
  forked; the advisory run was skipped for the same reason, "merge the base first"). Every other stage was green,
  including `gate-gc.test.sh` and `gate-explain.test.sh` in the script tests. Fix: merge commit of the base
  (`33e25af2`), then this commit.
- The run wrote 3,288 files (3,821 inodes) into one report directory: the brief's ~3,300 holds here too.
- The later runs and their numbers are in the PR comments and the PR body's Evidence.

## 5. The same shape elsewhere (step 6)

Measured in the audit (top 10 by `du -s --inodes`): `/tmp/tower-gate-pin` is already bounded on the folder
(`gate-pin.keep_worktrees`); `.gate/evidence` has the same unbounded shape (one directory per `ship-verify` run) but is
frozen with production (D-054). The box itself was not reachable from this session.

## 6. Lessons

- A retention test must assert the folder, not only the key: GX-19 promised "report directories stop growing past the
  bound" and its test proved the per-key bound only (owner: gate-excellence brief author — add "the bound holds on the
  container, measured after N pushes" to every retention done-line).
- Recency must come from the data, not from the directory that the collector itself mutates (owner: engine-gate-run).
- An inode table can fill while `df` shows free space; the preflight checks writable paths but not free inodes
  (follow-up, not fixed here: `scripts/cloud/preflight` names a full inode table as an env gap).
