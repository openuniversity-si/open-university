# U4 engine-commit-plan: plan

Premises: P-03 (high: files stay logical; if wrong the move is a later, mechanical PR), P-04, P-05 (no literals to migrate; verified by the
empty allowlist), P-07 (no contract change here). None is CRITICAL: no money, production or source-of-truth change.

Commits (sequential: they share the manifest and the tests of one battery):
1. audit.md (this evidence). 2. plan.md. 
3. Hermetic fast tests: `test_commit_check.py` calls `commit_check.main` in-process instead of one subprocess per fixture (same class: any
   other per-case subprocess of the unit's tests). Owns `scripts/tests/test_commit_check.py` (+ `test_plan_tick.py` if needed).
4. Manifest `battery.command` = `scripts/unit-battery engine-commit-plan`; regenerate aggregates/CODEOWNERS with `scripts/generate`.
   Owns `units/engine-commit-plan/unit.json` and generated outputs.
5. retro.md.

Targeted tests: `scripts/unit-battery engine-commit-plan` after 3 and 4; `scripts/structure-check`. One final `scripts/gate-dev`.
D-069 items: 3 (zero literals, allowlist empty), 5 (generated outputs), 8 (ownership), 14 (battery under the limit, never loosened).
