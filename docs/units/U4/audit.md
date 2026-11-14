# U4 engine-commit-plan: audit

Read-only findings, base `a2c09043` (mod/roadmap-integration, includes LR1 #575 and CO1 #576).

- **Physical form.** `scripts/lib/unit_addresses.py` gives an `@ou/<id>` address only to units whose home lies inside the TypeScript
  project and holds no unit of another cell. This unit is Python and shell under `scripts/` and `config/registry/`, so it has no address
  form. Per the brief the files stay in place; the executables (`scripts/commit-check`, `plan-tick`, `pr-ready`) are the public entry
  contract and keep their paths. A `contract.entry` in the manifest cannot be verified without an address (`unit_battery.plan` reports
  the entry "not a file of" the unit), so the contract slot stays empty rather than hold an unverifiable entry.
- **Consumers.** Importers of `commit_check`, `plan_tick`, `pr_ready`, `local_checks`: `structure.py`, `structure-check`, `gate-local`,
  `premises.py`, `push_guard.py`, `decision_wait.py`, `gate-script-tests.json`; they reach the modules by sys.path, not an address.
- **Literals.** No `x-literal-sites` entry names a file of this unit; its tunables already live in `config/registry/{local-checks,plan-tick,budgets}.json`.
  Nothing to migrate; the allowlist for these files is already zero.
- **Battery.** `scripts/unit-battery engine-commit-plan` is RED: 12.3 s against `battery.unit_time_limit` (10 s). The one step is
  `script-tests` (3 files: commit-check 5.1 s, plan-tick 4.0 s, local-checks 3.7 s, run serially). The limit is never loosened.
  Cause for commit-check: `run_check` starts a Python subprocess per fixture (9 tests, ~0.5 s each, mostly interpreter and config startup).
- **Size.** 631 production lines, ceiling 1500: not oversize (it is over `units.context_budget` by closure, a property of its imports, not this PR).
- **Known base defects.** Timing-sensitive tcatalog tests (not touched); WARN-only structure findings unrelated to this unit.
