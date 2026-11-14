# AR1 audit: the `database` gate area

Base: `mod/roadmap-integration` at `efc7f3b4`. Read-only evidence, no suite run.

## What exists

- `scripts/lib/gate-areas.json`, area `database` (groups `gate-db`): besides the schema, migration, Neon and
  database-script paths it lists whole-tree globs `apps/web/src/{platform,kernel,catalog/admin,catalog/server,
  release/server,media,admin,auth,identity/server,progress,app/api}/**`. Any change under them sets `dbRequired`.
- `scripts/lib/gate_areas.py` matches areas by glob only. `plan_for(paths, packages)` has no access to file contents.
- Readers: `gate_policy.select_dev_plan` (root, base, head known), `gate_policy.classify_pr` (`db_paths`),
  `gate_batch` (through `select_dev_plan`), `gate-runner.sh` (reads the plan JSON only), `defect_router`,
  `gate_result_cache`, `premises` (`glob_match` only). `gate-db.test.sh` (HD1) copies `gate_areas.py` and
  `gate-areas.json`; it must keep working with the files as copied.
- The db layer: `apps/web/src/platform/db/**` (drizzle client, pool, schema, uow), `apps/web/drizzle/**`
  (migrations), packages `drizzle-orm`, `drizzle-kit`, `@neondatabase/*`, `pg`, `postgres`. tsconfig aliases
  `@ou/db-*` map into `src/platform/db` and `drizzle`; `@/*` maps to `src/*`.
- On the base, 111 files outside `src/platform/db` name a db specifier (regex over `platform/db`, `@ou/db-`,
  `drizzle-orm`, `@neondatabase/`).

## Cited sources checked (brief standard v2 (2))

- PR #607 exists (head `f3f77b4b` per brief), 15 code files under `apps/web/src/admin/**`.
- Premise in the brief is partly wrong: 2 of the 15 files import the db layer directly.
  `admin/server/deps.ts` imports `../../platform/db/{security,admin,catalog}/index.ts` (on #607:
  `@ou/db-contexts/...`, `@ou/db-catalog-store/...`) and `admin/server/http-dispatcher-next.test.ts` imports
  `../../platform/db/security/index.ts`. Under the goal's rule (b) they are `database`; the other 13 are not.
  So #607 stays `db=1` after this unit because it edits the import lines of a db-importing file. Reported, not hidden.
- `apps/web/src/catalog/server/table-io.ts` (listed in the area) no longer exists.
- `config/registry/gate.json` is in KF3's diff: AR1 registers its keys in a new owner file
  `config/registry/gate-areas.json` instead.

## Fences

BD1 (#667), LP1, KF3 (#665) files untouched. `gate-db.test.sh` (HD1) read-only.
