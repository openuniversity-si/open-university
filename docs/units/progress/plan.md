# U3b progress: plan

Mechanical PR (plan v3.1 §4: U3b is a Haiku lane). Rewrite the unit's cross-unit imports to `@ou/<id>/<path>` per the
generated map (U3a, `apps/web/tsconfig.json` `paths`). No file moves, no renames, no behaviour change.

## Commits (dependency graph)

Every commit touches a disjoint set of files, but the four code commits all run after the audit and plan. They run in
the order below because `server/handler.ts` is shared between two import groups, so it is owned by exactly one commit.

1. Audit: `docs/units/progress/audit.md` (done, pushed).
2. Plan: `docs/units/progress/plan.md` (this file).
3. Kernel imports, four files: `client/client.ts`, `domain/rules.ts`, `domain/view.ts`, `domain/intents.ts`.
4. Platform, identity and db imports: `application/viewer.ts`, `server/deps.ts`, `testing/in-memory-progress.ts`,
   `testing/progress-contract.ts`.
5. Handler imports (kernel, platform): `server/handler.ts`.
6. Catalog test import: `server/handler.test.ts`.
7. Retro and the final census in the PR body (`docs/units/progress/retro.md`).

Parallelism: commits 3, 4 and 6 touch disjoint files and could run as sub-agents. The rule "one owner per file" holds,
so they run in parallel and each is pushed on its own. Commit 5 runs after 3 and 4 because it is the only file that
imports from both groups, and it runs as its own commit.

## Targeted tests per commit

Each commit: `pnpm exec tsc --noEmit` (apps/web), then the progress unit tests (`pnpm exec vitest run src/progress`),
then `scripts/unit-battery progress` once all four code commits are in. Expected: the same test count and file count
as the audit census (5 files, 20 test call sites), no type diff.

## Final gate

One `OU_CREDENTIALS=network scripts/gate-dev --pr <N>` run on the exact head after the merge of
`origin/mod/roadmap-integration` (merge commit, never rebase), per the brief.

## Premises and blast radius

- **P-03 (units are logical; addresses are stable).** Radius: high. If wrong, the generated `@ou/` map does not resolve
  the imports, and tsc fails. Check: tsc is run after each code commit.
- **P-13 (mechanical rewrite keeps behaviour).** Radius: medium. If an address names a file in another unit, the import
  still resolves but to a different owner; `scripts/units check` catches that at the gate.
- Not CRITICAL: no production, no secrets, no source-of-truth change, no spend.

## Known base defects and owners

- None for `progress` at base `a2c09043`.
- Contract gaps (not edited here; for the owners of the target units):
  - `apps/web/src/platform/db/testing/in-memory-uow.ts` and `apps/web/src/platform/db/testing/uow-contract.ts` have no
    unit (`uow-contract.ts` is imported by two progress files), so `@ou/` cannot name them. Owner: the platform/db test support (a unit to be declared in U4).
  - `apps/web/src/test/fixtures/progress-oracle.ts` has no unit. Owner: the testing unit (`testing-support`, if it
    covers `test/fixtures`; to be confirmed in U4).
  - `progress` imports `db-core` (`uow.ts`) and `catalog-application` (`testing/fake.ts`), but `units/progress/unit.json`
    `requires` lists neither. Owner: the progress lane, in a later manifest change; not changed in this mechanical PR.
