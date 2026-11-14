# LP3 plan — fold, validate and log the live plan

Unit LP3 of live-planning (D-071), branch `mod/lp3`, one PR into `mod/roadmap-integration`. Deadline: 1.5 h opus, stop at 3 h.

## Commits (dependency graph)

1. Audit and plan (`docs/units/LP3/{audit,plan}.md`). — 
2. `fold` + `digest` + tests against the fixture (`plan_live.py`, `test_plan_live.py`, `program.test.sh` runs it). ← 1
3. `validate` (op shape, unknown unit, missing dep, cycle, wave, stale parent) + tests. ← 2
4. `read_log` / `append` (chain check, optimistic parent, append-only file under the programs dir) + tests. ← 3
5. `scripts/program plan <p> [--at N]` and `log <p>` (`program.py`, `scripts/program` usage) + CLI round-trip test. ← 4
6. RETRO (`docs/units/LP3/retro.md`). ← gate

All code commits share `plan_live.py`/`test_plan_live.py`, so they are sequential (real edge: each builds on the previous
function); no sub-agents — the critical path is one writer, ≈ 60 min of code + one gate (≈ 3-6 min) + retro.

## Premises

- P-48 (cited by the brief). LP3-local: the fixture is right (verified: digests recompute — audit F1); `plan/live` absent
  is version 0 (blast radius: `read_log` only). None CRITICAL: no money, production or source-of-truth change.

## Tests

Targeted: `scripts/tests/program.test.sh` (runs `test_program.py` + `test_plan_live.py`), `scripts/program check
live-planning`, `scripts/structure-check` on the body. One `scripts/gate-dev --pr <n>` at the end from a clean base-tip checkout.

## Known base defects expected

claude-session, root-identity, config RegistryMemo / flaky `config.test.sh`, cloud uid-65534 fs-encoding (env; owners per brief).
