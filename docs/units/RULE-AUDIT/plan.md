# RULE-AUDIT plan

Phase 0 of the RULE-AUDIT program, plus the rule system Daniel added at 16:52, 16:55, 17:08 and 17:09 BRT 28/10.
Deadline 120 min of work. Decisions: D-069 item 9, D-072, D-025.

## Commits (dependency graph)

| # | Commit | Files it owns | Depends on |
|---|---|---|---|
| 1 | README skeleton | `docs/audits/rules/README.md` | none |
| 2 | Audit and plan | `docs/units/RULE-AUDIT/audit.md`, `plan.md` | 1 |
| 3 | Census data | `docs/audits/rules/census.json` | 2; refusal and resource rows and the PR-history stop counts from two read-only sub-agents |
| 4 | Groups, template, briefs | `docs/audits/rules/groups.json`, `GROUP-BRIEF-TEMPLATE.md`, `briefs/*.txt` | 3 (real: the rows) |
| 5 | Rule register and library | `config/registry/rules.json`, its generated binding, `scripts/lib/rule_registry.py`, its tests and covers, `units/engine-rules/unit.json`, `CODEOWNERS` | 2 only (built beside 3 and 4) |
| 6 | Rule CLI | `scripts/rule`, its manifest lines, its asset inventory entry | 5 (real: wraps the library) |
| 7 | SYSTEM.md and the README complete | `docs/audits/rules/SYSTEM.md`, `docs/audits/rules/README.md` | 4 and 6 (real: names the groups and the commands) |
| 8 | Retro | `docs/units/RULE-AUDIT/retro.md` | everything above |

Critical path: 2 -> 3 -> 4 -> 7 -> 8 -> gate, about 15 + 20 + 10 + 10 + 10 + 15 minutes. Commits 5 and 6 were built by
a sub-agent in parallel with 3 and 4: no file is shared, so no edge between them is a collision edge. Commit 3 is
regenerated once after 5 and 6 land, because the census is the committed tree and the rule system's own parameters and
refusal function are rules too. The coordinator is the only writer of the branch and pushes after every commit.

## How the plan changed (and why)

- The rule system (items 5 to 7) arrived at 16:52 and grew at 16:55 (premises), 17:08 (stops as accidents, Q0) and
  17:09 (the standing question); 7 items became 8.
- 16 groups, not the target 8-14: about 1000 rows at the estimate model in `groups.json` leave no 14-group cut where
  every group fits one 90-minute session, and "never larger than one session" wins over the target.
- The census builder and the brief generator are deterministic scripts; a sub-agent's file overwrote the first builder
  in the shared scratch directory, so the coordinator's scripts moved to a private directory.

## Premises (blast radius)

- P-a: the census commands reproduce the brief's counts. Held for 792 / 304 / 0 and 63; the refusal pattern gives 37 in
  20 modules, one fewer than the brief. Radius: the census numbers only. Not critical.
- P-b: the box queue path is not reachable from this container, so the briefs are committed in the repo. Radius: where
  A Torre reads the briefs. Not critical, reversible (a copy).
- P-c: a new registry file `config/registry/rules.json` passes the registry's own checks without changing
  `contracts/config/registry.v1.json` (which #774 edits). Radius: the config check stage. CRITICAL for the collision
  with #774 if false. Held: the record schema lives inline in `rules.catalog`, the config tests pass.
- P-d: the new files can belong to a new unit manifest without touching another lane. Radius: lane ownership. Held:
  `units/engine-rules` is an engine-lane unit like the others it requires.
- P-e: no measurement here spends money or touches production; everything reads local files or GitHub read-only.

## Tests

- Per commit: JSON validity and the census/group consistency check (every row in exactly one group, sums equal); the
  English-only check (a local stand-in for `tools/language-check.py`, which is absent here); for 5 and 6
  `scripts/tests/rule.test.sh` (28 tests) plus the config, generate, premises, units and schema-compat script tests and
  `scripts/generate --check`; `scripts/prepush` before every push.
- One `scripts/gate-dev --pr 775` at the end, on the exact head.

## Known base defects

- WebKit cannot launch on gate machines (A Torre: 48 of 50 failures on PR #724 on 28/10 came from webkit-mobile-390
  `browserType.launch`, not from the PR). Owner: the environment, not this unit.
- `.gate/records` is absent in a fresh container, so the first gate here runs every stage it selects.
- `prepush` judges the working tree, not the pushed commit: a sub-agent's untracked files refuse the coordinator's push.
  Owner: engine-push-guard.

## Cheapest useful effort

Action: one census of 1017 rows built by one deterministic script over the committed tree, cut into 16 groups by one domain map, 16 briefs generated from one template, and a rule register with its command and 28 tests, closed by one `scripts/gate-dev --pr 775`.
Cost: about 120 minutes of one coordinator session and three sub-agents (rule-system builder; census rows for refusals and resources; stop counts from PR history, about 66 read-only GitHub searches), and one gate run.
Requirement: Daniel and A Torre need every rule, requirement and resource use counted with its owner, review date and stops, cut into groups that each fit one audit session, and a register where the next rule cannot live without its justification; A Torre launches the 16 audits from the briefs.
Cheaper rejected: auditing the rules one at a time without a census (nothing would prove the groups complete and disjoint); writing the 16 briefs by hand (they drift apart; one template and a generator keep one shape); refusing incomplete rules at once (47 stopping functions have no record, so refusing would stop every PR, the failure this program exists to end).
