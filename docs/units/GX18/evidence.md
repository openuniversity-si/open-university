# GX-18 evidence

Docs-only selection (plan_for + gate_script_tests.select_plan), before -> after:

| path | before | after |
|---|---|---|
| docs/process/EVENTS.md | no script tests | event-contracts.test.sh |
| docs/units/GX18/retro.md | none | coordinator, lessons |
| docs/programs/gate-excellence/plan.md | none | coordinator, program |
| docs/domain/DECISIONS.md | none | budgets, units |
| docs/process/premises/P-42.yml | none | premises |
| docs/operations/local-gate.md (uncovered) | none | none |

Unreadable covers (ScriptTestMapError mocked): `script tests` is still planned (test_unreadable_covers_still_run_the_script_tests).
Targeted: gate-areas.test.sh 24 OK, gate-test-cache.test.sh 7 OK, gate-script-tests.test.sh 15 OK.
Note: scripts/tests/gate-areas.test.sh is mode 100644 on the base, so `scripts/run test gate-areas` says "no such test"; run with bash. Not touched here.
