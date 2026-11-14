# GX-FIX-modules plan

Decision: D-070. Premises: P-42.

Critical path (about 25 min): audit run without apps/web/node_modules (~8 min, background) -> flip flags (1 min) -> guard test (3 min) -> gate (~10 min). Real edges only; the two edits touch different files and could run in parallel but are small enough to serialize.

## Commit plan
1. Plan and audit docs (docs/units/GX-FIX-modules/**).
2. `generate.test.sh` and every other test the audit shows needs modules: `"modules": true` in `scripts/lib/gate-script-tests.json`.
3. Guard in `scripts/tests/test_gate_script_tests.py`: new exact set, and a script that invokes `scripts/generate` or node tooling must be `modules: true`.
4. Retro.

## Premises
- P-42 (gate slot checkouts have no apps/web deps). Blast radius: install time only.
- Known env failures (claude-session, root-identity, config) are owned by GX-ENV.

## Tests
Per commit: `python3 scripts/tests/test_gate_script_tests.py`, each flipped test, structure-check. One gate at the end.
