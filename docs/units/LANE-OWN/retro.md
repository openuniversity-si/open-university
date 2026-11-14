# LANE-OWN retro

Branch `claude/lane-ownership-paths-lqqq9d`, PR #771, base `mod/roadmap-integration` @ 5fe8da27d.

## 1. Brief quality

- Clear rule, clear alternatives rejected, named files all existed on the base (audit table). Good.
- **Measurement was one family at a time.** The brief removed the census family, then the web-config family,
  each alone. 659 needed both, so the brief counted it as lane debt. 635 and 645 carry `tsconfig.json`, but they
  also change two real units each, so the brief counted them as fixed. The real count, measured with both rules
  on the PRs' REST file lists: 10 of 17 decidable, 7 real debt (PR comment, table).
- Not stated: manifests are read **at the merge base**, so the rule acts on other PRs only after this one merges.
  It also did not say that `refusals()` will still ask a tooling- or ui-lane PR that regenerates the census for
  an engine-lane approval in the train. The brief does want that ("sharing removes the ambiguity, never the
  owner"), but the effect on the train queue is worth a sentence.
- Branch naming: the session's assigned branch (`claude/lane-ownership-paths-lqqq9d`) differs from the brief
  standard's `mod/<unit>`. The session's assignment won.

## 2. Audit and plan

- Premises held: the census files are generated (`literals:census`, `catalog_files`); every file this PR changes
  is engine-lane or unclaimed, so the PR was decidable under today's manifests.
- Finding that shaped the design: `lane_of` and `lane_errors` were two copies of one match. The fix was one
  helper, `UnitOwnership.lanes()`, that both call. Without it, "they must agree" is only a docstring.
- `refusals()` needed no change, only a test. That shrank item 4 of the brief to a test.
- Plan unchanged, apart from one file the plan missed: `contracts/generated/typescript/contracts_units_unit_v1.ts`
  (the schema has two derived files, not one).

## 3. Execution (timeline, commit times)

| Time | Commit | Note |
|---|---|---|
| 18:09 | a692eb16 | step 0: skeleton, draft PR #771, STATUS |
| 18:14 | 9b8350b5 | audit + plan |
| 18:18 | 8f169efa | lane rule (item 4), here; item 3 ran in parallel in a sub-agent |
| 18:20 | 16bfff2c | schema + validation (item 3) |
| 18:23 | 56bb626d | declarations + approval-duty test (item 5) |

Failures and rework:
- **Self-inflicted test-file corruption.** While writing test_structure.py, I took a slice between two
  `index()` calls. The end marker also occurred earlier in the file, so the slice was empty, and `replace('', new)`
  inserted the text between every character. Caught at once by an IndentationError, and fixed with
  `git checkout` plus a redo through an assert-exactly-once `sub()`. Class: an unchecked text edit. The fix that
  stopped it from happening again in this session: every scripted edit asserts `count(old) == 1`. This is the
  same rule as the Edit tool's, and it should be the default for any scripted edit.
- **Generated drift found by the push guard.** The sub-agent's brief named only the Python derived file. The
  schema also derives a TypeScript file, so `scripts/generate --check` failed. The cause was my brief (it listed
  derived files from memory), not the agent. Fix: run `scripts/generate ts-types`.
- **Push guard vs. a parallel working tree.** The pre-push check reads the working tree, so commit 4's push was
  refused because of commit 3's uncommitted schema change. Worked around by stashing the other commit's files
  for the push. This is safe only once no sub-agent is writing. Class: parallel commits in one working tree.
  The structural fix is one worktree per parallel commit (`git worktree add`), which `EnterWorktree` supports.

## 4. Gate

- Run 1, head 56bb626d (25 s, ceiling 180 s): every stage green except `pr metadata`, which failed with
  `plan: item(s) 6 not ticked`. Class: code (process). The plan-completeness check needs the retro commit before
  the gate can pass, so the retro cannot wait for a green gate; it goes in first, and its gate section names the
  run on its own head. Same layout as BASEFIX-shellcheck (retro `Plan: 6`, then the gate).
- Run 2, on the head that adds this file: the final gate; verdict in the RETRO comment and MERGE-READY.
- No known defect hit. Unit tests came from the tier-1 cache; 23 script tests selected.
- Lesson: the brief template says "retro after the final gate passes", but GX-21's plan completeness says "every
  item ticked before the gate passes". The two contradict each other for the retro item. Fix: the template should
  say "retro commit last, then the final gate on its head". Owner: A Torre (brief template).

## 5. Lessons (change, owner)

1. A sub-agent brief that changes a contract should say "run `scripts/generate --check`" instead of naming
   derived files. Owner: coordinator brief template.
2. Parallel commits in one PR: one git worktree per writer, or the pre-push check (which reads the working tree)
   refuses the other writer's push. Owner: the brief standard (parallel commits safeguards), engine-lane for a
   `scripts/` helper if wanted.
3. Briefs that measure "which PRs a rule fixes" should measure with every proposed change applied at once. The
   one-family-at-a-time method misclassified 3 of 17. Owner: A Torre (measurement step of the brief).

## 6. The step that should have descended

- **"Which open PRs does a lane-rule change unblock?"** I wrote a 15-line script for it today, and the coordinator
  measured the same thing by hand at 15:05. It should become a deterministic command, e.g.
  `scripts/units lane --pr <n> [--manifests <ref>]` (or `structure-check --lane-at <ref>`) over every open PR.
  Cost this time: about 5 min and 2 turns here, plus the coordinator's manual measurement. Owner: engine-lane
  (engine-units / engine-structure).
- **Declaring a new shared path** is now a data edit (`shared` in a manifest), not code: this unit already
  moved that decision down one step, from code to data. The next generated file shared by all lanes needs only a
  manifest line.
- **The census files' lane** was decided by hand twice (by the brief and in this audit). A rule in the engine
  could catch it: a path every lane writes, i.e. the `generate`/census outputs of `scripts/generate --list`, is
  shared by construction, and `units check` could warn when a generated output is in `paths` but not in
  `shared`. Cost today: the audit time spent confirming the files are generated (about 3 min). Owner: engine-units.
