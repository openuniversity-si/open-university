# Program <program>: plan

## Alternativas
<!-- Padrão v7 (D-081): for each structural root of audit.md's `## Causas raiz`, a `### R<n>` with 2-4 alternatives `| A<k> <option> | remendo / corrige a classe / redesenho | resolve a raiz? | custo | reversibilidade | risco | degrau |` (template docs/process/templates/plan.md). -->

## Escolha
<!-- `- R<n> → A<k>: <justification>`; a remendo also names `Follow-up:`. -->

## Units

The PR graph is data (contracts/programs/program.v1.json). Status is never written here: `scripts/program status <program>`
folds it from events.

```json program.v1
{
  "contract": "program.v1",
  "program": "<program>",
  "complaint": {
    "symptom": "what is observed",
    "evidence": "where it is shown",
    "goal": {"metric": "prs_merged_per_day", "comparator": "gte", "target": 1, "unit": "prs/day"}
  },
  "units": [
    {"id": "A1", "depends_on": [], "owner": "lane", "model": "model", "wave": 1, "done": ["the unit's done criteria"]}
  ]
}
```
