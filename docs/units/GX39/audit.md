# GX-39 audit (read-only findings)

Base `mod/roadmap-integration` 4bc4dd04. Branch `claude/gx39-report-cache-seams-uabres` (the session's designated branch; the brief's `mod/gx39` is not used, no second branch).

## Cited sources, verified on the base
- `scripts/lib/gate_report.py` (277 lines): `gate_events`, `defect_events`, `adjudicate_known_defects`, `emit_evidence`, publish condition in `main`. Exists.
- `scripts/lib/gate_result_cache.py`: `tier_of`, `key`, `stage_key`, `TIER1_MODES = {'dev'}`. Exists.
- `scripts/tests/test_gate_report_skips.py`, `units/engine-gate-report/unit.json`, `absolute-literals-baseline/engine/engine-gate-report.json`. Exist.
- `gate_proof/adjudicate/publish/tier/carry/keys.py`: do not exist yet (this unit creates them).

## Coupling that constrains the split
- Tests call `gate_report.gate_events`, `defect_events` (via gate_events), `emit_evidence`, `expected_stages`, `stage_log`, `stage_results`, `apply_coverage`, `browser_failures`, `ready_hook`, `main`, and patch `gate_report.adjudicate_known_defects` (`test_defect_detect.py`, `test_gate_report_skips.py`, `test_pr_ready.py`, `test_forge_events.py`). Those names stay in `gate_report`.
- `gate_skips.py` imports `gate_report.expected_stages`; it stays.
- Registry reads (`forge-events.repo`, `tier1_gate_modes`, `gate_step_prefix`, `gate_producer`) are in `gate_report`; the new modules read no config (D-B9, no `x-readers` change).
- `gate_result_cache` and the report use two tier sources (`TIER1_MODES` constant vs registry `tier1_gate_modes`); `gate_tier` takes the modes as an argument so both keep their source.
- Literal census: the `number 1000` allowance of `gate_report.py` leaves with the moved `round(seconds * 1000)`.
- Unit manifest: the new files are not yet claimed in `units/engine-gate-report/unit.json` (GX-38 pre-claims them); `scripts/structure-check` reports 0 errors without the claim.

## Known base defects (not this unit)
`claude-session.test.sh`, `root-identity.test.sh`, `config.test.sh` (`RegistryMemo.test_a_rewritten_file_is_read_again`): env, owned by GX-ENV.
