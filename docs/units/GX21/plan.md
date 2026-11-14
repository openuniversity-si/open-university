# GX-21 plan

Critical path: 1 -> 2 -> 3 -> gate (~10 min code + ~397 s script tests). Edges 2->3 real (3 imports 2). No parallel fan-out: two small files.

1. docs/units/GX21/audit.md (this audit).
2. docs/units/GX21/plan.md.
3. plan_tick.py: `ticked_by_commits` (empty commit ticks nothing; RETRO-only commit ticks only the RETRO item) + tests in test_plan_tick.py.
4. structure.py: `plan_completeness_errors` and `lane_errors` wired into `main` (`--pr`, and `--pr-body` via local git) + tests in test_structure.py, incl. the #615 fixture (item 3 unticked -> RED naming 3, fix = body edit or real commit).
5. retro.md + MERGE-READY.

Premises: P-22 (D-022 plan rule), P-46 (GA-PG1 pinned gate). Neither CRITICAL. pr_ready.py untouched.
Tests: scripts/tests/test_plan_tick.py, test_structure.py; final: gate-dev --pr 763.
Base defects expected: none known.
