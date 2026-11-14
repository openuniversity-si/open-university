# tooling-perf audit (U4)

Read-only findings, base `mod/roadmap-integration` 657b6f4f.

- Unit: 12 files under `apps/web/scripts/` (bundle scan, perf budget, factory bench, ship bench, nbuild, html snapshot), 936 lines, under `units.size_ceiling` (no `unit.oversize`).
- Physical form: S1 keeps units logical (P-03). The `@ou/tooling-perf/*` address maps to `apps/web/scripts/*`, which other tooling units share, so nothing moves.
- Import graph: no unit imports `@ou/tooling-perf` yet. The only outside reader of a unit file is `lib/perf-budget-home.test.ts` (owned by no unit), which imports `auditHomeImages`, `estimatedFirstViewportsImageBytes`, `homeImageFailures` and `PERF_BUDGET` from `perf-budget.ts`.
- Contract slot: empty before this PR. Filled with `lib/perf-contract.ts` (1.0.0), exporting exactly those four names.
- Tunables found as literals: the perf budget (total, image, font bytes), the two viewport widths, the initial JS budgets of `bundle-scan.ts` and the two factory-bench time limits. Nine registry entries now hold them (`budgets.perf_*`, `budgets.bundle_*`, `budgets.factory_bench_*`), values unchanged, read through `lib/perf-config.ts`.
- Literals left: the D-063 census (`scripts/lib/absolute-literals-baseline/scripts.json`) still lists 508 offenders in the eight production files: usage and error prose, option names, regexes, small counts.
- Battery: `scripts/unit-battery tooling-perf` is green on every step but over `battery.unit_time_limit` (10 s): the `types` step is about 11 s because `factory-bench.ts` pulls 1231 files through the catalog harness. It was 11.9 s on the base before this PR, so it is a base defect, not a regression. The limit stays.
- Hermeticity: unit tests use no network; `factory-bench.int.test.ts` runs on the local test database.
