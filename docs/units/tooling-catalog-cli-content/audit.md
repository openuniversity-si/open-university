# tooling-catalog-cli-content audit (U4)

Read-only findings, base `mod/roadmap-integration` 265227c2.

- Unit: six command modules under `apps/web/scripts/lib/catalog-cli/commands/` (`courses`, `editions`, `imports`, `lessons`, `reference`, `texts`), 1244 lines, under `units.size_ceiling` (no `unit.oversize`).
- Physical form: S1 keeps units logical (P-03). The unit's `@ou/tooling-catalog-cli-content/*` address maps to the shared `commands/` directory, which other tooling units also own, so nothing moves; `registry.ts` (core unit) imports the modules by relative path and stays untouched.
- Import graph: the only `@ou/tooling-catalog-cli-content` importer is `catalog-cli/sync.test.ts` (`checkTextsFile`); `registry.ts` imports the seven command lists. Nothing else outside the unit imports a unit file.
- Contract slot: empty before this PR. Filled with `commands/contract.ts` (1.0.0), exporting exactly the seven command lists and `checkTextsFile`.
- Literals: `config_check.literal_findings` reports none (no tunable), but the D-063 absolute census (`scripts/lib/absolute-literals-baseline/scripts.json`) still lists 1073 offenders in the six files (809 strings, 219 numbers, 35 booleans, 10 regexes): CLI usage and help prose, error messages, option names, small counts.
- Battery: `scripts/unit-battery tooling-catalog-cli-content` was green at 6.4 s against `battery.unit_time_limit` (10 s); the unit owns no test of its own, only type-checking.
- Hermeticity: the unit's behaviour is exercised by core-unit tests with fake clients; no network.
