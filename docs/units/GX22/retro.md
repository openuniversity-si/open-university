# GX-22 retro

One merge rule in `config/registry/merge.json`; P-G3 switch default on (today's rule). PR #722, branch `mod/gx22`.

## 1. Brief quality
- Clear on keys, files and fences. Missing: BD1's `merge_behind.py` needs four more keys (compare paging, overlap rule,
  paths shown) and a one-line `github_api` change (query strings) that the brief's file list did not name; taken under
  "own dependencies are in scope".
- `merge.require_exact_head` cannot be false in practice: `github_api` refuses `pr merge` without `--match-head-commit`.
  The key is read and, when off, merge-phase refuses with that reason (no silent relaxation).
- The brief named `mod/gx22`; the harness designated another branch. The brief won (one PR, one branch).
- HOLD/RESUME: launched before GX-37 merged; held at 21:13 with nothing written, resumed on d101b73c. Cost: ~5 min.

## 2. Audit and plan
- Premises held: GX-37's `forge_events.gate_evidence` was the exact read merge-phase needed; the REST fake already
  stored issue comments, so the forge_events GitHub adapter round-trips through it (no new fake adapter).
- Plan unchanged: 3 → (4 ∥ 5) → retro → gate. 4 and 5 ran in sequence by one writer (short; no sub-agents needed).

## 3. Execution (UTC commit times)
- 00:18 skeleton, 00:20 audit, 00:21 plan, 00:23 registry + merge_behind, 00:27 commit_check, 00:32 merge-phase.
- Failure 1 (class: the structure check's exit hidden by a pipe): commit 3 was pushed with 6 structure errors
  (literal census in the harvested test, undeclared `engine-events` import) because `scripts/structure-check | tail -1`
  returned tail's 0. The pre-push local check did not catch them either (its structure_fast subset skips the literal
  census and unit imports). Fixed in commit 4, which also carried its own change (no fix-up commit). Lesson: never pipe
  a check whose exit decides a commit; owner of the local-checks registry (LR1): add the literal census and unit-import
  check to `structure_fast` if they fit its budget.
- Failure 2 (same class, caught before commit): new numeric literals in tests (PR numbers, sha lengths, argv indexes).
  Fixed by deriving every value from fixtures/registry (plan-tick `gate_passed`, `merge.max_behind_base`) and shrinking
  the baseline with `literal_census.py --write` (it also tried to grow a count, which I removed at the source).
- Failure 3 (class: wall clock in a unit test): `datetime.now` in the switch fixture → `hermetic.clock()`.
- Design choice: commit_check formats "N behind, limit M" itself instead of importing merge_behind, to avoid a new unit
  edge engine-commit-plan → engine-delivery.

## 4. Gate
- Run 1 (pinned, head 11e84a2d, 00:37 UTC): FAILED, three causes:
  1. structure check, production guard: merge_behind's log reader passed the producer string 'merge-phase', a
     production entrypoint mention. My local structure-check ran without `--base`, so the diff-based checks (production
     guard, literal growth vs base) never ran locally. Fixed (producer 'merge-rule'), commit 7.
  2. claude-session.test.sh: besides its known env failure (GX-ENV), `test_claude_session.py` proved merge-phase with a
     local `abc123.pass` record, which merge-phase no longer reads ("gate has not passed at abc123 in the event log").
     I searched merge-phase's callers for the `.pass` contract only in `scripts/tests/*.sh`; this caller is a `.py`.
     Fixed (proof emitted to the fake forge), commit 7.
  3. hermetic.test.sh `test_the_trace_directory_is_removed`: INCIDENT below. Fixed, commit 8.
- Run 2: on the head carrying commit 8; result in the RETRO/MERGE-READY comments.

## INCIDENT (gate run 1, hermetic.test.sh set mismatch)
- Cause (confirmed): the test compared the set of `ou-covers-*` directories in the SHARED temp directory before and
  after one traced child run. In the gate, other script tests run at the same time and their covers traces create and
  remove `ou-covers-*` directories there, so the "after" set held another test's directory. Not caused by
  `config/registry/merge.json`: the test passes alone on this head (14 OK) and reads no registry list; the PR's two
  extra script tests only changed the interleaving. The coordinator's hypothesis (a registry file missing from hermetic
  expectations / test selection) does not hold: hermetic.test.sh did run in the gate (it is what failed).
- Class: a test asserting on a process-global shared location (`tempfile.gettempdir()`) that concurrent tests write.
  Searched `scripts/tests/` for every glob of the shared temp dir: this was the only occurrence.
- Fix: the child gets its own TMPDIR and the assertion reads only that directory (no shared state; D-069 item 5).
- Prevention (owner engine-tests / hermetic rules): add a hermetic structure rule refusing `gettempdir()` globs in unit
  tests, like the existing wall_clock rule.

## 5. Lessons
- Rule (all units): run `scripts/structure-check --base origin/<base>` locally; without `--base` the diff checks
  (production guard, literal baseline growth) are silent. Owner: brief template / LR1 local checks.
- Rule (all units): when changing a contract (here the `.pass` proof), grep every caller in every language
  (`git grep -n 'merge-phase'`), not one file type.
- Rule (all units): run structure-check and commit-check unpiped (`|| exit`) before each commit; owner: brief template.
- Tool (LR1 owner): local `structure_fast` should include the literal census for changed files.
- Contract (GX-30): the train reads `merge.max_behind_base`, `merge.tier1_requires_base_merge`; GX-27 flips the switch
  with `scripts/config set merge.tier1_requires_base_merge false` (shared store, GA-PG8).
