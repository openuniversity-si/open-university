# RULE-AUDIT retro (phase 0 and the rule system)

Unit RULE-AUDIT, PR #775, branch `mod/rule-audit`, base `mod/roadmap-integration` 5a753035. Launched about 16:49 BRT
28/10; first push 16:51; scope grown four times by Daniel (16:52, 16:55, 17:08, 17:09); one coordinator session with
three sub-agents (the rule-system builder; census rows for refusals and resources; stop counts from PR history).

## The descent and the counts

| What | Count | Command or source |
|---|---|---|
| Census rows | 1017 | `census.json` › `row_count_command` |
| Registry parameters | 799 (792 at the base, 7 of `rules.json`) | `census.json` › `measurements` |
| ... with `x-source` / with a review date | 311 / 0 | same |
| Decisions | 63 (0 with a review date) | `grep -cE '^\| *D-[0-9]{3} ' docs/domain/DECISIONS.md` |
| Premises | 53 (35 undated) | `ls docs/process/premises/*.yml \| wc -l` |
| Refusal functions | 48 in 29 modules (census pattern); 37 in 20 by the brief's `errors` pattern | `census.json` › `measurements` |
| Routines / paid or metered calls | 22 / 32 | `census.json` › `resource_commands` |
| Scheduled tasks of this account | 0 | `list_triggers`, 28/10 |
| Rows that can stop the flow | 119 | `census.json` › `stops` |
| Refusals with a stop count from PR history / never measured / that stopped at least one PR | 41 / 7 / 14 | `census.json` › `stops` |
| Groups | 16, 1017 rows grouped, every id once, 62 to 86 estimated minutes each | `groups.json` › `count_command` |
| Briefs | 16 | `ls docs/audits/rules/briefs/*.txt \| wc -l` |
| Rule records / stops without a question / stale premises | 1 / 47 / 31 | `scripts/rule check --today 2026-10-28` |

The descent of the program: Daniel's order (16:46, 16:47) -> this census and cut -> 16 phase 1 audits launched by
A Torre in the README's run order -> phase 2 turns the KEEP and WARN verdicts into records of `rules.json` and the
DELETE verdicts into removals -> `scripts/rule check` counts what is left until refuse mode can be switched on.

## 1. Brief quality

- The brief cited files that do not exist where the session runs: `/workspace/torre/motor/v3/backlog/regras-que-param.md`,
  `/workspace/torre/motor/v3/rules/commitment.md`, `rules/language.md`, the queue `/workspace/torre/motor/v3/queue/rule-groups/`
  and `tools/language-check.py`. A cloud container has no `/workspace`. #774 (RULE-MASS) hit the same gap the same day
  and made the same decision: the same decision twice.
