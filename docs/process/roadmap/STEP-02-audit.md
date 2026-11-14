# Step 2 audit: one database package

Roadmap step 2 of 8 (D-054). Audited on `mod/roadmap-integration` 657c8e11 (step 1 closed), 2026-10-25, by the
roadmap implementer session. A Torre's baseline audit (main 198aa130) was the starting hypothesis. Each finding is
verified, corrected or extended below with exact counts and file lists.

## How the counts were taken

- **SQL literal**: a string or template literal in production code whose text starts (after punctuation and
  whitespace) with upper-case SQL: `SELECT … FROM|pg_…(|$1`, `INSERT INTO`, `UPDATE <t> SET`, `DELETE FROM`,
  `WITH <t> AS (`, `LOCK TABLE`, DDL (`CREATE|ALTER|DROP TABLE…`, `TRUNCATE`) or a bare `BEGIN`/`COMMIT`/`ROLLBACK`.
  Upper case only: a first pass that ignored case counted HTTP route strings (`"DELETE /redirects"`) and help text as
  SQL and inflated the scripts count from 26 to 63.
- **Production** excludes `*.test.ts`, `*.int.test.ts`, `testing/` folders and `e2e/`. Integration tests seed and
  assert against the local PostgreSQL with SQL on purpose. They are out of the step's scope, and the plan keeps them
  out of the rule.
- **Import edge**: one `import`/`export … from`/`import()` whose specifier names `platform/db/<module>`, from a file
  outside `apps/web/src/platform/db/`.
- PR 2.2 turns this method into the checker rule `L2.db-package`, and its baseline
  (`scripts/lib/db-package-baseline.json`) is the reproducible count. **Correction (PR 2.2):** the rule found more than
  the first count, and the numbers below are the rule's. Its grammar also matches a `SELECT` whose `FROM` is built by a
  helper (`SELECT ${assetSelect(…)} ${assetFrom(…)}`, 6 more in `media/server/repository.ts`) and a bare
  `COMMIT`/`ROLLBACK` (2 more in `catalog/server/tables.ts`), so production `src` holds 381 literals, not 373. It resolves
  relative imports inside `platform/`, which adds `platform/security/rate-limit.ts`'s two `../db/…` imports: 72 edges
  from 56 files, the number A Torre reported.

## Baseline

| Measure | A Torre (198aa130) | Verified (657c8e11) |
|---|---|---|
| Production `src` files with SQL outside `platform/db` | — | **35** files, **381** SQL literals |
| Production `src` folders holding SQL | 7 (`SQL_OWNERS`) | 6 hold literals (`catalog`, `media`, `admin`, `config`, `progress`, `platform/security`) plus `platform/db`; `identity` holds none, but Better Auth runs SQL on 4 tables through the shared pool. The checker's table-owner map names 7 owners. |
| `apps/web/scripts` production files with SQL | — | **10** files, 36 literals (11 of them the migration ledger in `scripts/lib/migrations.ts`) |
| `apps/web/fidelity` production files with SQL | — | 1 file, 16 literals (the tooling database) |
| Import edges into `platform/db` from outside | 72 | **72** production edges from **56** files in `src`; 2 in `apps/web/scripts` (`lib/database-seed.ts`, `lib/migrations.ts`); 29 test edges from 24 test files |
| Database drivers | 2 | **2**: `pg` 8.23.1 (runtime, tests, most scripts) and `@neondatabase/serverless` 1.2.0 (`apps/web/scripts/lib/database-client.ts`, `scripts/lib/neon-runtime.cjs`), plus the `drizzle-orm/neon-serverless` adapter |
| Connections opened outside `platform/db/pool.ts` in production code | — | 0 in `src`; 10 in `apps/web/scripts` and `apps/web/fidelity` (8 through `createDatabaseClient`, 2 `new pg.Client`) |
| `check-architecture` violations | 0 | 0, and none of the above is reported |

## Findings

### F1. SQL lives in six context folders, not in the database package

Verified, and the spread is uneven: two thirds of it is one catalog file.

