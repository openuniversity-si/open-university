# Program fluxo-amplo: brief

## Complaint
The flow of A Torre produces integrated commits too slowly, and the lanes wait on a gate that takes far longer than the regime of
exception allows. The program's main metric is counted integrated commits per hour, summed over lanes (D-137, `scripts/flow-metrics`).

## Symptom
The gate on the e2-micro takes far more than 10 s (Daniel's exit criterion, D-155); the lanes sit idle in the meantime.

## Evidence
`docs/programs/fluxo-amplo/avaliacao.md` (the assessment), `diagnostico.md` (the causes), `solucao.md` (the redesign). Base real gate:
152 s cold, 10 s warm (db422dcd, D-191). Pace: 36 to 38 counted commits an hour over three hours (`scripts/lane-status`).

## Measurable goal
Counted commits per hour, steered by the hourly pace per lane (D-156): 500 a day is 20.8 an hour, 1,000 is 41.7. The program gate
measures `prs_merged_per_hour` (goal 7) until the coordinator counts commits from git.
