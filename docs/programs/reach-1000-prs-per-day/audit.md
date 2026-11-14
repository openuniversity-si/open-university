# Program reach-1000-prs-per-day: audit

Seeded retroactively on 2026-10-27 from the unit list of the program brief; `v3/queue.json` was not in the repository,
so `scripts/program migrate-queue` reads it when an operator has it.

| Area | Evidence | Consequence for the plan |
|---|---|---|
| Events | `scripts/lib/forge_events.py`, `contracts/events/*.v1.json` | Status and decisions are folds of the log, no second store. |
| Merge | `scripts/lib/train.py` (TR1) | The coordinator enqueues through the train's own predicate. |
| Defects | `scripts/lib/defect_router.py` (KD1) | Known defects become fix units through the router. |
| Gate | `gate_select.py` (GS1), `gate_status.py` (GV1) | Used through their CLIs. |
| Lessons | LR1 | Lessons enter briefs through a port. |
