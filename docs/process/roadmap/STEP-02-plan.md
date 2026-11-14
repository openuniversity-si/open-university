# Step 2 plan: one database package

Target: every SQL statement in production code and operations scripts lives in `apps/web/src/platform/db/`, as a
translator behind a port of the context that owns its tables; nothing outside the package imports its internals; one
driver (`pg`) everywhere; and a checker rule refuses any regression. No visual or behavior change: the rows stored, the
release served and the pages rendered stay the same. Root causes and counts: [STEP-02-audit.md](STEP-02-audit.md). Counts are `L2.db-package`'s (PR 2.2).

Every PR branches from `origin/mod/roadmap-integration`, targets it, has 3–8 commits, stays under the B5 size budget,
and ends with `Capability: CAP-007` and `Fit-Review: not reviewed (Daniel 2026-10-25: no review step)` (D-055).
`gate-db` needs Neon credentials this session does not have; each database PR is proven on the local PostgreSQL 18
integration tests instead and says so.

## Target layout (D-056)

```
apps/web/src/platform/db/
  pool.ts uow.ts errors.ts limit.ts database-env.ts schema.ts   package internals (unchanged roles)
  migrations/                                                     migration runner and ledger (from scripts/lib/migrations.ts)
  config/  progress/  identity/  security/  admin/  media/  catalog/  tooling/
    <name>.ts                                                     translators: SQL + row mapping, one port each
    index.ts                                                      the entry: binds translators to the pool
```

- A **translator** implements a port from `<context>/ports/`. Each port method is an operation in the context's words
  (`read(kind)`, `commit(revision)`, `lockConfig(kind)`), never `query(sql)`. When a context needs several operations
  in one transaction, its port declares `transaction(work)` and the work receives the same port bound to one
  connection. Advisory locks become named operations.
- A translator may import its context's `ports/` and `domain/` (types and pure functions) and `kernel/`. The package
  root stays as today: it imports only `kernel/` and `platform/`.
- Outside the package, only `platform/db/<context>/index.ts` and `platform/db/database-env.ts` may be imported, and
  only by a composition root (a `deps.ts`, a `*-gateway.ts`, D-057) or an operations script under `apps/web/scripts/`.
  Until step 3, a context's own code may also import its own entry (D-057). `Queryable`,
  `UnitOfWork`, `DbPool` and `AppPool` are not exported past the package.
