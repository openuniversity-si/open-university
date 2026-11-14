# CO1 plan (mirrored in the PR description)

## Commit plan
1. Audit (`docs/units/CO1/audit.md`).
2. Plan (this file).
3. Program contract and registry: `contracts/programs/program.v1.json`, `scripts/lib/program.py` (load, validate, graph checks, status folded from events), template, seed `docs/programs/reach-1000-prs-per-day/`, `scripts/program`, registry keys, tests.
4. Coordinator core: `scripts/lib/coordinator.py` pure `next(state, events, config)`, `scripts/coordinator` CLI (`next`, `status`, `run`), registered limits, tests.
5. Launch adapter: `docs/padrao/v1/*`, brief renderer, launcher port with Claude Code cloud adapter and dry-run, lessons and defects ports, tests.
6. Program gate and retro: `scripts/lib/program_gate.py` (all units merged, measurable goal from events, retro aggregation with `padrao_candidate`), tests.
7. Docs and ownership: `docs/operations/coordinator.md`, EVENTS.md notes, unit manifest `engine-coordinator`, CODEOWNERS, script-test mapping, generated outputs.

## Dependency graph and owned files
`1 → 2 → 3 → {4, 5 (after 4's action shape), 6} → 7`. 4, 5 and 6 each own disjoint files; 5 consumes the action shape fixed in 4, so they run in sequence. The steps are small and share vocabulary, so the coordinator session executes them directly (sub-agents would re-derive the same context; same call as GV1).

| Commit | Files owned |
|---|---|
| 3 | `contracts/programs/**`, `config/registry/coordinator.json`, `scripts/lib/program.py`, `scripts/program`, `docs/programs/**`, `scripts/tests/test_program.py`, `scripts/tests/program.test.sh` |
| 4 | `scripts/lib/coordinator.py`, `scripts/coordinator`, `scripts/tests/test_coordinator.py`, `scripts/tests/coordinator.test.sh`, registry keys |
| 5 | `scripts/lib/coordinator_launch.py`, `scripts/lib/adapters/launcher*.py`, `docs/padrao/**`, tests |
| 6 | `scripts/lib/program_gate.py`, tests |
| 7 | `docs/operations/coordinator.md`, `docs/process/EVENTS.md`, `units/engine-coordinator/**`, `CODEOWNERS`, `scripts/lib/gate-script-tests.json`, generated outputs |

## Premises
Premises: none registered. Working premises:
- **CRITICAL**: none. No money, production or source of truth: the coordinator defaults to dry-run, the real launcher is only invoked with an explicit flag, and launching spends quota only when an operator runs it.
- (high) `v3/queue.json` is absent: the seed comes from the brief's unit list (reader provided for the real file). Wrong dependencies in the seed are data, fixed by editing `plan.md`.
- (high) LR1 is not on the base: lessons come through a port with a null fallback.
- (medium) A launch is the existing `work.assigned` event; no new event type, contracts stay additive.
- (low) Event order within one second may tie: ordering uses the port's `ordering` (append order).

## Targeted tests, then one final gate
3: `program.test.sh`, `config.test.sh`. 4: `coordinator.test.sh`. 5/6: same plus `vendor_check`. 7: `scripts/generate --check`, `schema-compat`, `unit_check`. Then one `gate-dev`.

## Known base defects expected
`generate.test.sh` (`intents-doc.ts`), `premises.test.sh` (`measurement:S1`).
