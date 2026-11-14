# LP7 audit (read-only findings)

- `premises.py` `emit` printed `event: {...}`; callers: `propose`, `answer`, `blast` (only `main` and `test_premises.py`).
- `premise.{proposed,confirmed,refuted,blast}.v1` are in `forge-events.subject_exempt_schemas`: they carry no repo/pr, so
  `ForgeEvents.emit/publish` refuses them (`event_contracts.validate`). Publishing needs a thin adapter in `premises.py`
  that appends the already-validated envelope to the repository channel (`Channel(repo, None)`), idempotent by event_id.
  CANDIDATE for GX-37: premise.*.v2 with a subject, then the adapter goes away (expand->contract, D-029).
- `lessons.apply` already does proposed>applied with an audit line (audit_chain) and `lesson.applied` through the port;
  `lessons.brief_statuses` = applied and `lessons_brief.for_area` already feeds `coordinator_launch`'s lessons port.
  Missing for the planner: a call keyed by a plan decision (no PR), idempotent, refusing retired lessons by name, and a
  one-call "lines for the next brief" that reads the register.
- No new registry key is needed: the dry-run switch is the `--no-emit` flag (same as lessons), the adapter and repo come
  from `forge-events.adapter` / `forge-events.repo`.
