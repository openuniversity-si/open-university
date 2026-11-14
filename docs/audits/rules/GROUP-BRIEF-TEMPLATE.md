# Group audit brief template (RULE-AUDIT phase 1)

Every group brief in `docs/audits/rules/briefs/<group-id>.txt` is this template with the `{placeholders}` filled from
`docs/audits/rules/groups.json` and `docs/audits/rules/census.json`. The brief is the unit-specific part; A Torre
appends the standing generic rules at launch, and this brief wins where they conflict. Do not edit a generated brief by
hand: change this template or the group, then regenerate.

The template starts at the next line and ends at the end of this file.

---
RULE-AUDIT-{GROUP_ID_UPPER}: audit every rule of the group "{title}" (program RULE-AUDIT, phase 1; brief written by
RULE-AUDIT phase 0, PR #775)
Repo openuniversity-si/open-university. Base mod/roadmap-integration (gate your own head; never merge or rebase the base into your
branch). Branch mod/rule-audit-{group_id}. One draft PR from mod/rule-audit-{group_id} into mod/roadmap-integration.
Approved: Daniel 28/10 16:43-16:55 under A Torre's execution. Decisions: D-069 item 9 (fix the class), D-072 (a block
enters an evaluation before any action).

STEP 0 (before anything else, within about 3 minutes): create the branch from the current base tip, commit and push
docs/units/RULE-AUDIT-{GROUP_ID_UPPER}/audit.md as a skeleton, open the draft PR through the REST API (title
"RULE-AUDIT-{GROUP_ID_UPPER}: {title}", body with the 3-8 item commit plan and the trailers "Decision: D-069 item 9,
D-072", "Premises: none", "Fit-Review: not reviewed (Daniel 2026-10-25: no review step)"), post a STATUS comment. Only
then start the audit.

== WHY ==
Daniel's order, 16:46 and 16:47 BRT 28/10, in his words: "toda regra, requisito, uso de recursos etc merece uma
justificativa - e uma muito boa - para continuar, juntamente com uma pequena simulacao do impacto, tanto positivo
quanto negativo, de retira-la. Ou seja, praticamente uma auditoria completa em cada uma delas" and "peca para que uma
avaliacao inicial agrupe os requisitos, e lance uma auditoria propria para cada grupo. Vamos investir recursos nisso."
He decided that every rule, requirement and resource use must earn its place with a strong justification and a small
simulation of the impact of removing it, and that each group of them gets an audit session of its own. This session is
the audit of one group. Phase 2 acts on the verdicts; this session changes no behaviour.

What the rows of this group have in common: {common}

== YOUR ROWS (exactly these {row_count}; census at PR #775, docs/audits/rules/census.json) ==
{row_lines}

Kinds: {kind_counts}. Estimated work: {estimate_min} minutes (model in docs/audits/rules/groups.json).

== THE QUESTIONS (Q0 and the five questions; answer all of them for every row, verbatim) ==
Daniel, 17:08 BRT 28/10: every stop of the flow is an accident. He decided that any question that leads to a stop of
the flow, however small, must itself be questioned, the way Tesla treats an accident in one of its vehicles: it
becomes a case with a mandatory root cause, never a statistic to be accepted.
(Q0) Does this rule/requirement/check ever cause a STOP of the flow? If yes, the audit cannot end in KEEP without a named root cause, the cheapest fix that removes the stop, and the number of times it already stopped the flow.
(Q1) What is the justification for this to continue existing? Name who asked for it and the day, or say plainly that nobody is named — that is a finding, not a failure.
(Q2) What is the damage if it is removed?
(Q3) What is the impact, POSITIVE and NEGATIVE, of removing it — a small simulation, with numbers read from evidence (log lines, gate records, PR history, config reads), never an opinion. Count how often it fired, what it blocked, and what it would have let through: if that cannot be measured from the evidence, say so and say what would be needed to measure it.
(Q4) Does it need to STOP anyone, or is a printed number enough?
(Q5) Verdict: KEEP (with the justification), WARN (measure and print, never refuse), or DELETE (nothing measures it and the guarantee exists elsewhere).

== THE IMPACT SIMULATION (Q3) ==
For each row, read the evidence before you write a number:
- Gate records: .gate/records/reports/<sha>/<mode>-<ts>/ on the box (gitignored; absent in a fresh cloud container,
  say so when you cannot read them) and the one-line gate comments on PRs (REST: GET
  repos/openuniversity-si/open-university/issues/<n>/comments).
- PR history: PRs whose gate or structure check named this row (REST search; count them, quote two).
- Git history: `git log --oneline --grep '<id or name>'` and the commits that introduced the row (`git log -S`).
- Config reads: every reader of a parameter (`x-readers`, then `rg -n '<key>'`), and what the reader does with it.
- Premises: `scripts/premises list` and the premise record each row rests on (status, `at`, dependents).
- Stops of the flow (Q0): count every way the row stopped a unit: refusals, "conflicting" and "blocked" verdicts,
  "busy", "held", gate reds. A report that says a unit cannot proceed is a stop, so it needs a cause, not a status
  word. The census carries what PR history already shows (`stops_flow` on each row, GitHub issue search over PR
  text and comments); confirm it and add what the gate records show.
Write, per row: fired N times (source), blocked N PRs (source), would have let through N (source), or "not measurable
from the evidence: needs <what>". A row that can stop the flow and has never been measured is a finding by itself.
Never type a number you did not read or count.

== OUTPUT ==
1. docs/audits/rules/{group_id}.md: one table row per census row, columns: id | Q0 stops the flow (times, source;
   root cause; cheapest fix) | Q1 justification (who, day) | Q2 damage if removed | Q3 impact +/- with numbers and
   source | Q4 stop or print | Q5 verdict. At the end, the counts of the verdicts (KEEP n, WARN n, DELETE n; total
   equals {row_count}), the list of findings "nobody is named" and the list "stops the flow, never measured".
2. docs/audits/rules/{group_id}.json: the same verdicts as data for phase 2, one object per row: {{"id", "verdict",
   "justification", "owner", "created": {{"on", "by"}}, "damage_if_removed", "impact_of_removal": {{"positive",
   "negative", "measured"}}, "stops" (true only for KEEP rows that must stop), "stop_record": {{"count", "source",
   "measured_on", "root_cause", "cheapest_fix"}}, "ends_when", "premises": [P-NN, ...], "evidence": [...]}}. Phase 2 turns the KEEP and WARN rows into records of config/registry/rules.json (see
   docs/audits/rules/SYSTEM.md); an empty premises list is itself a finding.
3. docs/units/RULE-AUDIT-{GROUP_ID_UPPER}/audit.md, plan.md and retro.md.

== ACCEPTANCE (quote each with evidence in the PR) ==
* docs/audits/rules/{group_id}.md has exactly {row_count} rows, one per census row of this group, and the verdict
  counts sum to {row_count} (quote the command that counts them).
* docs/audits/rules/{group_id}.json parses and has the same {row_count} ids.
* Every Q3 cell carries a number with its source, or says what is not measurable and what would measure it.
* Every row with nobody named is listed as a finding.
* No row that stops the flow (Q0 yes) ends in KEEP without a named root cause, the cheapest fix that removes the stop
  and the number of times it already stopped the flow.
* Every document is in English; Daniel's own words keep their Portuguese inside quotes with an English sentence.
* scripts/gate-dev --pr <n> on the exact head, stage count and verdict line quoted.
* MERGE-READY <full sha> posted, PR out of draft in the same turn; you did not merge.

== HARD RULES ==
* NEVER MERGE this PR. When gate-green: mark it ready (out of draft), post "MERGE-READY <full sha>" and a STATUS
  "gated, waiting for the coordinator/train", end the turn.
* One branch, one PR. Do NOT launch any session.
* Files you may touch: docs/audits/rules/{group_id}.md, docs/audits/rules/{group_id}.json and
  docs/units/RULE-AUDIT-{GROUP_ID_UPPER}/**. Change no code, config, contract, registry or premise record: you measure
  and judge, phase 2 changes behaviour. A wrong or missing census row goes into a "census corrections" section of
  your report, never into census.json.
* Production frozen (D-054); no GitHub Actions; no pings, no comments on other PRs; never print secrets.
* TARGETED TESTS ONLY while working; the full scripts/gate-dev --pr <n> ONCE at the end.
* Commit and push every 3-4 minutes with a Plan: N trailer and "Decision: D-069".

== COLLISIONS ==
* PR #775 (RULE-AUDIT phase 0, branch mod/rule-audit) owns docs/audits/rules/README.md, census.json, groups.json,
  GROUP-BRIEF-TEMPLATE.md, SYSTEM.md, briefs/** and the rule system (scripts/rule, scripts/lib/rule_registry.py,
  config/registry/rules.json): do not edit them.
* Every other group's branch owns only its own two output files and its own docs/units directory:
{other_branches}

== TARGET TIME ==
{estimate_min} minutes of audit work; one session of 60 to 90 minutes including the gate. If the rows cannot be
finished in time, commit what is done, list the rows left in the PR and in the retro, and say why.

== FINAL OUTPUT ==
Print: PR number and URL, branch, final head sha, gate verdict with numbers, the verdict counts (KEEP, WARN, DELETE),
the rows with nobody named, and the three rows whose removal unblocks the most work.
