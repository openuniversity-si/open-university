# RULE-AUDIT audit (read-only; evidence from `mod/roadmap-integration` at 5a753035)

Unit: RULE-AUDIT phase 0. The census of every rule, requirement and resource use as data, the cut into groups, one
launchable audit brief per group; extended by Daniel at 16:52 BRT 28/10 (build the rule system that owns the rules)
and 16:55 BRT (the rule system also owns the premises). Decisions: D-069 item 9, D-072, D-025.

## Cited sources (brief standard v2 item 2)

1. `/workspace` does not exist in this cloud container (`ls /workspace`: no such file or directory). So
   `/workspace/torre/motor/v3/backlog/regras-que-param.md`, `/workspace/torre/motor/v3/rules/commitment.md`,
   `rules/language.md` and the queue `/workspace/torre/motor/v3/queue/rule-groups/` are not readable here.
   Decision: the briefs are committed to `docs/audits/rules/briefs/<group-id>.txt` and also written to the queue
   path in this container; A Torre copies the committed files to the box queue.
2. `tools/language-check.py` does not exist in the repository (`ls tools`: no such directory). Every file of this unit
   is in English; a local equivalent check is run and quoted in the PR.
3. D-025 (row 37), D-054 (row 56), D-065 (row 67), D-069 (row 71), D-072 (row 74) and D-073 (row 75) exist in
   `docs/domain/DECISIONS.md`.
4. The premise register exists and the rule system builds on it: `docs/process/premises/*.yml`, schema
   `contracts/premises/premise.v1.json`, reader `scripts/lib/premises.py` (`load`, `record_errors`, `recorded`,
   `write_record`), writer `scripts/premises`.

## Counts (each with its command)

| Kind | Count | Command |
|---|---|---|
| Registry parameters | 792 in 60 files | `python3` over `config/registry/*.json`, `len(properties)` summed |
| ... with `x-source` | 304 | same pass, `'x-source' in parameter` |
| ... with a review date | 0 | same pass; the attribute keys present are type, default, x-unit, description, x-readers, x-source, minimum, items, minLength, minItems, uniqueItems, maximum, x-flag, pattern, enum, exclusiveMinimum, deprecated, format, additionalProperties, x-literal-names, propertyNames, required, x-text, x-text-context, maxItems: none is a date |
| Decisions | 63 | `grep -cE '^\| *D-[0-9]{3} ' docs/domain/DECISIONS.md` |
| ... with a review date | 0 | the table header is `Id, Date, Decision, Invariant, Proof (test), Status`: no review column |
| Refusal functions, brief's pattern | 37 in 20 modules | `grep -hE '^\s*def [a-z_]*errors[a-z_]*\(' scripts/lib/*.py \| wc -l` (the brief said 38; #774 measured the same 37) |
| Refusal functions, census pattern | 47 in 28 modules | `grep -hE '^\s*def ([a-z_]*(errors\|refus\|reject\|block)[a-z_]*)\(' scripts/lib/*.py \| wc -l`; adds the refusals not named `errors` (`refuse_frozen`, `refuse_merge`, `refusal`, `refuse_production`, `prod_refusal`, `refusals`, `refused`, `merge_block`, `plan_block`, `blocked`) |
| Premises | 53 | `ls docs/process/premises/*.yml \| wc -l` |

## Evidence of firing

- `.gate/records` (the gate's reports) is gitignored and absent in this container (`ls .gate`: no such file); it lives
  on the box. So "fired" is a proxy here: commits whose message names the item and retros that name it (135
  `docs/units/*/retro.md` files). The only real firing counts available are A Torre's measurement of 28/10 quoted in the
  brief: lane ownership 6, plan completeness 5, missing gate stage 2, staleness 1; none for an irreversible risk.
- A Torre's measurement of 28/10 16:56 on the premises: 28 confirmed, 16 inferred, 5 to-validate, 3 validated,
  1 refuted (P-00); 35 of 53 carry `at: null`.

## Collisions

- #772 (COMMIT-STEP) and #773 (BODY-GATE) touch `scripts/lib` and `config/registry`; this PR adds new files only
  (`scripts/lib/rule_registry.py`, `config/registry/rules.json`) and edits none of theirs.
- #774 (RULE-MASS, draft) edits `contracts/config/registry.v1.json`, `scripts/lib/structure.py`,
  `units/engine-structure/unit.json`, `scripts/tests/test_config_check.py`, `scripts/tests/covers/structure-check.json`
  and adds `scripts/lib/rule_audit.py`, `docs/units/RULE-MASS/**`. It does not touch `docs/audits/rules/README.md`.
  This PR edits none of those files; the program supersedes #774, which must rebase onto it.

## What already exists that this unit could duplicate

- #774 annotates registry parameters with `x-stops`, `x-damage-if-passed`, `x-irreversible`, `x-ends-when` and counts
  them in `structure-check`. The rule system here keeps rules as records (a rule is often a function or a decision,
  not one parameter) and reads parameters by reference, so the two do not write the same field.
- The premise register (D-066) already carries statement, status, radius, blast and the date of each assumption; the
  rule system cites premise ids and reads that register, it does not copy it.
