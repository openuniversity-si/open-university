# catalog-authoring-server: plan (U4)

Premises: P-03 (units stay logical; medium: the alias maps to a directory other units share), P-04, P-05 (see the literal decision, medium), P-07 (a contract is added, nothing breaks; high), P-16. None is CRITICAL.

Commits:
1. Manifest `battery.command`; a first attempt added `server/contract.ts` and a test (two commits), which overran the catalog cell budget, so the next commit removes them again.
2. `audit.md`, `plan.md`.
3. `contract.md`: the surface and the literal decision.
4. `retro.md` after the final gate.

Literal decision (P-05): the 423 D-063 census offenders are table and column names, statuses, audit action names and error text whose exact value is pinned by int tests and by the HTTP contract. Rewriting them with the contract would mix two risks, so the baseline is left as is (shrink-only holds) and the migration is its own slice. Recorded in a PR comment.

D-069 items: 3 (no new literal, no tunable), 5 (alias and CODEOWNERS generated), 8 (ownership through `scripts/units`), 14 (battery 7.3 s, limit untouched).