| Folder | Files | SQL literals | Files |
|---|---|---|---|
| `catalog/server` | 20 | 298 | `table-io.ts` (170), `reference.ts` (25), `projections-repo.ts` (15), `common.ts` (12), `editions.ts` (10), `media-owners.ts` (9), `releases.ts` (9), `imports.ts` (7), `mutation.ts` (7), `lesson-slugs.ts` (6), `redirects.ts` (6), `lifecycle-refs.ts` (4), `queries.ts` (4), `release-load.ts` (3), `admin-journal.ts` (2), `misc.ts` (2), `release-routes.ts` (2), `doctor.ts` (1), `refs.ts` (1), `tables.ts` (3) |
| `media/server` | 10 | 60 | `repository.ts` (15), `lifecycle.ts` (14), `asset-reads.ts` (11), `pending-deletions.ts` (10), `diagnose.ts` (4), `objects.ts` (2), `attach-set.ts`, `inheritance.ts`, `institution-cover.ts`, `media-locks.ts` (1 each) |
| `admin/server` | 1 | 11 | `jobs-repo.ts` |
| `config/server` | 1 | 6 | `repository.ts` |
| `progress/server` | 2 | 5 | `repo.ts` (3), `maintenance.ts` (2) |
| `platform/security` | 1 | 1 | `rate-limit.ts` (and 2 imports of `platform/db` internals) |
| `identity` | 0 | 0 | Better Auth issues its own SQL against `user`, `session`, `account`, `verification` through `appPool()` (`identity/server/config.ts`) |
| `platform/db` (the package) | 1 | 4 | `uow.ts` (transaction and advisory locks) |

Outside `src`, `apps/web/scripts` has 10 production files with 36 SQL literals:
`lib/migrations.ts` (11, the migration ledger), `lib/media-content-migrate.ts` (9), `ship-bench.ts` (4),
`db-fingerprint.ts` and `lib/legacy-snapshot.ts` (3 each), `lib/factory-bench.ts` (2), and `catalog-bake.ts`,
`fidelity-migrate-r2.ts`, `lib/media-migrate.ts`, `site-health.ts` (1 each). The two benches seed a local database with SQL.
`apps/web/fidelity/references/repository.ts` has 16 against the separate tooling database.

Why-chain:
1. 381 SQL literals sit in 35 files across six context folders.
2. Each context's server code receives a `query(sql)` handle and writes the SQL it needs where it needs it.
3. The database contract handed to contexts is `Queryable`/`UnitOfWork`/`DbPool` (`platform/db/uow.ts`), whose one
   method is `query(sql, values)`. Contexts re-export it under their own names (`MediaPool = DbPool` in
   `media/server/repository.ts`, `AdminPool = DbPool` in `catalog/server/mutation.ts`), and the identity port
   `session-database.ts` declares `query(sql)` itself.
4. The written rule puts SQL there on purpose: CAP-004 PR 5 says "Ports ask for an operation; SQL stays in the server",
   and `L2.sql-owner` maps each table to a context and accepts SQL anywhere inside that context.
5. Root cause **R1 (wrong abstraction and ownership)**: the database is offered as a SQL pipe, not as operations, and
   SQL is owned per context instead of by one package. Nothing says the database package owns every statement.

### F2. Callers import the package's internals

