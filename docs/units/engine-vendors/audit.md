# engine-vendors audit (U4)

Read-only findings at base a2c09043 (mod/roadmap-integration).

- **Physical form.** UNITS.md (U3a): a unit outside the TypeScript project (the engine's `scripts/` units) has no `@ou/`
  address until it has its own directory, and S1 (P-03) keeps units logical. No engine unit has moved. Decision: keep the
  files in place (the brief's explicit fallback) and deliver the rest of the definition of done.
- **Owned files.** `scripts/lib/adapters/**` (10 modules + `engine-vendors.json` catalog), `scripts/lib/vendor_check.py`,
  `scripts/tests/test_ports_*.py`, `test_vendor_check.py`, `vendor-ports.test.sh`. Manifest has no `contract` yet.
- **Importers (the contract surface).** `storage.open_store` (gate_result_cache, gate_test_cache, defect_detect),
  `launcher.adapter` / `launcher.LaunchRequest` / `launcher.launch` (coordinator, coordinator_launch, test_coordinator_launch),
  `vendor_check.check` (structure.py). Nothing else is imported from outside the unit.
- **Literals.** `config_check.literal_findings` reports nothing for these files, and no `x-literal-sites` entry names them.
  Manual scan: no timeout, count, path or model literal outside the registry (`launcher_claude` reads
  `coordinator.launcher_timeout_s`). The allowlist for the unit is already zero.
- **Battery.** `scripts/unit-battery engine-vendors` is red: 73.5 s against `battery.unit_time_limit`.
  Cause: `test_ports_model_ladder.Registry.test_the_registry_ladder_holds_the_current_rule` calls `config.check(ROOT)`
  (66 s, a repo-wide check owned by engine-config and run by structure-check). The other four test files take 4 s together.
- **Oversize.** Not checked against `units.size_ceiling` beyond line counts (658 production lines): far below; no `unit.oversize`.
