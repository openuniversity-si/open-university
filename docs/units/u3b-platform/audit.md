# U3b platform: audit

Read-only evidence for the platform lane's import rewrite (plan v3 §9.2, row U3b; D-067 (1); D-069 items 8 and 11).
Base: `origin/mod/roadmap-integration` at `a2c09043` (includes U0 #509, U3a, CO1 #576 and the other U3b lanes).

## Scope

The lane owns eight units (`units/<id>/unit.json`, `owner: platform-lane`): `db-catalog-io`, `db-catalog-store`,
`db-contexts`, `db-core`, `db-media`, `db-migrations`, `db-operations`, `platform-runtime`. `scripts/units owner <path>`
confirms each file has one unit.

`scripts/units addresses --json`, filtered to importers whose file belongs to a lane unit (a throwaway scan in the
session scratchpad, not committed):

- 196 specifiers in 67 lane files name another unit's file by path (relative, `../`, or `./` into a sibling unit).
- Every target unit that these specifiers name has an `@ou/<id>` address (`apps/web/tsconfig.json`, generated). No
  target is without an address.
- `db-migrations` has no TypeScript importer (`apps/web/drizzle/**` holds SQL and metadata). Nothing to rewrite.
- No `@/`, `@tower/` alias import and no path-based `vi.mock` / `require` in lane files. The only `vi.mock` calls are
  for `server-only` and `next/cache` (packages, not units).

## The Node-run closure (the constraint that decides the scope)

`apps/web/package.json` runs 27 TypeScript scripts with plain `node scripts/<name>.ts` (`db:migrate`, `db:seed`,
`db:check`, `db:fingerprint`, `postinstall` → `catalog-bake.ts`, `build` → `static-home-check.ts`, …). Node's
native TypeScript loader does not read tsconfig `paths`, so an `@ou/` specifier there fails with
`ERR_MODULE_NOT_FOUND`. The same failure was recorded by the config lane (commit `3c0ffb84`, D-069 item 7).

Walking the static import graph from those 27 entries (`scripts/lib/unit_map.py` `Code.resolve_import`) reaches
**146 of the 196 specifiers** (most of `db/catalog`, `db/media`, `db/operations`, `db/checks.ts`, `db/pool.ts`, `db/uow.ts`
and the kernel files they load). Those importers must keep relative paths until Node can resolve `@ou/*`, which is a
tooling change in the owner's files, not in this lane.

So the lane can rewrite **50 specifiers** outside that closure, in 30 files. The other 146 are listed in the PR body
as a contract gap (`@ou/*` resolver on the Node path, D-069 item 7).

## Validation of each target

For each of the 50 specifiers the scan computed the new address `@ou/<owner>/<path under the owner's home>` and
checked it with `scripts/lib/unit_addresses.py` `resolve()`: the address must resolve to the same file, and that file
must belong to the target unit alone. All 50 pass; none is an export gap. (A target that is not exported through its
address would be a gap for that unit's U4, and no other unit is edited here.)

## Test and type-check census (before)

- `apps/web/tsconfig.json` type-check baseline: `tsc --noEmit -p apps/web` (output in the PR body, identical after).
- Test census: test files and test cases in the lane are unchanged by import rewriting; the count is recorded in the
  PR body before and after with `vitest list` (no test file is added, removed or renamed).

## Known base defects that could interfere

- The timing-sensitive tests named in the brief (tower-catalog cover concurrency, read-latency) are not touched and not
  changed. If only those fail, the rule is merge `origin/mod/roadmap-integration` and gate again.

## Premises checked (cheap evidence only)

- P-03 (units are addressed by `@ou/<id>`): holds for every target here; the map is generated (U3a).
- P-13 (an address never reaches into another unit): holds; `scripts/lib/unit_addresses.py` `check` is the enforcer.
- The Node-run closure premise (above) is the one that changes scope. Verified by reading `apps/web/package.json` and
  the import graph, not by running the scripts.
