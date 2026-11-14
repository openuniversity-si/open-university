# GX-12 audit

Unit: tier 2 leaves evidence, `scripts/lib/gate_publish.py` only. Base mod/roadmap-integration eaeeb29d.

## Publish condition today (file:line on the base)
- `scripts/lib/gate_publish.py:7-9` `should_publish(mode, pr, sha)` = `bool(mode and pr and SHA.fullmatch(sha))`. Only caller: `scripts/lib/gate_report.py:211`.
- `scripts/lib/gate_publish.py:12-15` `channel(mode, logs)` is the writer id `gate:<mode>:<run folder>`; caller `gate_report.py:94` (no registry key, channel of the log is chosen by the envelope's `pr`).
- Argv: `scripts/gate-local:90-91` sets `event_pr="$pr"` and clears it for a report-only run; it is the 5th argument of `gate_report.py` (`:134, :209, :499`). A tier-2 run (`scripts/gate-batch:31`, `gate-local --dev --sha <head>`) has no `--pr`, so `event_pr` is "" and `should_publish` is False: no verdict, no `engine.step.measured`, nothing on the repository channel (G-02).

## What blocks a no-PR publish besides the condition
1. `gate_report.py:212` `emit_evidence(report, mode, int(pr), ...)`: `int("")` raises ValueError, caught as "FAIL gate evidence ... (class env)" at `:216-219`. Flipping the condition alone would make every no-PR run FAIL.
2. `gate_proof.verdict_payload` sets `tier` from `gate_tier.current(mode, tier1_modes)`; `dev` is a tier-1 mode (`forge-events.tier1_gate_modes` default `["dev"]`), so a no-PR dev run would be labelled tier 1, not 2.
3. `emit_evidence` reads the PR body for premises via `port.adapter.change(repo, pr)`; with `pr` None this must be skipped.
4. `ready_hook` (`:222`) is only for a passed verdict of a PR; it would need `pr` too.

Items 1-4 are in `gate_report.py` (GX-39 only, closed to this unit) and `gate_proof.py` / `gate_tier.py`.

## Decision (seam-respecting, recorded in the PR)
`gate_publish.py` gains the pure rules (repository-channel condition, `change_number`, `tier`) with tests; the existing tier-1 `should_publish` stays byte-for-byte so `gate_report.py` keeps working. Flipping `should_publish` is NOT done here because the closed caller would turn every no-PR run red (item 1). The two caller lines are handed to the owner of `gate_report.py` (see PR).
