# U3b platform: plan

Rewrite the cross-unit imports of the platform lane's files to `@ou/<target>/<path>` addresses (plan v3 §9.2 row U3b;
D-067 (1); D-069 items 8 and 11). Mechanical: no file moves, no renames, no behaviour change. The evidence is in
`docs/units/u3b-platform/audit.md`.

## Scope decision

The lane rewrites the **50 specifiers** that are outside the Node-run closure. The other **146** stay relative, because
`apps/web/package.json` runs the files that import them with plain `node scripts/<name>.ts`, and Node's native
TypeScript loader does not resolve `@ou/*` (the same constraint recorded by commit `3c0ffb84`). Those 146 are a
contract gap in the PR body, with the owner named there (the `@ou/*` resolver on the Node path is a tooling change).

## Commits, as a dependency graph

Each code commit owns the files of one importer unit. No file is owned by two commits, so the five code commits are
independent and could run in parallel; they are pushed one at a time on the shared branch (one push per commit).

```
[1 audit] -> [2 plan] -> { 3 db-contexts | 4 db-catalog | 5 db-media | 6 db-operations | 7 platform-runtime }
                                                         -> [8 retro, after the final gate]
```

1. Audit and plan documents (`docs/units/u3b-platform/audit.md`, `plan.md`). Done.
2. `db-contexts`: `db/admin/*`, `db/config/*`, `db/identity/index.ts`, `db/security/*` (9 files, 16 specifiers).
3. `db-catalog-io` and `db-catalog-store`: `db/catalog/queries.int.test.ts`, `db/catalog/store.test.ts` (2 files, 3 specifiers).
4. `db-media`: `db/media/*.test.ts` (4 files, 7 specifiers).
5. `db-operations`: `db/operations/migrations.test.ts` (1 file, 1 specifier).
6. `platform-runtime`: `host/request-address.ts`, `host/vercel.ts`, `host/vercel.test.ts`, `observability/logger.test.ts`
   (4 files, 6 specifiers).
7. `db-migrations`: no TypeScript importer; no commit. Recorded in the PR body.

Each commit: the rewrite of its own files only, then the targeted checks for that commit (below), then one push.

## Premises and blast radius

- **P-03** (a unit is addressed by `@ou/<id>` and the map is generated, U3a). Radius: medium. If wrong, a specifier
  does not resolve: `tsc`, vitest and Next fail at once, the gate stays red, and the commit is not pushed.
- **P-13** (an address never reaches into another unit's file). Radius: medium. If wrong, the `unit_addresses.check`
  structure check fails (the gate catches it); the scan validates each target before any edit.
- **Node-run closure** (Node cannot resolve `@ou/*`, so the closure keeps relative paths). Radius: high for scope,
  low for safety: keeping a path relative never breaks a run. If Node can resolve `@ou/*`, the 146 relative imports
  stay correct and the follow-up is a tooling change. It does not spend money, touch production or change the source of
  truth. Not CRITICAL.

No premise is CRITICAL. Nothing here touches production, secrets, the database, or Vercel.

## Targeted checks per commit

- Each commit: `apps/web` type-check (`tsc --noEmit -p .`) output compared with the baseline, the unit's own tests
  (`vitest run` on the changed `*.test.ts` files) and `scripts/units check`.
- Each commit also runs `scripts/unit-battery <id>` for the unit whose files it changed (tier 1).

## Final gate

After commit 6 and before the retro: merge `origin/mod/roadmap-integration` if it moved (merge, never rebase), then
`(. scripts/cloud/env.sh; OU_CREDENTIALS=network scripts/gate-dev --pr <N>)` with the exit code, wall time and each
stage time recorded. Merge only on a green gate-dev on the exact head, with `--match-head-commit`. No gate-db
(the change does not touch the database schema or migrations; `apps/web/drizzle/**` is unchanged).

Census (before and after, recorded in the PR body): the `tsc` output, the test file count (`git ls-files` matching
`*.test.ts`) and the test case count.

## Known base defects and their owners

- The timing-sensitive tests named in the brief (tower-catalog cover concurrency, read-latency) are not changed here.
  If only those fail: merge the base and gate again. Owner: the performance stage (H0).
- Vercel statuses on commits are not gates for this lane and are never awaited.

## D-069 items

- 8 (ownership): each rewrite is owned by its importer unit, and each target is addressed by its owner (`scripts/units owner`).
- 11 (small, trunk-based, reversible): seven small commits, each green alone, on a branch from the merged base.
