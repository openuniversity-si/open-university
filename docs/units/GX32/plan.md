# GX-32 plan: base health signal (`base.red` / `base.green`)

Goal: tier 3 (battery role, on `integration.advanced`) publishes which tests are red on the base tip; adjudication excuses a red test of **any** per-test stage kind when the `base.red` for the proof's `base_sha` lists it with the same signature and the PR did not touch its file or covers (GX-13 rule), with zero base re-runs. Rollback: `defects.base_signal_enabled=false` (today's behaviour exactly).

## Commits (`Plan: N` trailers)
1. `docs/units/GX32/audit.md`: audit (done).
2. `docs/units/GX32/plan.md`: this plan.
3. `scripts/lib/defect_adapters.py` (new, harvested from BD1 #667): one adapter per failure shape (`script`, `vitest`, `browser`), `failures(report, logs)` → every failing test of every failed stage with a `complete` flag, `file_of(failure)` (id → repo path) and `rerunnable(stage)` (only the script shape has a base re-run). Tests in `scripts/tests/test_defect_detect.py`; `covers/defect-detect.json` gains the new file.
4. `scripts/lib/defect_detect.py` + `config/registry/defects.json` (+ `scripts/lib/generated/config_registry_defects.py`): `defects.base_signal_enabled` (true) and `defects.stages` widened to the per-test stages; `base_signal(base)` reads the newest `base.red`/`base.green` for exactly that sha on the repository channel; `adjudicate` excuses a listed, untouched failure without `outcome()`; without a listing only re-runnable stages are re-run (unchanged); `explained` uses the adapters for all stages; `touched` resolves vitest/browser ids to files. Switch off: the old path (script tests only, re-run). Tests: N PRs on one red base all `MERGEABLE` with zero re-runs; a touched test not excused; another signature not excused; another base_sha not excused; switch off restores today.
5. `scripts/lib/battery.py`: `Tier3Gate` runs with its own `GATE_REPORT_DIR` and reads the failing tests through the adapters; `run_tip` emits `base.red {tests, since, base_sha}` on a red tip with attributed tests (`since` carried from the open base.red) and `base.green {cleared}` on the first green tip after a base.red. Tests in `scripts/tests/test_battery.py` validating against the locked v1 contracts; `covers/battery.json` gains `defect_adapters.py`.
6. `docs/units/GX32/retro.md`: RETRO after the pinned gate.

## Dependency graph and critical path
1 → 2 → 3 → {4, 5} → gate → 6. 3 → 4 and 3 → 5 are real (both import the adapters); 4 and 5 own disjoint files and could run in parallel. Choice: one writer, in sequence (each step ≈ 10-15 min, a sub-agent brief costs about the same as the step; no file shared). Critical path ≈ 5 + 15 + 20 + 15 + gate.

## Premises
- D-070 only (`Premises: P-46`, GA-PG1 pinned gate). Masking risk medium, mitigated by: exact `base_sha` match, same normalized signature, GX-13 touched rule, unattributed stages stay the PR's, a failed read of the signal excuses nothing. Not CRITICAL (no money, production or source of truth).

## Tests
Targeted: `scripts/run test defect-detect`, `battery`, `event-contracts`. Final: pinned `scripts/gate-dev --pr 737`.

## Known base defects expected (not mine)
KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3; env: claude-session, root-identity, config (GX-ENV).

## Out of scope
Re-gate pause while the base is red: `defect_detect.base_red(base)` is exposed; the train/coordinator owner wires it.