- Table ownership (`L2.sql-owner`'s map) is checked on the folder: SQL in `platform/db/catalog/` touches only catalog
  tables, and so on. A statement that joins two owners is an operation of one port that reads the other through its
  port, or it is recorded in the plan of the PR that moves it.
- Test doubles implement the context ports. `platform/db/testing/uow-contract.ts` runs each port's contract against
  the in-memory double and the real translator.

## PRs

| PR | What | Before → after (SQL literals outside the package, production `src`) | Root causes | Enforcement it adds |
|---|---|---|---|---|
| 2.1 | This audit and plan, D-056, CAP-007, `STATUS.md` | 381 → 381 | all (record) | `structure-check` covers the docs (links, decision and capability formats) |
| 2.2 | `L2.db-package` in `scripts/check-architecture.mjs`: a SQL literal (the audit's grammar, no `.query(` precondition), a `pg`/`drizzle-orm` import, a connection, or an import of a `platform/db` internal outside the package, in `src`, `apps/web/scripts` and `apps/web/fidelity`; `@neondatabase/*` anywhere. Existing cases are listed in `scripts/lib/db-package-baseline.json`: a new case fails, and a listed case that no longer occurs also fails until it is removed, so the list only shrinks | 381 → 381, all listed | R2, R4 | checker rule + `check-architecture.test.ts` cases (new file with SQL refused, pass-through like `selectRows(db, sql)` refused, stale entry refused) |
| 2.3 | One driver: `database-client.ts` opens `pg.Client` only; delete `neon-runtime.cjs`, the `neon-ws` transport, `APP_DATABASE_OPERATIONS_TRANSPORT` from `neon_pr.py`/`neon_migrate.py`, `drizzle-orm/neon-serverless`, and `@neondatabase/serverless` from `package.json`; the eslint ban covers scripts too; queue Q-07 (the release host reaches PostgreSQL over TCP); update `docs/operations/database.md` | unchanged; drivers 2 → 1 | R3 | `L2.db-package` refuses `@neondatabase/*` with no baseline entry; lint ban in every folder |
| 2.4 #398 | Config: `config/server/repository.ts` → `platform/db/config/documents.ts` behind the unchanged `ConfigDocuments` port (its lock stays inside the translator's `commit` transaction); `platform/db/config/index.ts` is the entry; `deps.ts` is its only importer and `read.ts` takes the port from it; cache tags move to `invalidate.ts` to avoid a cycle | 381 → 375 | R1, R2 | baseline shrinks; `L1.platform-down` lets a translator read only its own context's `ports/` and `domain/`; `L2.sql-owner` takes the owner from the translator folder |
| 2.5 #399 | Progress records: `progress/server/repo.ts` → `platform/db/progress/records.ts` behind `ProgressRepositoryPort`; `progress/server/deps.ts` is the composition root; `ProgressDatabase` (a `query(sql)` interface) is deleted | 375 → 372 | R1, R2 | baseline shrinks |
| 2.5b #400 | Rate limit and identity: the admin limiter's counter → `platform/db/security/` and its entry builds the `adminRateLimiter` singleton; Better Auth's storage comes from `platform/db/identity/` through `identity/server/deps.ts`; `identity/ports/session-database.ts` (a `query(sql)` interface) is deleted | 372 → 371 | R1, R2 | baseline shrinks; `L2.sql-owner` maps `admin_rate_limits` to `security` and `rate_limit` to `identity` |
| 2.6 #401 | Admin jobs: `admin/server/jobs-repo.ts` → `platform/db/admin/jobs.ts`, behind `JobStorePort` (which gains `actorOf`); `AdminCatalogDeps.jobs(participant)` is bound in `catalog/server/deps.ts`. `admin/http-dispatcher.ts` (the catalog mutation's `UnitOfWork` participant) and `admin/deps.ts` (`catalogAdminJournal(appPool)`) keep their imports until the catalog transaction moves in 2.10 | 371 → 360 | R1, R2 | baseline shrinks; `L4.job-boundary` names the folder, not the file |
| 2.7 #402 | Media, pure SQL modules: `lifecycle.ts`, `media-locks.ts`, `pending-deletions.ts` → `platform/db/media/`; D-057 (gateways are composition roots; a context may import its own entry until step 3); `StorageError` moves to `media/domain/` | 360 → 335 | R1, R2 | baseline shrinks; `L5.lifecycle` and the cover rules name the translator folder |
| 2.7b #403 | Media records: `repository.ts` (statements, row mapping and the locking transaction) → `platform/db/media/records.ts`; its handle names (`MediaPool`, `MediaDatabase`) move to the media entry, the D-057 surface until step 3; former importers keep loading `public-hosts.ts`; `MediaConflictError` moves to `media/domain/` | 335 → 320 | R1, R2 | baseline shrinks; `L2.admin-spec-pure` and `L2.cli-api-boundary` refuse any `platform/db` path |
| 2.7c #404 | Media objects: `readObjects`/`registerObject` → `platform/db/media/objects.ts`; image inspection and the object store stay in `media/server/objects.ts` | 320 → 318 | R1, R2 | baseline shrinks |
| 2.8 #404 | Media, reads: `asset-reads.ts`, `diagnose.ts`, `attach-set.ts` move whole; the statements of `inheritance.ts` and `institution-cover.ts` become `deleteLessonMedia`/`deactivateInstitutionCover`; the entry names `MediaTransaction` | 318 → 300 (measured) | R1, R2 | baseline shrinks; `src/media` has no SQL |
| 2.8b #405 | The pool from composition roots: one package-level server entry `platform/db/server.ts` (`applicationDatabase()`, a `DbPool` without the driver type; composition roots only), so `media/server/index.ts` and `revalidate.ts` (through a new `media/server/deps.ts`) and the admin and catalog `deps.ts` stop importing `pool.ts`/`database-env.ts`; the media translator entry stays free of `server-only` because Node scripts import it | 298 → 298 | R2 | baseline shrinks (import cases); checker test for the server entry |
| 2.9a #406 | Catalog projections and queries: `projections-repo.ts` → `platform/db/catalog/projections.ts` (its dead `readScopedCourseState` deleted; `selectCoursePage` takes the provider from its caller), `queries.ts` → `platform/db/catalog/queries.ts` | 300 → 281 | R1, R2 | baseline shrinks; `L4.projection-boundary`, the health-route rule and `L4.query-consumers` name the translator |
| 2.9b #407 | Catalog release writes and routes: the statements of `releases.ts`, `release-routes.ts`, `redirects.ts` → `platform/db/catalog/releases.ts` and `redirects.ts`; the handlers keep compile, cut, validation, audit and messages | 281 → 264 | R1, R2 | baseline shrinks |
| 2.10a #408 | Catalog journal and shared state: the statements of `mutation.ts` (audit, idempotency, row and release locks), `common.ts` (revisions, paths, redirects, positions), `admin-journal.ts`, `misc.ts` → `platform/db/catalog/journal.ts`, `state.ts`, `redirects.ts`; `runMutation` and the handler contracts stay in `mutation.ts` | 264 → 241 | R1, R2 | baseline shrinks |
| 2.10b #409 | Catalog editors: the statements of `editions.ts`, `lesson-slugs.ts`, `imports.ts` → `platform/db/catalog/editions.ts`, `lesson-slugs.ts`, `imports.ts`; the catalog's handle types (`AdminPool`, `Tx`) move to the entry with the last catalog cut (2.12) | 241 → 218 | R1, R2 | baseline shrinks |
| 2.11a #410 | Catalog owner rows, lifecycle refs, batch refs, export snapshot, doctor names (the `selectRows` pass-through deleted) → `platform/db/catalog/`; progress maintenance → `platform/db/progress/`, reached through `catalog/server/progress-gateway.ts` | 218 → 198 | R1, R2, R4 | baseline shrinks; `L3.no-retired-paths` exempts the doctor translator; `progress` has no SQL and no `platform/db` import |
| 2.11b #411 | Catalog reference data: the statements of `reference.ts` (licenses, sources, areas, subareas) → `platform/db/catalog/reference.ts`; `L7.handler-no-sql` and its 12-file list deleted | 198 → 173 | R1, R2, R4 | baseline shrinks; `L2.db-package` replaces the per-file list |
| 2.12 #412 | Catalog tables: `table-io.ts`, `release-load.ts`, `row-institution.ts` move whole into `platform/db/catalog/`; the video statements take the provider from a catalog playback gateway; the SQL grammar counts aliased UPDATEs | 173 → 0 | R1, R2, R4 | baseline shrinks; `L4.projection-boundary` names only the translator; no SQL left in `src` |
| 2.12b #413 | Catalog handles and internals: the limiter moves to `kernel/concurrency.ts`; the catalog entry names `CatalogDatabase`/`CatalogTransaction`/`CatalogPool`/`CatalogClient` and exposes `withUnitOfWork` and `fromDatabaseError`; `page-reads.ts`, `read.ts`, `draft.ts`, `doctor.ts` take the pool, build probe and pressure from `catalog/server/deps.ts`; the admin dispatcher's participant is named through admin's media gateway | 0 → 0 (import cases 37 → 2) | R2 | baseline has no `src` entry |
| 2.13a #414 | Operations layer: `scripts/lib/database-client.ts`, `migrations.ts`, `database-seed.ts` → `platform/db/operations/` (`DatabaseToolError` as an `AppError`; the client's statement timeout is `LIMITS.operationsStatementMs`); the fidelity tooling counts as a composition root | scripts SQL 36 → 25 | R1, R2, R3 | baseline 20 → 14; the gate's database area keeps covering the files through `apps/web/**/db/**` |
| 2.13b #415 | Tooling database: `fidelity/references/repository.ts` → `platform/db/tooling/references.ts` (`NoActiveReferenceSetError` as an `AppError`); `fidelity-migrate-r2.ts` reads through `referenceImageRows` | tooling SQL 16 → 0, scripts 25 → 24 | R1 | baseline 14 → 12 |
| 2.13c #416 | Remaining scripts: `catalog-bake`, `site-health`, `ship-bench`, `db-fingerprint`, `media-migrate`, `factory-bench` call translator functions; `legacy-snapshot.ts` moves into `platform/db/operations/`; no own `pg` client is left | scripts SQL 24 → 9; drivers and connections 4 → 0 | R1, R3 | baseline 12 → 1 |
| 2.13d #417 | `media-content-migrate.ts`: media statements → `platform/db/media/content-migration.ts`, catalog cover reads and lock → `platform/db/catalog/owner-rows.ts`; the cross-owner `LOCK TABLE` becomes media's lock then the catalog's, same order and transaction | scripts SQL 9 → 0 | R1 | baseline 1 → **0** |
| 2.14 #418 | D-036: migration `0034_edition_language_required` backfills an edition's language from its course and makes it NOT NULL (local test database only; Q-02 for the host swap); the edition inserts take the course's language in the same statement; `structure-check` refuses a journal `when` that is not after the previous one | — | — (carried) | the migration-order and queue checks from step 1, plus the `when` order; `edition-language.int.test.ts` |
| 2.15 #419 | Close: the baseline file is empty and deleted; `L2.sql-owner` folds into `L2.db-package` (the owner check reads only `platform/db`: a translator folder touches its own context's tables, the package root none); D-056 marked proven; step metrics | 0 → 0 | all | the rule stands with no exceptions |

2.2 and 2.3 change gate-adjacent files (`check-architecture.mjs` is run by the gate's unit stage; `neon_pr.py` and
`neon_migrate.py` are tail files), so their bodies cite D-056. Order: 2.1 → 2.2 → 2.3 → 2.4 … → 2.15. 2.14 may move
earlier if a later PR needs the column required. A PR that finds a cross-owner statement it cannot split records it in
its body and in the next PR's row, not in a baseline that grows.

## Enforcement per root cause

| Root cause | Check that stops it recurring | PR |
|---|---|---|
| R1 the database is offered as `query(sql)`; SQL owned per context | `L2.db-package` refuses SQL outside `platform/db`; the SQL-shaped types are not exported past the package; the same rule checks table owners per translator folder; CAP-004 PR 5 replaced by D-056 | 2.2, 2.4–2.13, 2.15 |
| R2 `platform/db` has no entry or allowed importers | `L2.db-package` refuses any import of a package internal, and any import of an entry from a file that is not a composition root or an operations script | 2.2 |
| R3 host workaround became a second driver | `L2.db-package` and the eslint ban refuse `@neondatabase/*` in every folder; Q-07 makes TCP to PostgreSQL a property of the release host | 2.3 |
| R4 no rule says where SQL may live | `L2.db-package` detects SQL by its grammar in every production file, with no baseline since 2.15, and covers `apps/web/scripts` and `apps/web/fidelity` | 2.2, 2.15 |

## Out of scope for step 2

- Removing D-057's own-context allowance: step 3 moves transactions into use cases, so a context's server code stops
  importing its own translator entry and only composition roots import one.

- Use cases and where a transaction starts (step 3). Step 2 keeps each transaction where it is today and moves only
  its statements behind the port.
- Context boundaries and the intents registry (step 4); other vendors (step 5); literals inside SQL (step 6 keeps
  D-050's `EXTENT`/`LIMITS` as they are).
- Integration and e2e tests that use SQL on the local test database.
- The local test-server scripts in `scripts/cloud/` (they create the test database, not application data).

## Metrics

| Measure | Before (657c8e11) | Target after step 2 | After step 2 (measured on 2.15) |
|---|---|---|---|
| SQL literals outside `platform/db`, production `src` | 381 in 35 files | 0 | 0 |
| SQL literals in `apps/web/scripts` and `apps/web/fidelity` outside `platform/db` | 36 in 10 files; 16 in 1 file | 0 | 0; 0 |
| Production import edges into `platform/db` internals from outside | 72 from 56 files (2 more in scripts) | 0; entries imported only by composition roots and operations scripts | 0; entries imported by composition roots, operations scripts and, until step 3 (D-057), 40 files of the entry's own context |
| Database drivers | 2 | 1 (`pg`) | 1 (`pg`) |
| Checker rules that know where SQL may live | 0 (`L2.sql-owner` checks owners inside each context) | 1 (`L2.db-package`), with no baseline | 1 (`L2.db-package`, table owners included), with no baseline |
