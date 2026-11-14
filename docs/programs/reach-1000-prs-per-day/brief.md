# Program reach-1000-prs-per-day: brief

## Complaint
A Torre (a chat assistant plus a PR-event routine reading `v3/queue.json` by hand) coordinates about 130 units. It does not
scale to 1,000+ PRs a day (Daniel, 26-27/10/2026).

## Symptom
Coordination is manual: launches, blocks, fix units and merges wait on one assistant reading a file.

## Evidence
Roughly 130 units coordinated by hand in the last cycle; the merge, gate, defect and lesson loops each needed a person or a chat turn.

## Measurable goal
`prs_merged_per_day` >= 1000, measured by `scripts/lib/program_gate.py` from `pr.merged` events of the repository.
