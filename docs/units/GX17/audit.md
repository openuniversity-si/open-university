# GX-17 audit — our own `tower/gate` commit status

Base `4bc4dd04` (mod/roadmap-integration). Cheap evidence only; nothing run.

## What exists
- `scripts/lib/gate_status.py` (GV1): one PR comment per head+mode, edited in place through `Publisher` -> `ForgeEvents.upsert_comment` -> `GitHubAdapter.upsert_comment`. Hooks: `begin` (gate-local:240,334), `stage-start/end` (gate-runner.sh:9-25), `final_from_report` (called by `gate_report.publish_status`, gate_report.py:185-190, passes the verdict envelope as `events`). A write failure is printed and never changes the gate (`push`).
- Port `forge_events.ForgeEvents` has operations via `_operation(name)`: an adapter lacking one is refused by name. `MemoryAdapter` (test fake) and `FileAdapter` have no comment/status operations; `GitHubAdapter` has `comment`, `upsert_comment`.
- `forge_github.py` header states commit statuses were avoided because the cloud token got 403 on status writes. `github_api.rest` raises `RuntimeError('gh: exit N ...')`; `forge_github._status` parses N.
- Registry `config/registry/forge-events.json` has no status keys. `gate.json` has `gate.status_enabled` (comment switch; unrelated, GX-03 owns the file).
- Verdict envelope payload (gate_report.gate_events:74): `tier` (1 for tier-1 modes, else None), `plan` (mode), `input_hash`; no `input_digest` yet (GX-10 not merged).
- Tests: `scripts/tests/test_forge_events.py` (run by `scripts/tests/forge-events.test.sh`), `scripts/tests/test_gate_status.py` (run by `gate-status.test.sh`; FakeRest patches `github_api.rest`).

## Cited sources verified
All brief file paths exist, except: tests live in `scripts/tests/`, not `scripts/lib/`; `docs/process/EVENTS.md` is deliberately not touched (GX-37); `docs/operations/gate-status.md` is new; `gate_report.py` is GX-39's, so the final status is derived inside `gate_status.py` from the `events` it already receives.

## Branch note
The session is bound to `claude/gx17-gate-status-api-r2kajb`; the brief names `mod/gx17`. The session rule forbids pushing to another branch, so this single branch/PR is used.

## Risks
- 403 (identity lacks `statuses:write`): must be non-fatal, printed once per run.
- `gate.status_enabled` already means "comment"; the new switch is `forge-events.status_enabled`.
