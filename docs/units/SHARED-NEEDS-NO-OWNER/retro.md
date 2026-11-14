# SHARED-NEEDS-NO-OWNER retro

Branch `claude/shared-paths-ownership-refusals-ubmrj4`, PR #778, base `mod/roadmap-integration`: branched at 1de1fc2b,
merged up to 0a735f77 (938364f7).

## 1. Brief quality

- **The rule and the stop checked out.** Both refusals, the code path and the docstring quoted in the brief ("it stays
  owned (refusals() still names its owner)") are on the base exactly as described. The brief counted 19 of 21 open
  non-draft PRs at 17:26. At 21:01 the measurement gave 17 of 22: the open set had changed, and the brief was right.
- **It missed the second caller.** `refusals()` has two callers: `train.owned()` and `forge_events.unit_of`, which
  borrowed it to name the units of a change. Applied as written ("refusals() excludes the shared globs"), the fix would
  have dropped the `unit` of every change of only shared paths, and the train queue weighs entries by `unit`. LANE-OWN's
  audit (finding 2) had recorded that caller; this brief did not carry it forward. The fix gave naming its own query,
  `units()`.
- **Two instructions contradicted the change.** "(c) the existing tests keep passing" cannot hold for the LANE-OWN test
  that pinned the old refusal of a shared path. It was rewritten to pin the new rule, and every other test is
  unchanged. "Show test (a) failing alone" under M1 conflicts with (b)'s own specification ("names only the non-shared
  file"): under M1 the refusal also lists the shared file, so (b) fails too. I read "alone" as "run by itself", ran it
  that way, and reported both failures.
- **The approval is impossible for a second reason the brief did not give.** `refusals()` compares the manifest
  `owner`, a lane id, with reviewer logins. No review can ever match, independent of who reviews (audit, "Why the
  approval never arrives").
- **Branch naming, second unit in a row.** The brief named `mod/shared-needs-no-owner` and the session was assigned
  `claude/shared-paths-ownership-refusals-ubmrj4`. The assignment won, as in LANE-OWN.

## 2. Audit and plan

- Premises held: the train reads manifests at the integration tip; every shared glob is also in `paths`; `refusals()`
  had exactly two callers at the base (`git grep -n "\.refusals(" 1de1fc2b -- scripts/lib`: `train.py:174`,
  `forge_events.py:82`), and has one now.
- Item 6 found one rule that waits for an approval that cannot arrive: the train's ownership refusal itself. Its
  non-shared half stays (the brief keeps it). It fires only when manifests change between a PR's merge base and the
  tip, because the gate's lane rule already refuses a PR whose non-shared paths span lanes, and its approval clause
  is dead in a single-identity repository. Recorded, not fixed.
- The plan did not change, apart from the order: 6 ran before 1 (section 3).

## 3. Execution (timeline, commit times UTC)

| Time | Commit | Note |
|---|---|---|
| 20:39 | f7a55a90 | step 0: audit skeleton, draft PR #778, STATUS |
| 20:45 | 1b7ea762 | item 6, written while REST was blocked |
| 21:03 | 52c46f22 | item 1: measurement (block lifted 21:00:41) |
| 21:03 | a0663d79 | item 5: plan |
| 21:06 | 9d8bc80d | item 2: `deciding()`, `units()`, two tests adapted |
| 21:08 | 6c3b0bf2 | item 3: train tests (a), (b) |
| 21:11 | f0f33b80 | item 4: mutation proof, run on 6c3b0bf2 |
| 21:16 | bee0fb49 | item 5: this retro (first version); gate run 1 on it |
| 21:25 | 938364f7 | merge of the base, 28 commits behind (section 4) |

The fix and its tests were written and dry-run in a separate git worktree while REST was blocked. Each commit then
went in on its own: code stashed for the docs commits, every suite re-run in the main checkout before each code commit,
and one push per commit through the push guard.

Failures and rework:
- **Setup stopped at 20:31, silently.** The session's GitHub limiter had recorded a rate-limit refusal (a 29-minute
  block), and `scripts/cloud/setup.sh` reads the registry through the shared change store over REST, so it stopped
  after installing Python. The same block made `env.sh`'s push-guard install fail without a word (`|| true`), so
  `core.hooksPath` stayed unset and the push guard was inactive. I found both only by checking `.toolchain/bin` and
  `git config`. Worked around with `OU_CONFIG_STORE=file` for setup, hooks and local checks, and by waiting out the
  block (the client's `max_wait_s`) for REST. Class: env.
- **The literal census refused my first tests.** They wrote PR numbers, and `2` appeared 46 times in engine-train
  where the census allows 41. The repository's own structure check caught it in the worktree dry run, before any
  commit. The tests now number PRs with the fixture's `make()` (LT1), as the fixture's docstring already said.
  Class: code.
- **A test of absence that could not fail.** The first draft of (a) asserted no `pr.refused` with
  `self.events(None, ...)`, which reads the repository channel, while `pr.refused` lands on each PR's channel. I
  caught it while writing the test. The mutation proof would not have: under M1, `self.asked` already turns (a) red.
  Class: code.

## 4. Gate

- Local evidence before the gate: the 14 suites that reach `train_ownership`, `unit_of` or `pr_ready` are green
  (`test_unit_of`, `test_gate_report_v4`, `test_gate_v4_readers`, `test_generate`, `test_literal_census_derived`,
  `test_plan_tick`, `test_pr_ready`, `test_quarantine`, `test_slo`, `test_structure`, `test_train_role`, `test_units`,
  `test_units_companion`, `test_train`), along with `forge-events.test.sh`, `train-role.test.sh`, and
  `scripts/structure-check` with 0 errors and the base's 48 warnings.
- `scripts/gate-dev --pr 778 --explain` on f0f33b80: 10 stages, full selection (`scripts/lib/forge_events.py` is a
  full-battery file), 33 script tests, preflight ok.
- **Run 1, head bee0fb49 (21:19:44-21:25:03, 292 s, ceiling 180 s): FAILED**, on two stages with one cause. While the unit
  ran, the base moved: RULE-AUDIT (#775) and ADDR-MAP-SHARED (#779) merged. `pr metadata` refused the head as "21
  commit(s) behind mod/roadmap-integration … (21 behind, limit 20)", and `schema compat` read the base's new
  `config/registry/rules.json` as 7 properties "removed without a revision that marked it deprecated". The other 8
  stages passed: both secret scans, no workflows, generated drift, structure check, install, unit tests (117 s) and the
  33 script tests (181 s). Class: code (process); the remedy is the one the refusal names.
- **Base merge, 938364f7**: `git merge origin/mod/roadmap-integration`, a merge commit and never a rebase. By then
  GATE-GC-CHEIO (#777) had landed as well, so the merge brought 28 commits, not the 21 its message says (the message
  was written from run 1's count, and pushed history is not rewritten). None of the 28 touches a file of this PR
  (`git diff --name-only 1de1fc2b 0a735f77 -- <this PR's files>`: 0). On 938364f7 the 14 suites are green again, and
  `scripts/structure-check` gives 0 errors and 48 warnings.
- **The measurement at the new tip**: the audit's command with `0a735f770 120`, run 21:26:42-21:28:06 with the fixed code,
  gives `{'open': 49, 'non-draft': 22, 'touch shared': 17, 'refused': 7, 'refused for a shared file': 0}`. The shared
  globs now include ADDR-MAP-SHARED's `apps/web/tsconfig.paths.json`, a declaration this fix honours with no change.
  The 7 refused (#596 #618 #635 #641 #645 #649 #662) have no lane, and each is refused only for non-shared units of
  other lanes.
- **Run 2** runs on the head that adds this revision of the retro, because plan completeness needs every item ticked
  before the gate can pass (LANE-OWN lesson). Its verdict is in the RETRO and MERGE-READY comments of the PR.

## 5. Lessons (change, owner)

1. A brief that changes what a function returns should list its callers (`rg -n "\.<name>\("`). Here the second caller
   would have moved the `unit` of events silently. Owner: A Torre (brief template).
2. A test of absence must read the channel the event is emitted on, and it needs its own proof of failure: a mutation
   that another assertion already turns red does not test it. Owner: engine-lane (engine-train: a fixture helper that
   reads `pr.refused` from every PR channel of a run would remove the trap).
3. Machine bootstrap should not depend on the shared change store. A recorded REST block stopped setup half way and
   left the push guard off. Setup failed on `env.tool_version_probe_timeout_s` (`toolchain_manifest.observed_version`),
   and `env.sh`'s push-guard install failed on `push-guard.*`. Neither `env` nor `push-guard` is in
   `config.bootstrap_owners` (`cloud`, `toolchain`, `env-premises`), the NANO-UNBLOCK (D-070) list of parameters that
   never cost a read of the shared store. Adding the parameters bootstrap reads, or moving them to a bootstrap owner,
   closes it. Owner: engine-lane (engine-env, engine-config, engine-push-guard).
4. The brief standard should name the branch as "the session's assigned branch". This is the second unit in a row
   with the conflict. Owner: A Torre (brief standard).
5. The train's non-shared ownership refusal compares lane ids with reviewer logins, so its approval clause can never
   lift a refusal (audit, row 1 of the last table). Whether a cross-lane change should be refused outright, or lifted
   by something that can happen, is a rule to write down. Owner: A Torre with engine-lane (engine-train).

## 6. The step that should have descended

- **"Which open PRs does an ownership rule stop, before and after a change?"** This was measured by hand for the third
  time today: the coordinator at 15:05, LANE-OWN's 15-line script, and this unit's `measure.py` (about 45 lines,
  embedded in the audit, and run twice). It should be one deterministic command, for example `scripts/units refusals
  --open-prs --at <ref>`, that prints `lane_of` and `refusals` (nobody approving) per open PR. Cost this time: about
  15 minutes, and the REST reads of every open PR's file list, twice. Owner: engine-lane (engine-units, engine-train).
- **"Is this head too far behind its base?"** `gate-dev --explain` said "preflight: ok" on f0f33b80, and run 1 then
  spent 292 s to learn that the head was over `merge.max_behind_base`, which one compare call knows in a second.
  `--explain` (and the pre-push hook) should print the `rebase` verdict of `commit_check.rebase_errors` before a gate
  starts. Cost this time: one 5-minute gate run. Owner: engine-lane (engine-gate-plan).
- **The mutation proof is generic.** Applying an exact-once edit, running the named suites, restoring and comparing
  sha256 is the same for every unit that proves a fix by mutation. It could be `scripts/mutation-proof <file> <old>
  <new> -- <tests>`. Cost this time: two short scripts (`mutations.md`). Owner: engine-lane.
