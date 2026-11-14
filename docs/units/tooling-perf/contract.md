# tooling-perf contract (1.0.0)

Entry: `apps/web/scripts/lib/perf-contract.ts`, address `@ou/tooling-perf`. It exports only what other files import today:

| Export | Source | Importer |
|---|---|---|
| `PERF_BUDGET`, `auditHomeImages`, `estimatedFirstViewportsImageBytes`, `homeImageFailures` | `perf-budget.ts` | `lib/perf-budget-home.test.ts` (no unit; relative path) |

Everything else (`plannedResources`, `findSecretLeaks`, `runBench`, ...) is private to the unit. A breaking change goes expand->contract (P-07, D-029); no consumer file is edited here. Aliases and CODEOWNERS come from `scripts/generate`.

Configuration: every budget is a `budgets.*` registry entry (D-068); `lib/perf-config.ts` reads them. A budget only tightens.

Open items: the 508 D-063 census offenders are prose and structure, not tunables, and are not migrated here (see `plan.md`); the baseline did not grow. The battery's `types` step is over its time limit on the base.
