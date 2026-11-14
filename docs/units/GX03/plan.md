# GX-03 plan: size the gate to its container

Premises: GA-PG4 (low; GX-00 registered it with the program premises P-42..P-47), P-36 speed sustainable (medium). No CRITICAL premise. Decision: D-070.

## Commits (Plan: N)

1. audit.md (this unit's findings; measurement section opened).
2. plan.md (this file).
3. Sizing: `gate.script_tests_per_vcpu`, `gate.slots_per_vcpu`, `gate.slots` as optional override (0 = derived), `gate_test_cache.script_tests_workers/gate_slots`, `gate-isolation.sh ou_gate_slot_count`, longest-first order from `engine.step.measured`, `gate_graph.run_commands(timings=)`, tests, regenerated config module.
4. Measurement results (cold base gate at concurrency 4 and 8, then with the change) in audit.md.
5. retro.md.

## Dependency graph and critical path

Real edges: 3 needs nothing; 4 needs the measurement runs (started at launch, about 2 x 10 min, in parallel with coding 3) and 3 for the with-change run; 5 needs 4. Collision edges: none (each commit owns its files). Critical path: measurement (about 25 min) overlaps coding (about 30 min); with-change cold gate about 10 min; retro 10 min.

## Tests

Per commit 3: `scripts/tests/gate-test-cache.test.sh`, `gate-isolation.test.sh`, `gate-heavy-db.test.sh`, `gate-graph.test.sh`, `scripts/generate --check`. One final gate: `gate-dev --pr <n>` from a clean base-tip checkout (verdict of record, D-A3) plus the own-checkout report-only run.

## Rollback

`gate.slots` = 3 and `gate.script_tests_concurrency` = 8 with `gate.script_tests_per_vcpu` large through `scripts/config`; or revert the merge commit.

## Known base defects expected

claude-session, root-identity, config script tests (env unit GX-ENV).
