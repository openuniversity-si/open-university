# tooling-catalog-cli-content: plan (U4)

Premises: P-03 (units stay logical; confirmed, medium: a move would break the shared `commands/` alias), P-04, P-05 (see the literal decision below, medium), P-07 (a contract is added, no breaking change; high). None is CRITICAL.

Commits:
1. Contract entry `commands/contract.ts` 1.0.0, its test, manifest paths and `contract`, regenerated `tsconfig` aliases and CODEOWNERS.
2. `audit.md` and this plan.
3. `contract.md`: the published surface and the literal decision.
4. `retro.md` after the final gate.

Literal decision (P-05): the 1073 census offenders are help and error prose whose exact text is pinned by core-unit tests; each needs a documented D-063 catalog key. Rewriting them in the same PR as the contract would mix two risks, so the baseline is left as is (shrink-only holds) and the migration is its own slice. Recorded in a PR comment.

D-069 items: 3 (no new literal, no tunable), 5 (aliases and CODEOWNERS generated), 8 (ownership through `scripts/units`), 14 (battery 6.7 s, limit untouched).
