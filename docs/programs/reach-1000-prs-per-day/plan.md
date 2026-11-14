# Program reach-1000-prs-per-day: plan

The PR graph is data (contracts/programs/program.v1.json). Status is never written here: `scripts/program status
reach-1000-prs-per-day` folds it from events. The `pr` field only names a unit's PR once known.

```json program.v1
{
  "contract": "program.v1",
  "program": "reach-1000-prs-per-day",
  "complaint": {
    "symptom": "coordination by one chat assistant reading a queue file by hand",
    "evidence": "about 130 units coordinated by hand; does not scale to 1,000+ PRs a day",
    "goal": {"metric": "prs_merged_per_day", "comparator": "gte", "target": 1000, "unit": "prs/day"}
  },
  "units": [
    {"id": "X1", "title": "execution foundation", "depends_on": [], "owner": "engine", "model": "claude-sonnet-5-5", "wave": 1, "done": ["merged to mod/roadmap-integration with gate-dev green"]},
    {"id": "TI1", "title": "test isolation", "depends_on": [], "owner": "engine", "model": "claude-sonnet-5-5", "wave": 1, "done": ["merged with gate-dev green"]},
    {"id": "GD1", "title": "gate decomposition", "depends_on": [], "owner": "engine", "model": "claude-sonnet-5-5", "wave": 1, "done": ["merged with gate-dev green"]},
    {"id": "PD1", "title": "premises and defects base", "depends_on": [], "owner": "engine", "model": "claude-sonnet-5-5", "wave": 1, "done": ["merged with gate-dev green"]},
    {"id": "GS1", "title": "selective gate", "depends_on": ["GD1", "TI1"], "owner": "engine", "model": "claude-sonnet-5-5", "wave": 2, "done": ["merged with gate-dev green", "per-test cache reuses unaffected tests"]},
    {"id": "TR1", "title": "merge train", "depends_on": ["X1"], "owner": "engine", "model": "claude-sonnet-5-5", "wave": 2, "done": ["merged with gate-dev green", "train queue_entry predicate on pr.ready"]},
    {"id": "KD1", "title": "known defects and router", "depends_on": ["PD1"], "owner": "engine", "model": "claude-sonnet-5-5", "wave": 2, "done": ["merged with gate-dev green", "defect_router.route emits work.assigned"]},
    {"id": "GV1", "title": "gate status comment", "depends_on": ["GS1"], "owner": "engine", "model": "claude-sonnet-5-5", "wave": 3, "pr": 574, "done": ["merged with gate-dev green", "one live status comment per head"]},
    {"id": "LR1", "title": "lessons registry", "depends_on": ["KD1"], "owner": "engine", "model": "claude-sonnet-5-5", "wave": 3, "pr": 575, "done": ["merged with gate-dev green", "lessons for-area and aggregator"]},
    {"id": "CO1", "title": "program coordinator", "depends_on": ["KD1", "GS1", "GV1", "TR1", "LR1"], "owner": "engine", "model": "claude-sonnet-5-5", "wave": 4, "pr": 576, "done": ["merged with gate-dev green", "coordinator next() decides from events", "program gate measures the goal"]},
    {"id": "U3b", "title": "roadmap wave U3b", "depends_on": ["CO1"], "owner": "engine", "model": "claude-sonnet-5-5", "wave": 5, "done": ["merged with gate-dev green"]},
    {"id": "U4", "title": "roadmap wave U4", "depends_on": ["U3b"], "owner": "engine", "model": "claude-sonnet-5-5", "wave": 6, "done": ["merged with gate-dev green"]}
  ]
}
```