Verified: 72 production edges from 56 files (the first count said 70 from 55 because it missed two relative imports
inside `platform/`; corrected by PR 2.2's rule).

| Module imported | Production edges | Why callers import it |
|---|---|---|
| `uow` | 48 | the `Queryable`/`UnitOfWork`/`DbPool` types and `withUnitOfWork` |
| `pool` | 14 | `appPool()` itself, from `catalog`, `media`, `config`, `progress`, `identity` and `admin/deps.ts` |
| `database-env` | 6 | `hasDatabase()` / `buildWithoutDatabase()` |
| `limit` | 3 | the SQL `LIMIT` clamp |
| `errors` | 1 | the pg error mapping |

By folder: `catalog` 30 files, `media` 14, `admin` 3, `config` 3, `progress` 3, `identity` 2, `platform/security` 1.
Scripts: `lib/database-seed.ts` and `lib/migrations.ts` import it; `db-check.ts`, `lib/absolute-literals.ts` and
`lib/domain-literals.ts` only name its path in a string.

Why-chain:
1. 56 production files import five different `platform/db` modules.
2. They need the pool, the SQL handle, the env probe and the error map to run their own SQL.
3. Because the SQL is theirs (F1), the package's internals are their dependencies.
4. The package has no public surface: no entry module, and no rule says which file may import `platform/db`. The only
   restrictions are local: `L4.query-consumers` (pages under `app/`), `L6.factory-api-only` (the factory),
   `L3.inner-pure` (`domain/` and `ports/`) and a few named files.
5. Root cause **R2 (missing boundary)**: the package was never given an entry point and a list of allowed importers, so
   every importer is legal by default.

### F3. Two drivers

Verified. `pg` runs the application, the tests and most scripts. `@neondatabase/serverless` runs in two places:

- `apps/web/scripts/lib/database-client.ts`: `APP_DATABASE_OPERATIONS_TRANSPORT=neon-ws` swaps `pg.Client` for the Neon
  WebSocket client and `drizzle-orm/node-postgres` for `drizzle-orm/neon-serverless`. Nine scripts open their
  connection through it (`db-seed`, `db-fingerprint`, `db-legacy-snapshot`, `catalog-bake`, `lib/migrations`,
  `lib/media-cli`, `lib/database-seed`, `lib/legacy-snapshot`, `fidelity/references/connect`).
- `scripts/lib/neon-runtime.cjs`: a `--require` preload that replaces `pg.Pool` with `neon.Pool` inside the subject's
  `node_modules`. `scripts/lib/neon_pr.py` (gate-db) loads it; `neon_pr.py` and `neon_migrate.py` set the transport.

The reason is written in `docs/operations/database.md`: "The shared box blocks outbound TCP 5432". Both callers that
need it, `gate-db` and `neon-migrate`, are frozen (D-054) and cannot run in this roadmap. The local gate unsets the
variable (`scripts/gate-local`).

Why-chain:
1. Two drivers, and one of them is patched into the other at runtime.
2. Operations scripts on one box could not reach Neon over TCP 5432.
3. The workaround was put in code (a transport switch and a preload) instead of in the host (an egress rule) or the
   pipeline.
4. The lint rule that bans Neon transports from the application explicitly allows them in scripts ("Neon transports
   belong only in operations scripts", `apps/web/eslint.config.mjs`), so the second driver was legal by rule.
5. Root cause **R3 (host workaround made a code rule)**: a property of one machine became a supported code path, and no
   rule says tooling uses the application's driver.

### F4. The checker reports 0 because it looks for shapes, not for SQL

Verified, with four concrete holes.

- `L2.sql-owner` only reads files whose text contains `.query(`, and then checks that a statement's tables belong to the
  file's context. It allows SQL in every context by design; its table-owner map is the "7 owners".
- `catalog/server/doctor.ts` is in `L7.handler-no-sql`'s list, and runs raw SQL anyway: `LEGACY_MEDIA_SQL` is passed to
  `selectRows(db, sql)`, a generic pass-through in `table-io.ts`. The rule only searches for `.query(`.
- Per-file lists (`L7.handler-no-sql` names 12 files, `L4.job-boundary` and `L5.lifecycle` name one owner file each)
  do not cover a new file: a new `catalog/server/x.ts` with SQL passes every rule.
- `apps/web/scripts` and `apps/web/fidelity` are not checked for SQL or connections at all. `L1.single-pool` covers
  `src` only, while 10 connections are opened in scripts.

Why-chain:
1. The checker reports 0 violations while 381 SQL literals sit outside the database package.
2. Its rules test text shapes (`.query(`, a file name in a list) instead of the property (a SQL statement, a location).
3. Each rule was written to stop the last incident in the files of that incident.
4. There was no target layout for SQL to check against, only "the table belongs to this context".
5. Root cause **R4 (missing gate)**: no rule states where SQL may live, so the checks are lists of incidents. This is
   the database half of step 1's R7; the rest of R7 stays in step 7.

### F5. D-036's edition language belongs to this step

Carried from step 1 (PR 1.6, #393). An edition's `language` is still nullable (`schema.ts`
`language: text("language")`). D-036 asks for a backfill from the course and then `NOT NULL`. It is a migration and a
data rewrite of the one database package, queued as Q-02. It has no root cause of its own in this step; the plan gives
it a PR.

## Root causes

| Id | Root cause | Kind | Findings |
|---|---|---|---|
| R1 | The database is offered as `query(sql)`, and SQL is owned per context (CAP-004 PR 5, `L2.sql-owner`) | wrong abstraction, unclear ownership | F1 |
| R2 | `platform/db` has no entry module and no list of allowed importers | missing boundary | F2 |
| R3 | A box's blocked port became a second driver; lint allows Neon in scripts | host workaround made a code rule | F3 |
| R4 | No rule says where SQL may live; checks are per-incident text shapes | missing gate | F4 |

The plan ([STEP-02-plan.md](STEP-02-plan.md)) names the check that closes each one.
