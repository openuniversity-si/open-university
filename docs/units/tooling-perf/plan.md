# tooling-perf: plan (U4)

Premises: P-03 (units stay logical; confirmed, medium: a move would break the shared `scripts/*` alias), P-04, P-05 (literal decision below, medium), P-07 (a contract is added, no breaking change; high). None is CRITICAL.

Commits:
1. Contract entry `lib/perf-contract.ts` 1.0.0, its test, nine `budgets.*` registry entries replacing the unit's tunable literals, regenerated `tsconfig` aliases and CODEOWNERS.
2. `audit.md`, this plan and `contract.md`.
3. `retro.md` after the final gate.

Literal decision (P-05): tunables (budgets, viewport widths, time limits) are registered. The 508 remaining census offenders are help/error prose and option names whose text is pinned by tests; each needs a documented D-063 catalog key, which is its own slice, so the baseline is left as is (shrink-only holds).

Battery decision: the over-limit `types` step is a base defect caused by the catalog harness graph; the limit is untouched and the owner of `factory-bench` can split it later.

D-069 items: 3 (budgets in the registry), 5 (aliases and CODEOWNERS generated), 8 (ownership through `scripts/units`), 14 (budgets keep their values; limit untouched).
