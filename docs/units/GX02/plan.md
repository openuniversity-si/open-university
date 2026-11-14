# GX-02 plan (mirrored in PR #695)

## Plan
- [ ] 1. Cherry-pick `eaa408de` unchanged (`-x` provenance line; message keeps the original text, trailer `Plan: 1`).
- [ ] 2. `docs/units/GX02/audit.md`: findings and evidence.
- [ ] 3. `docs/units/GX02/plan.md`: this plan (mirrored here).
- [ ] 4. `engine_role.CommandGate` reads the GX-01 class line (`gate.class_line_prefix`) for the failed stage and its class (`GateResult.kind`) instead of the first `^FAIL` line and the 2000-char tail regex; `train.tier2_log_chars` is kept for the log excerpt only. Tests: `scripts/run test train-role`, `scripts/run test train`.
- [ ] 5. Train: `train.halt_classes` (registry, default `["env","contract"]`, generated module) decides halt vs eject from `result.kind` for the combined head and every bisection probe; `env` emits `env.drift` (`contracts/events/env.drift.v1.json`) before `TrainHalt`; the 27/10 fixture (`FAIL local postgres did not start`) halts with `env.drift` and no `pr.ejected`. Tests: `scripts/run test train`.
- [ ] 6. Docs: `docs/operations/train.md` (halt on env/contract, eject only on code, the switch) and the `env.drift` producer line in `docs/process/EVENTS.md` (reverted in 7).
- [ ] 7. GX-06 (absorbed by plan-v2, coordinator 15:20): `train.trigger_mode` (`emit_only` default, `detached` rollback) in `train_trigger.py` (plus the one caller line in `pr_ready.py`); the lock lease is `train.tier2_timeout_s + train.lock_lease_margin_s` (`train.lock_lease_s` retired); the lock owner is the session id (`train.session_id_env`); the train refuses a machine-local override of `train.enabled`; tier 2 gets a fresh `GATE_TEST_CACHE_DIR`; a timeout counts as `env` (its registry description); every train-module read goes through `engine_role.setting` (this checkout's registry, so the base-tip gate reads the head's new keys); the train-role session runbook and the `env.drift` producer go in `train.md`; my `EVENTS.md` hunk is reverted (GX-37 owns that file). Tests: `scripts/run test train-role`, `scripts/run test train`, `plan-tick`, `battery`.
- [ ] 8. `docs/units/GX02/retro.md` and `train.enabled` default true (the last commit; safe under `emit_only`).

Graph: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8. The edges 4 → 5 and 5 → 6 are real (5 reads `kind` from 4, 6 documents 5). 7 collides with 4-6 only on the same files, so it runs after them; the cap of 8 commits keeps it one commit. Critical path ≈ 3 h (plan-v2 estimate) plus gate wall time.

Premises: GA-P05 (verified: `git merge-base --is-ancestor eaa408de origin/mod/roadmap-integration` exits 1; radius low); P-18 train is the sole merger (medium; `train.halt_classes=[]` is the one-key rollback); P-21 long session per lane (low); P-33 everything in the cloud (medium; `train.trigger_mode=detached` is the rollback); P-42 and P-46 indirectly. Decisions D-070 and D-065 (3); GA-PG2 (one designated train session) and GA-PG8 (`train.enabled` never in one machine's change log).
Known base defects (owner GX-ENV): `claude-session.test.sh`, `root-identity.test.sh`, `config.test.sh` (`RegistryMemo.test_a_rewritten_file_is_read_again`), and in the cloud the uid-65534 fs-encoding crash.

Final gate: one `scripts/gate-dev --pr 695` from a clean base-tip checkout (verdict of record, D-A3), and one from this checkout (report-only). Before it, only the targeted tests: `scripts/run test train` and `scripts/run test train-role`.

Decision: D-070, D-065. Premises: P-18, P-21, P-33, P-42, P-46.