- "38 refusal functions across 20 gate modules" came without its command. The `errors` pattern gives 37 in 20 modules
  on 5a753035 (#774 measured the same 37).
- The brief named the branch `mod/rule-audit`; the session harness named another. The brief's branch was used: one
  branch, one PR.
- "8 to 14 groups" does not fit about 1000 rows: at an honest per-row estimate the census is about 1180 minutes of
  audit, and "never larger than one session" forces at least 16 groups. The brief gave no estimate model; `groups.json`
  now carries one.
- The scope grew four times in twenty minutes, each as a separate message, while the builder sub-agent was already
  writing code; the deadline grew from 75 to 120 minutes.
- The brief expected firing counts; the gate records that hold them live on the box. PR history was the cheapest
  readable substitute, and it only sees what was posted to GitHub (a refusal from a local run never reaches a PR).
- The brief did not say that plan completeness ticks the retro before the gate while the retro must report the gate:
  the two orders conflict (see 4).

## 2. Audit and plan

- P-a (counts reproduce): held for 792 / 304 / 0 parameters, 63 decisions, 53 premises; broke by one for refusals.
- P-b (box path unreachable): held; briefs committed in the repo and written to the queue path in the container.
- P-c (a new registry file passes without touching `registry.v1.json`, which #774 edits): held; the record schema is
  inline in `rules.catalog`.
- P-d (a new unit manifest, one lane): held; `units/engine-rules` (engine-lane). It changes the generated `CODEOWNERS`,
  which makes the gate select the full battery.
- Plan changes: 7 items became 8; 16 groups instead of 14; the refusal estimate went from 5 to 4 minutes per row (the
  census row already carries callers, owner and irreversibility); `slo` moved to the budgets group, `delivery` to the
  merge-train group, the event contract to planning, and the 54 resource rows became three groups; the census was
  regenerated once after the rule system landed, since its own rules are rules too.

## 3. Execution

Timeline (BRT, commit times): 16:51 README skeleton; 16:59 audit and plan; 17:05 template; 17:09 Q0 in the template;
17:14 README text (refused by the pre-push guard, pushed 17:19 from a clean worktree); 17:20 census; 17:21 groups and
briefs; 17:21 README tables; 17:27 rule register, library and tests; 17:30 `scripts/rule` (twice refused by the asset
inventory, fixed before it reached the remote); 17:31 SYSTEM.md; 17:33 census regenerated with the rule system; 17:36
the plan as executed with its effort block; then this retro and the gate.

Failures and their class:
- A sub-agent wrote its own generator to the scratch file name the coordinator's census builder used, overwriting it.
  Class: parallel workers sharing one scratch namespace. Cost: about 10 minutes to rebuild the builder from the
  coordinator's own record into a private directory.
- `prepush` refused a push of an unrelated commit because the builder's untracked files were in the same working tree
  (a registry file without its generated binding, a unit not yet in `CODEOWNERS`). Class: the pre-push guard judges the
  working tree, not the commit being pushed. Pushed from a clean worktree of the branch instead, where the guard runs on
  exactly the pushed content (0 findings each time); the guard was never bypassed.
- The asset inventory refused the new `scripts/rule` twice: first no entry, then a `retire` text outside its grammar
  (`never: <why>`, `migration:<name>`, `decision:D-NNN`). Class: a declaration the brief's file list did not name; it
  is an own dependency of the change, so it was added (`docs/structure/assets.json`).
- The local language stand-in flagged `com` and `ou` inside host names and identifiers; fixed by ignoring dotted,
  slashed and underscored tokens (the Portuguese sanity sample is still flagged).
- Where the quota went: the builder sub-agent (about 26 minutes, 98 tool calls), the census-rows sub-agent (about
  17 minutes, 76 calls), the PR-history sub-agent (about 10 minutes, 110 calls, about 66 searches), the coordinator.

## 4. Gate

One `scripts/gate-dev --pr 775` on the exact head that carries this retro. Its stage count and verdict line are posted
in the RETRO comment and the MERGE-READY comment on the PR, not here: plan completeness refuses a PR whose plan items
are not all ticked by commits, so the retro (item 8) must exist before the gate, and writing the verdict into the retro
afterwards would change the head the gate proved.

## 5. Lessons

| Problem | Change that prevents it | Owner |
|---|---|---|
| Box paths in a brief for a cloud session | The brief template names only repository paths; box files a session needs travel inside the brief or the repo | A Torre (brief template) |
| `tools/language-check.py` absent from the repo | Move the language check into the repo (`scripts/language-check`) so every session runs the same check | A Torre |
| A count in a brief without its command | Every number in a brief carries the command that produced it | A Torre (brief template) |
| Sub-agents overwrote each other's scratch files | Each sub-agent writes only under its own scratch subdirectory, named in its brief | coordinator (agent tree rule) |
| `prepush` judges the working tree | Judge the tree of the commit being pushed (`git archive` or a temporary worktree of that commit) | engine-push-guard |
| Four scope additions in twenty minutes | One consolidated amendment with its deadline change; the coordinator re-briefs once | A Torre |
| Group target vs census size | The brief template states the estimate model and lets the count follow from it | A Torre (brief template) |
| Retro before the gate vs retro reports the gate | The gate verdict lives in the PR comment; the retro names the run and links it | A Torre (padrao) |
| Asset inventory not in the file list of a brief that adds a script | The unit template lists the declarations a new script needs (unit manifest, covers, asset entry, CODEOWNERS) | structure owner |

## 6. The step that should have descended

| Work done by an AI today that would be done identically tomorrow | Descends to | Cost this time | Owner |
|---|---|---|---|
| The census builder (parameters, decisions, premises, refusals, resources into one JSON) | a deterministic script in the repo, `scripts/rule census`, reading the same sources | about 25 minutes including the rebuild | rule system next unit |
| The domain map that cuts the census (which group each registry file, decision, premise and refusal belongs to) | data: a `domain` on each registry file, decision row and premise record, so the cut is a script | about 15 minutes | structure owner and premise register |
| The brief generator (template plus rows) | `scripts/rule briefs`, next to the census | about 10 minutes | rule system next unit |
| The refusal discovery pattern | already descended in this PR: `rules.stop_patterns`, read by `scripts/rule check`, equal to the census pattern | done | done |
| The stop counts from PR history (about 66 searches by an AI) | a script over the gate records and forge events that counts stops per rule, with the question id on every stop event (SYSTEM.md next units) | about 10 minutes of a sub-agent | engine-events and rule system |
| The language check stand-in | the repository's own language check | about 5 minutes | A Torre |
| The decision "the box path is unreachable, commit the file to the repo" (made by #774 and by this unit the same day) | a rule in the brief template | about 2 minutes, twice | A Torre |
| The decision "push from a clean worktree because prepush reads the working tree" | the prepush fix above | about 5 minutes | engine-push-guard |
