# GX-29 plan

Critical path ≈ 60 min: Plan 3 → Plan 5 (both edit `hermetic.py`); Plans 2 and 4 are independent of them and of each other (disjoint files), so they are done first/alongside. Edges: 3→5 file collision only (accepted, one file); everything else none.

- [x] 1. Audit and plan docs (`docs/units/GX29/audit.md`, `plan.md`).
- [ ] 2. DB residue: `test_db.py` `residue()`/`sweep()` + CLI; `gate-fixed.sh` sweeps in `gate_fixed_join`. Tests in `test_test_db.py`.
- [ ] 3. Network denial for the gate shell: `hermetic.py` `shell_env()` + an embedded Node hook (`_NODE_HOOK`, written to the temp directory; no new file, so no unit manifest edit) + `gate-fixed.sh` passes `--offline` to the media prefetch when `OU_GATE_OFFLINE=1`. Tests in `test_hermetic.py`, `gate-fixed.test.sh`.
- [ ] 4. Offline seed: `cloud.offline_seed_paths` in `cloud.json` (+ generated module), `setup.sh` seeds Chromium, pnpm store, media cache; `fonts.py` seeds fonttools. Test in the cloud-tail suite.
- [ ] 5. Covers trace (report-only): `gate-trace.json` `gate-trace.covers_trace_mode` default `report` (+ generated module); `hermetic.py` records opened files; `gate_script_tests.py` compares with declared covers. Tests.
- [ ] 6. RETRO + proof (network-denied gate run, leak count 0).

Premises: P-26 cloud hosts reachable (low); GA-P01..: P-42..P-47 as in the PR line. CRITICAL: none.
Targeted tests: `scripts/run test hermetic`, `gate-fixed`, `test-db`, `cloud-tail`, `claude-session` (known env failure). One final pinned gate.
Known base defects expected: see audit. Owners: GX-ENV, GX-FIX-modules.
