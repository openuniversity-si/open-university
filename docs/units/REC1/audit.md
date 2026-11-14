# REC-1 audit

Base tip d6021680 (2026-10-28). Evidence read from the code, no suite run.

- `forge_events.subject(repo, pr, sha, premises, unit=None)`: `unit` defaults None. `pr_ready.emit_ready` calls it without a unit; `train_queue.entry` reads `payload['unit']` from `pr.ready`, and `Train.subject(entry)` already forwards `entry.unit`. So one source fixes both: `pr.ready` carries the unit, the train copies it to `pr.merged`.
- `ForgeEvents.publish` derives the channel from `payload.pr`, so `pr.merged` (pr=N) lands only on the PR channel; `train.batch.green` has pr=None and lands on the repository channel. Nothing writes `pr.merged` to the repository channel (slo and program read it there).
- `program.fold` matches `payload['unit']` to the lower-case program unit id and reads `payload['pr']`; the event shape needs no change.
- Unit lookup rules already exist: `train_ownership.UnitOwnership.manifests(commit)` and `gate_areas.glob_match`. `lane_of` is the same pair with lanes; `unit_of` is the same with ids.
- Cited sources verified: forge_events.py, pr_ready.py, train.py, train_ownership.py, EVENTS.md exist on the base.
- No new switch needed; the change is always on.
