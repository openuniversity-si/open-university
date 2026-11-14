# GK1 audit (read-only; evidence from `scripts/gate-local` and `scripts/lib/gate_report.py` at 244e7c7c)

## Complaint
LR1 retro item 7: a registered known base defect in `script tests` sets `failed=1`; `e2e smoke` never runs and `gate_report` says `missing gate stages: e2e smoke`.

## Findings
1. `failed` is one flag for two different things: "the verdict is red" and "a later stage cannot run". Known defects are adjudicated only at the end (`gate_report.py` re-runs the failing tests on the base), so at schedule time no stage can tell a known defect from a new failure.
2. Guards that read `failed` before running a stage (`scripts/gate-local`):
   - line 319 `if [[ $failed -eq 0 ]]`: the whole fixed block (suite union, impact, lint, unit, builds, Neon, browsers). In a full battery `shellcheck`, `script tests`, secret scans or `structure check` all run before it, so any red there skips everything after.
   - line 343 Neon PR migrations, 374 `e2e + a11y`/`e2e smoke` after `browser inventory`, 389 `factory bench`, 211 DB-gate stages.
3. Only some of those are real dependencies: install failed (no `node_modules`), `browser inventory` failed (nothing to run), DB-gate classify failed. A red `script tests`, `shellcheck`, secret scan or lint does not make a later stage unrunnable.
4. A skipped stage leaves no trace. `gate_report.py` computes `expected - passed` and prints `missing gate stages`, which is the same text for "not in this plan" and "skipped by a guard"; the guard cause is lost.
5. `*.stage.json` is read by `gate_status.py`, `gate_report.py`, `gate_failures.py`; a skip record must use another suffix to leave them untouched.
6. Existing coverage: `scripts/tests/gate-local.test.sh` (runner + structure greps), `gate-db.test.sh` (real gate-local, stubs), `test_defect_detect.py`, `test_gate_failures.py`. None covers a skip. `gate-local` and `gate-runner.sh` are `fallback` files in `gate-script-tests.json` (touching them runs the whole script suite).
7. Settings: nothing new is tunable. No threshold or timeout is touched.

## Registered defects expected on this branch
KD-024bbecb (`generate.test.sh`) and KD-4db6e693 (`premises.test.sh`), base 79045314, owners per `docs/operations/known-defects.md`.
