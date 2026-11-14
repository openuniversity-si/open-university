# GV1 audit (read-only evidence)

Brief: one live, readable gate status comment per PR head (D-069). Findings:

- Stage boundary: every stage goes through `step()` in `scripts/lib/gate-runner.sh`, which writes
  `<stage>.stage.json` (`name, result, exit, seconds`). The one call site for stage start/end.
- Plan: `scripts/gate-local` writes `$logs/plan.json` (`stages`) after `gate_policy.py classify`; nightly/full modes use
  `gate_policy.PLANS`. `gate_report.expected_stages(mode, logs)` already resolves the planned stage names.
- Verdict: `scripts/lib/gate_report.py` `__main__` writes `stages.json` and calls `emit_evidence`, whose `gate.passed/failed`
  payload carries `failing_tests` (`gate_failures.failing`), `cached_tests` (`gate_failures.cached_tests`) and, since KD1 #572,
  `known_defects` (`defect_detect`, registry `scripts/defects`). KD1 is merged: GV1 reads `report['known_defects']`
  and `report['defect_decisions']`; no port is needed.
- Forge comments: `forge_github.GitHubAdapter` appends one marker-led comment per event chunk and never edits; `github_api.rest`
  is the single REST client (no `gh`). Status needs a PATCH of one comment, found by a marker plus the head sha.
- History for ETA: `$GATE_RECORD_DIR/reports/<sha>/<mode>-<ts>/*.stage.json` from earlier local runs (no network).
- Config: every number lives in `config/registry/gate.json` (+ `x-readers`); docs/generated outputs are checked by `scripts/generate --check`.
- Not touched (KD1/GS1): selection, classification, cache, base comparison.
