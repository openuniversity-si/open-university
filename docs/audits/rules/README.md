# RULE-AUDIT: every rule, requirement and resource use gets an audit of its own

Unit: RULE-AUDIT phase 0 (PR #775, branch `mod/rule-audit` into `mod/roadmap-integration`). Decisions: D-069 item 9,
D-072, D-025.

## What the program is

Daniel's order, 16:46 and 16:47 BRT 28/10, in his words: "toda regra, requisito, uso de recursos etc merece uma
justificativa - e uma muito boa - para continuar, juntamente com uma pequena simulacao do impacto, tanto positivo
quanto negativo, de retira-la. Ou seja, praticamente uma auditoria completa em cada uma delas" and "peca para que uma
avaliacao inicial agrupe os requisitos, e lance uma auditoria propria para cada grupo. Vamos investir recursos nisso."
He decided that every rule, requirement and resource use must earn its place with a strong justification and a small
simulation of the positive and negative impact of removing it, and that an initial evaluation groups them so each
group gets an audit session of its own.

He added four orders the same afternoon, all part of this program:

- 16:52: build the parts of the engine that own the rules from now on: a registry where no rule exists without a
  justification, an owner, a review date, an end condition and an impact statement ([SYSTEM.md](SYSTEM.md)).
- 16:55: the rule system also owns the premises: every rule cites the premises it rests on, read from the premise
  register (D-066), and a rule resting on a refuted or unvalidated premise shows up as a row.
- 17:08: every stop of the flow is an accident: a case with a root cause, never a statistic. Every audit answers Q0
  before the five questions, and the census counts how often each rule stopped the flow.
- 17:09: questioning is always on: every rule carries a standing question that must be answerable at any time.

The program runs in three phases:

- Phase 0 (this unit): the census of every auditable thing as data, the cut into groups, one launchable brief per
  group, and the rule system. Phase 0 audits nothing and changes the behaviour of no existing rule.
- Phase 1: one audit session per group, launched by A Torre from the briefs. Each answers Q0 and the five questions
  for every row of its group and writes `docs/audits/rules/<group-id>.md` (the table) and `<group-id>.json` (the same
  verdicts as data).
- Phase 2: acts on the verdicts (below).

## Files

| File | What it is |
|---|---|
| [census.json](census.json) | One row per auditable thing: id, kind, where, what, what it stops or spends, owner, review date, firing evidence, Q0 (`can_stop`, `stops_flow`) and the standing `question`. |
| [groups.json](groups.json) | The cut: every census row in exactly one group, with its ids, what the rows have in common, the estimated minutes and the run order. |
| [GROUP-BRIEF-TEMPLATE.md](GROUP-BRIEF-TEMPLATE.md) | The one shape of every phase 1 brief, with Q0 and the five questions verbatim. |
| [briefs/](briefs/) | One launchable brief per group, generated from the template (A Torre copies them to `/workspace/torre/motor/v3/queue/rule-groups/`). |
| [SYSTEM.md](SYSTEM.md) | The rule system: the registry of rules, its checks, its lifecycle and `scripts/rule`. |

## How the census was measured

Every count below was produced by the command next to it, on the committed tree named in `census.json`
(`measured_at_commit`); `census.json` › `measurements` carries each command with its result.

<!-- measurements:start -->
| Count | Result | Command |
|---|---|---|
| registry parameters (properties of every config/registry/*.json) | 799 | `python3 -c "import json,glob; print(sum(len(json.load(open(f))['properties']) for f in glob.glob('config/registry/*.json')))"` |
| registry parameters carrying x-source | 311 | `python3 -c "import json,glob; print(sum('x-source' in v for f in glob.glob('config/registry/*.json') for v in json.load(open(f))['properties'].values()))"` |
| registry files | 61 | `ls config/registry/*.json \| wc -l` |
| decision rows of the register | 63 | `grep -cE '^\\| *D-[0-9]{3} ' docs/domain/DECISIONS.md` |
| refusal functions, the brief's pattern (names containing errors) | 37 | `grep -hE '^\s*def [a-z_]*errors[a-z_]*\(' scripts/lib/*.py \| wc -l` |
| refusal functions, the census pattern (errors, refus, reject, block) | 48 | `grep -hE '^\s*def ([a-z_]*(errors\|refus\|reject\|block)[a-z_]*)\(' scripts/lib/*.py \| wc -l` |
| modules holding a census-pattern refusal function | 29 | `grep -lE '^\s*def ([a-z_]*(errors\|refus\|reject\|block)[a-z_]*)\(' scripts/lib/*.py \| wc -l` |
| premise records | 53 | `ls docs/process/premises/*.yml \| wc -l` |
| premise records with no date (source.at null) | 35 | `python3 -c "import sys; sys.path.insert(0,'scripts/lib'); import premises; print(sum((r.get('source') or {}).get('at') is None for r in premises.load()[0].values()))"` |
| scheduled tasks of this account (claude.ai) | 0 | `claude-code-remote list_triggers (read-only MCP call) 28/10: {"data": [], "has_more": false}` |
| routines, daemons and paid or metered calls found in the repository | 54 | `see resource_commands` |

Census rows: 1017 (parameter 799, decision 63, premise 53, refusal 48, routine 22, resource 32); command: `python3 -c "import json; d=json.load(open('docs/audits/rules/census.json')); print(len(d['rows']))"`.
Rows that can stop the flow: 119 (refusals with a measured stop count 41, never measured 7; limits and switches read by a refusal 71); rows whose Q0 the group audit answers: 170.
<!-- measurements:end -->

What could not be measured here, said plainly:

- Real firing counts. The gate records (`.gate/records`) are gitignored and live on the box, not in a cloud
  container. `fired` is therefore a proxy (commits and retros that name the row), and `stops_flow` is read from PR
  history (GitHub issue search over PR text and comments for each refusal's message). The only real counts of 28/10
  are A Torre's, quoted in the census: lane ownership 6, plan completeness 5, missing gate stage 2, staleness 1.
- The daemons of the box (train-loop, guard, vigia, watchers) and the bot's own scheduled routines, beyond what the
  repository shows: `/workspace` does not exist in this container. They are rows marked `box only`, and the group
  that owns them reads them on the box.
- The parameter classes `stops`, `spends` and `configures` are a heuristic (a limit or switch read by a module that
  refuses, a time or size unit, anything else); Q0 of each group audit confirms or corrects them.

## The groups

<!-- groups:start -->
| Run order | Group | Rows | Kinds | Estimated minutes | PRs stopped (measured) | Rows that can stop | Brief |
|---|---|---|---|---|---|---|---|
| 1 | `structure-check-and-premises`: Structure check, lanes, review trailer and the premise register | 64 | decision 8, parameter 46, premise 5, refusal 5 | 82 | 11 | 20 | [structure-check-and-premises.txt](briefs/structure-check-and-premises.txt) |
| 2 | `commit-and-pr-discipline`: Commit, push and PR body discipline | 59 | decision 3, parameter 48, refusal 8 | 75 | 10 | 8 | [commit-and-pr-discipline.txt](briefs/commit-and-pr-discipline.txt) |
| 3 | `registry-literals-and-text`: Configuration registry, literals, generated code and text | 61 | decision 4, parameter 49, premise 1, refusal 7 | 72 | 2 | 16 | [registry-literals-and-text.txt](briefs/registry-literals-and-text.txt) |
| 4 | `environment-toolchain-and-supply-chain`: Machine environment, toolchain and supply chain | 69 | decision 2, parameter 55, premise 2, refusal 10 | 86 | 2 | 13 | [environment-toolchain-and-supply-chain.txt](briefs/environment-toolchain-and-supply-chain.txt) |
| 5 | `production-release-and-migrations`: Production freeze, release policy and database migrations | 41 | decision 6, parameter 28, premise 1, refusal 6 | 72 | 2 | 9 | [production-release-and-migrations.txt](briefs/production-release-and-migrations.txt) |
| 6 | `planning-events-and-launch`: Planning, the event contract and session launch | 99 | decision 2, parameter 84, premise 11, refusal 2 | 80 | 2 | 2 | [planning-events-and-launch.txt](briefs/planning-events-and-launch.txt) |
| 7 | `merge-train-and-delivery`: Merge train, merge rule and the delivery tail | 89 | decision 2, parameter 79, premise 6, refusal 2 | 84 | 1 | 4 | [merge-train-and-delivery.txt](briefs/merge-train-and-delivery.txt) |
| 8 | `defects-lessons-and-postmortems`: Known defects, lessons and postmortems | 101 | decision 1, parameter 95, premise 1, refusal 4 | 81 | 0 | 21 | [defects-lessons-and-postmortems.txt](briefs/defects-lessons-and-postmortems.txt) |
| 9 | `performance-budgets-and-slo`: Performance budgets, visual capture and SLOs | 64 | decision 1, parameter 61, refusal 2 | 62 | 0 | 11 | [performance-budgets-and-slo.txt](briefs/performance-budgets-and-slo.txt) |
| 10 | `github-calls-and-rate-budget`: GitHub calls and the rate budget | 50 | decision 1, parameter 31, premise 3, refusal 1, resource 14 | 71 | 0 | 9 | [github-calls-and-rate-budget.txt](briefs/github-calls-and-rate-budget.txt) |
| 11 | `code-architecture-and-units`: Code architecture, contexts and units | 61 | decision 8, parameter 42, premise 11 | 70 | 0 | 3 | [code-architecture-and-units.txt](briefs/code-architecture-and-units.txt) |
| 12 | `gate-selection-proof-and-status`: Gate selection, proof reuse and status | 96 | decision 2, parameter 87, premise 6, refusal 1 | 81 | 0 | 2 | [gate-selection-proof-and-status.txt](briefs/gate-selection-proof-and-status.txt) |
| 13 | `gate-execution-and-tests`: Gate execution, test isolation and quarantine | 84 | decision 1, parameter 81, premise 2 | 62 | 0 | 1 | [gate-execution-and-tests.txt](briefs/gate-execution-and-tests.txt) |
| 14 | `paid-vendors-and-ai-sessions`: Paid vendors, AI sessions and the free-tier caps | 35 | decision 1, parameter 13, premise 3, resource 18 | 62 | 0 | 0 | [paid-vendors-and-ai-sessions.txt](briefs/paid-vendors-and-ai-sessions.txt) |
| 15 | `routines-and-daemons`: Routines, hooks and daemons that run without a person | 22 | routine 22 | 81 | 0 | 0 | [routines-and-daemons.txt](briefs/routines-and-daemons.txt) |
| 16 | `product-domain-rules`: Product and catalog domain rules | 22 | decision 21, premise 1 | 69 | 0 | 0 | [product-domain-rules.txt](briefs/product-domain-rules.txt) |

16 groups; grouped rows 1017 = census rows 1017; every row is in exactly one group (`groups.json` › `count_command`).
<!-- groups:end -->

## The order the audits run in

Largest expected unblock first: a group whose rules stopped the most PRs runs first, because its verdicts free the
most work. The order is computed in `groups.json` (`run_order`) from the census: the PRs each group's refusals stopped
(`stops_flow`, PR history) and the rows that can stop the flow; groups whose rules stop no queue (product rules,
architecture, budgets) run last. A Torre may launch several groups at once: no two groups share an output file.

## What phase 2 does with the verdicts

1. Reads every `docs/audits/rules/<group-id>.json` (one object per census row with its verdict and evidence).
2. KEEP and WARN rows become records of `config/registry/rules.json` with every field the rule system requires:
   statement, owner, created, review_by, ends_when, stops, damage_if_passed, impact_of_removal, premises, the stop
   record and the standing question with the audit's answer. `scripts/rule check` then reports the remaining gaps as
   numbers.
3. WARN rows that refuse today are converted to measure-and-print, each in a PR of the owner of its file, citing the
   verdict.
4. DELETE rows are removed in a PR of the owner of their file, with a decision id; a rule is retired through
   `config/registry/rules.json` (status `retired`, the decision id), never by an ad-hoc edit.
5. Every row whose Q0 answer is yes carries its root cause and the cheapest fix that removes the stop; the fixes are
   queued as units of their owners.
6. `scripts/rule check --mode refuse` is switched on only by an approved decision, after the unregistered stops reach
   zero.
