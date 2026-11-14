# LP4 audit — triage and the pass-on interface

Base `3c834942` (LP2 #701). Read-only evidence; no suites run.

## What exists (verified on the base)
- `scripts/lib/plan_triage.py`: LP2 stub, every body `NotImplementedError('LP4')`; `scripts/plan` execs it.
- Contracts (read-only, GX-37/LP2): `contracts/events/plan.{note,input,candidate}.v1.json`. `plan.candidate` natural
  key is (repo, program, signature): the port gives one event id per signature, so a re-published sighting update is a
  no-op. Triage therefore publishes a signature once, at promotion; the printed output carries current counts.
- Registry: `config/registry/planner.json` has `planner.triage_promote_sightings` (2) and `planner.overrun_factor` (2.0),
  both listing `scripts/lib/plan_triage.py` as reader. No new key is needed.
- Port: `forge_events.ForgeEvents(adapter, clock, producer, correlation_id)`, `emit`, `read`; `FileAdapter(dir)` for a
  temp store. `program.load`, `program.status`, `program.live_events` give the graph, unit stages and the program's
  channels.
- Inputs: `gate.failed` v3 carries `stages[].class` and `failing_tests[{id, stage, signature}]` (signature already
  normalized by `gate_failures.normalize`); `lesson.recorded` (class, source_unit); `premise.confirmed/refuted` (id;
  refuted has `dependents`); `defect.*` (defect, test, area); `work.assigned` (units, occurred_at).

## Gaps and how LP4 works around them (in its own files)
- `program.v1` units have no `estimate` field; `plan.changed` has a `set_estimate` op whose folded field is LP3's.
  Overrun reads a unit's `estimate` in minutes when the (folded) plan has one, else reports no overrun. CANDIDATE.
- `program.v1` units carry no premises: units citing a premise come from the `premises` of their events.
- Event `unit` is the lower-case program unit id (`program.unit_event_id`).
- 27/10's raw `gate.failed` envelopes are not in the repo; the replay fixture reconstructs L1, L2, L5, L6 inline from
  `docs/programs/live-planning/audit.md` (PRs, times, error strings).

## Collisions
None: LP4 owns `scripts/lib/plan_triage.py`, `scripts/plan`, `scripts/tests/test_plan_triage.py` (claimed by
`units/engine-coordinator/unit.json`). Python test discovery runs the new test; no sidecar needed.
