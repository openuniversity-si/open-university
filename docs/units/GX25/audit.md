# GX-25 audit (base 132af477)

Unit: gate lifecycle events, ETA from the ledger, `gate.slow`. Deadline: 90 min from launch (00:4x BRT 28/10).

## Findings (current behaviour, file:line)

| # | Finding | Where |
|---|---|---|
| A1 | Nothing publishes `gate.started`: the v1 contract, lock entry, generated modules and `EVENTS.md` row exist (GX-37) but no producer. | `contracts/events/gate.started.v1.json` (required: repo, pr, sha, unit, premises, tier, plan, expected_wall_s, critical_path); `rg gate.started scripts` has no producer |
| A2 | The begin seam is `gate_status begin`, called by the closed driver twice (first begin, then the scoped replan); `gate_status.begin` creates state only on the first call. | `scripts/gate-local:290`, `:386`; `scripts/lib/gate_status.py:begin` |
| A3 | The ETA is a sum, not a critical path: `render_live` adds `expected` of pending stages and says "no history" when the local history is empty; the text itself admits "stages overlap". | `gate_status.py` `render_live` (remaining/known sums) |
| A4 | The expectation is the median of the last `gate.status_history_runs` local `reports/*/*/stages.json` runs: box-local, empty on a fresh container. | `gate_status.py` `history()` |
| A5 | `engine.step.measured` per stage (`gate:<stage>`) is published with every verdict and is file-routed (`forge-events.file_kinds`): a read costs no forge call but is also box-local. `slo.step_stats(events, percent)` already folds it to a percentile per step. | `gate_report.py:gate_events`, `forge_events.py:adapter_from_config`, `slo.py:step_stats` |
| A6 | `forge_events.gate_slow(verdicts)` exists and is never called by a verdict path; `slo.run`/`scripts/slo evaluate` are run by hand. | `forge_events.py:gate_slow`; `gate_report.py:main` (no call) |
| A7 | The graph (`needs`) is available as data: `gate_graph.load()`; no critical-path function on base (GS2 has one on `origin/claude/gs2-lhj4m5`, `gate_timing_report.py`, not merged). | `gate_graph.py:load`; GS2 branch |
| A8 | The verdict path (`gate_report.main` -> `publish_status` -> `gate_status.final_from_report`) is the single point reached once per PR verdict and already holds the verdict envelope. | `gate_report.py:main`, `gate_status.py:final_from_report` |
| A9 | Tier: `gate_tier.current(mode, forge-events.tier1_gate_modes)`; premises: `forge_events.premises_from_body(port.adapter.change(repo, pr)['body'])` (one forge read). | `gate_tier.py:43`, `gate_report.py:emit_evidence` |

## Design consequences

* Producer at begin = inside `gate_status.begin` (first call only; natural key repo/pr/sha/plan dedupes any repeat). The driver stays untouched.
* Event-driven verdict hook = inside `gate_status.final` (A8), switch `gate-eta.started_enabled`.
* Critical path is computed over `gate-stages.json` needs restricted to the planned stages (concurrency limits ignored; recorded).
* Fresh container: ledger (file log) -> local report history -> registered per-stage fallback `gate-eta.fallback_stage_s`; never "no history".
* Step events do not carry the plan, so the expectation is per stage (plan-wide); recorded as a seam.

## Known base defects expected

KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3; env: claude-session, root-identity, config script tests.
