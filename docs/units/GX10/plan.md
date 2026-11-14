# GX-10 plan

Premises: P-42 (GA-P01, proof is content-addressed; CRITICAL, decided). No new premise.

## Commits (dependency graph)

1. `docs/units/GX10/audit.md` (done).
2. `docs/units/GX10/plan.md` (this file).
3. Registry switch: new `config/registry/gate-proof.json` with `gate-proof.event_version` (default 4, enum 3/4; 3 restores the v3 payload byte for byte), `x-unit`, description, `x-readers`; generated module via `scripts/generate`. Test: `scripts/run test config` parts that check the registry (`scripts/generate --check`).
4. v4 producer in `scripts/lib/gate_proof.py` (`bind()` the proof inputs, `verdict_payload` adds the v4 fields when the switch is 4 and the binding is complete, `version_of(payload)`, `selection_digest`, cost); the one-line seam fix `scripts/lib/gate_report.py:71` passes `gate_proof.version_of(verdict)` (audit Finding 1); new `scripts/tests/test_gate_report_v4.py` (v4 validates through `event_contracts`, v3 byte-identical with the switch at 3, the recompute-the-digest test from git and the toolchain manifest alone, GX-09's readers accept the produced event), run by `scripts/tests/gate-report-skips.test.sh` with its covers sidecar. Depends on 3.
5. `scripts/lib/gate-hooks/proof.sh`: calls `gate_proof.py bind` once, exports `OU_GATE_VERSION` and `OU_GATE_PROOF` (the binding as JSON), sets `OU_GATE_PASS_EXTRA` to `head_tree`, `base_sha`, `gate_version`, `toolchain_id`, `input_digest`; a binding that cannot be made (no sha or base) leaves both empty and the run unchanged. Test: a case in `test_gate_report_v4.py` sources the hook on a temp repo. Depends on 4.
6. `docs/units/GX10/retro.md` after the pinned gate.

3 → 4 → 5 is a REAL chain (5 calls the module of 4, 4 reads the key of 3); every commit is small, so the work stays in one session (no sub-agent: one module, no parallel files worth splitting). Critical path ≈ 3 (10 min) + 4 (35 min) + 5 (15 min) + gate (≈ 15 min) + retro (10 min).

## Tests

Per commit as above; final: `scripts/run test gate-report-skips`, `scripts/run test event-contracts`, `scripts/run test plan-tick` (GX-09 readers), `scripts/run test gate-local`, then the single pinned gate `scripts/gate-dev --pr 727`.

## Rollback

`scripts/config set gate-proof.event_version 3` (or the registry default) restores today's v3 payload; revert PR of the merge commit for the rest.

## Known base defects expected

KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3 (gate-adjudicated); env tests claude-session, root-identity, config (GX-ENV). Not touched.
