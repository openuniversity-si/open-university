# Step 3 plan: use cases

Target: every context has an application ring of use cases; `app/` (pages, layouts, route handlers, metadata and its
own helpers) reaches a context only through that ring; a use case owns its transaction, so a context's server code
receives a store bound to one transaction (D-059) and never imports its translator entry (D-057's allowance ends); the domain
imports only the domain; and checker rules refuse each regression with no exceptions. No visual or behavior change:
the rows stored, the release served, the responses and the pages rendered stay the same. Root causes and counts:
[STEP-03-audit.md](STEP-03-audit.md).

Every PR branches from `origin/mod/roadmap-integration`, targets it, has 3–8 commits, stays under the B5 size budget,
and ends with `Capability: CAP-008` and `Fit-Review: not reviewed (Daniel 2026-10-25: no review step)` (D-055).
`gate-db` needs Neon credentials this session does not have; a PR that moves a transaction is proven on the local
PostgreSQL 18 integration tests instead and says so.

## Target layout (D-058)

```
apps/web/src/<context>/
  domain/        rules and types; imports only domain/ (any context) and kernel/, plus pure packages
  ports/         contracts the application asks for; imports domain/ and kernel/
  application/   use cases: one exported function per thing a caller asks; takes ports from server/deps.ts; opens the transaction
  server/        adapters (vendor clients, Next cache wrappers, HTTP translation) and deps.ts, the composition root
  client/        client components
  testing/       doubles and contracts
```

- A **use case** is an exported function in `<context>/application/<name>.ts`, named for what its caller asks
  (`siteManifesto`, `viewerProgress`, `applyCatalogMutation`). It reads its ports from the context's composition root
  and, when several operations must commit together, calls the port's `transaction(work)`; the work receives the
  same port bound to one connection. The application ring imports its own `domain/`, `ports/` and `server/`, any
  context's `domain/` and `application/`, `kernel/` and `platform/observability/`. It does not import `next`,
  `react`, `platform/db`, another context's `server/` (that is a gateway in `server/`), `ui/` or `app/`.
- `app/` imports only `<context>/application/`, `<context>/domain/`, `<context>/client/`, `ui/`, `kernel/` and other
  `app/` files. Next.js calls that shape a response (`notFound`, `permanentRedirect`, `headers()`, `cookies()`) stay
  in `app/`.
- `admin/` is the admin HTTP API that dispatches to catalog, media and config. It gets an `admin/application/` ring
  for the three entry points `app/api/admin/*` calls; where `admin` belongs among the contexts is step 4.
- A context's server code that runs statements receives its context's store (D-059: the translator bound to one
  connection, named in `server/deps.ts`), never a database handle. Only composition roots import a translator entry
  (D-057 without its own-context allowance).
- A `domain/` file imports only `domain/` files, `kernel/` and the pure packages `zod` and `node:crypto`.

## PRs

| PR | What | Before → after | Root causes | Enforcement it adds |
|---|---|---|---|---|
| 3.1 | This audit and plan, D-058, CAP-008, `STATUS.md` | app 66, domain 6, own entry 40 (unchanged) | all (record) | `structure-check` covers the docs |
| 3.2 #421 | The domain imports only the domain: the generated token tables (`names.ts`, `values.ts`) move from `ui/tokens/` to `config/domain/theme/` (`tokens:generate` writes them there; `ui` reads them from there); `catalog/domain/transition.ts` becomes the first use case `catalog/application/transition.ts`; the `SourceDriver` contract moves to `playback/domain/source-driver.ts`; `playback/domain/types.ts` reads `./engine.ts`. `L3.context-layout` accepts the `application` ring | domain 6 → **0** | R1, R3 | `L3.domain-pure`, an allow list with no baseline, replaces the domain half of `L3.inner-pure`; `L1.no-backend-to-ui` takes its roots from the context list (adds `config`, `factory`) |
| 3.3 #422 | The checker resolves aliases from `apps/web/tsconfig.json` `compilerOptions.paths` instead of its own copy; `L3.app-application` refuses any `app/` edge outside the allowed rings, with a shrink-only baseline `scripts/lib/app-application-baseline.json` (a new edge fails; a listed edge that is gone fails until removed); `L4.query-consumers` is deleted, since the new rule covers it | app 66 → 66, all listed | R2 | rule + `check-architecture.test.ts` cases; a test that every tsconfig alias resolves to an existing file |
| 3.4 #423 | Site: `site/application/` serves the manifesto, the legal email and the build info; `guard.ts` (a Next 404/308 wrapper) moves to `app/` | app 66 → 48 | R1 | baseline shrinks |
| 3.5 #424 | Catalog projections: `public-routes.ts` and `metadata.ts` (pure) move to `catalog/domain/`; `progress-reading.ts` becomes `catalog/application/progress-reading.ts` (it value-imports the progress domain, which `L1.catalog-no-progress-value` keeps out of the catalog domain); `catalog/application/covers.ts` serves course and lesson covers and is the only importer of the `@tower/media` seam (**amended:** the alias stays, see below) | app 48 → 33 | R1 | baseline shrinks |
| 3.6 #425 | Progress and identity: `progress/application/` (the viewer's rows, saving progress) and `identity/application/` (the auth request, the verified session) | app 33 → 25 | R1 | baseline shrinks |
| 3.7 #426 | Catalog served reads and preview: page reads, preview token and route, draft claims, the health read (through a use case that is the only importer of the `@tower/catalog` seam) and the served theme through `config/application/` | app 25 → 19 | R1 | baseline shrinks |
| 3.8 #427 | Media revalidation and figure groups through `media/application/` | app 19 → 14 | R1 | baseline shrinks |
| 3.9 #428 | Admin API: `admin/application/` takes the catalog, media and config dispatch and their composition from `deps.ts`; the routes call one use case each | app 14 → 6 | R1 | baseline shrinks |
| 3.10 #429 | Platform from `app/`: robots facts, the preview origin, the request id and the CSP report through `site/application/`; the baseline is empty and deleted | app 6 → **0** | R1, R2 | `L3.app-application` stands with no baseline; `L3.application-boundary` refuses what a use case may not import |
| 3.11a #430 | Retire the eight direct media admin handlers (`handleAdminMedia*`) that duplicated the dispatcher path and only tests called; the tests go through the production dispatcher | own entry 40 → 40 (admin.ts keeps only a type import) | R1 | — (a deleted parallel path) |
| 3.11b #431 | Media store (D-059): `mediaStore(handle)` binds the media translator; `media/server/deps.ts` names `MediaStore` and returns the pool-bound store; media's reads, revalidation, admin actions, inheritance and institution covers take the store; the admin journal's participant and the catalog's media gateway bind a store to the catalog transaction through `storeConnection` in composition roots | own entry 40 → 32 | R1 | `L2.db-package`'s own-context allowance is limited to the catalog: a media file importing its entry fails |
| 3.12 #432 | Catalog store (D-059): `catalogStore(handle)` binds all 274 statement functions generically, with `transaction`, `readOnlySnapshot`, `afterCommit` and, on a transaction, `acquireLock`; `catalog/server/deps.ts` names `CatalogStore` and `CatalogTransactionStore`; a handler's `db` and a mutation's `tx` become stores; the small files move: `mutation`, `http`, `admin-journal`, `errors`, `common`, `misc`, `refs`, `list-projection`, `cover-kinds`, `lifecycle-refs`, `tables`, `draft`. **Bridge:** until 3.16 a catalog store is also the handle it wraps, so files not yet moved compile unchanged | own entry 32 → ~20 | R1 | — |
| 3.13 #433 | Catalog deletions and courses: `deletion`, `courses` | ~20 → ~18 | R1 | — |
| 3.14 #434 | Catalog editors: `lessons`, `reference`, `editions`, `lesson-slugs`, `texts` | 18 → 13 | R1 | — |
| 3.15 #435 | Catalog releases and batches: `batch-apply`, `bundle-apply`, `releases`, `release-routes`, `ship-batch`, `imports` | 13 → 7 | R1 | — |
| 3.16 #436 | Catalog reads and the rest: `doctor`, `home`, `authors`, `redirects`, `media-owners`, `read`, `page-reads`; the bridge is removed (a store is no longer a `Queryable`), and `L2.db-package` loses the own-entry allowance | 7 → **0** | R1 | `L2.db-package`: only composition roots import an entry |
| 3.17 #437 | Close: `runMutation` becomes `catalog/application/mutation.ts`; D-057 and D-058 marked proven, CAP-008 done, step metrics | — | all | every rule stands with no baseline |

**Amendment (PR 3.5):** `@tower/media` and `@tower/catalog` are not stale names to delete. `next.config.ts` resolves
them to the production adapters (`catalog/server/media.ts`, `catalog/server/read.ts`) or, in the test build, to the
fixtures (ADR-17), and the vitest config swaps `@tower/catalog` the same way. They stay as test-build seams; from 3.5
on, the only importer of each is the catalog use case that serves it, so `app/` never names an alias that reaches
`server/`. Replacing the seams with a composition root is step 4's (contexts and their composition).

3.2, 3.3, 3.10 and 3.16 change `scripts/check-architecture.mjs`, which the gate's unit stage runs, so their bodies cite
D-058. The catalog PRs 3.12–3.16 group files by the port they share; the estimates (~) are corrected in each PR's row
when it is opened, and a file that has to move with another group is recorded in the next PR's row, not left behind.

## Enforcement per root cause

| Root cause | Check that stops it recurring | PR |
|---|---|---|
| R1 no application layer | `L3.context-layout` has the `application` ring; `L3.app-application` sends `app/` through it; `L3.application-boundary` keeps frameworks and the database package out of it; `L2.db-package` without the own-context allowance makes the use case, through a port, the only owner of a transaction | 3.2, 3.3, 3.10, 3.16 |
| R2 no rule for `app/`, stale aliases | `L3.app-application` with no baseline after 3.10; aliases read from `tsconfig.json`, with a test that each resolves | 3.3, 3.10 |
| R3 domain rule as a deny list | `L3.domain-pure` lists what a domain file may import; `L1.no-backend-to-ui` derives its roots from the context list | 3.2 |

## Out of scope for step 3

- Where `admin` sits among the contexts, the contexts' services and the intents registry (step 4).
- Operations scripts under `apps/web/scripts/`: they are composition roots today and keep calling server functions;
  step 4 routes them through use cases or intents.
- Vendors (step 5), literals (step 6), the anti-mess structure rules beyond these (step 7).
- Integration and e2e tests, which may import any ring.

## Metrics

| Measure | Before (c95a8536) | Target after step 3 | After step 3 (measured on 3.17) |
|---|---|---|---|
| `app/` edges outside application, domain, client, `ui/`, `kernel/`, `app/` | 66 from 31 files (56 into `*/server`) | 0 | **0**; `L3.app-application` with no baseline |
| `domain/` edges outside the domain | 6 from 5 files | 0 | **0**; `L3.domain-pure` (allow list) |
| Files importing their own translator entry | 40 (catalog 32, media 8) | 0 | **0**; `L2.db-package` without the own-entry allowance |
| Contexts with an application ring | 0 | every context `app/` calls, plus `admin` | 6 (`catalog`, `site`, `identity`, `progress`, `config`, `media`) plus `admin`; 22 use-case files; `L3.application-boundary` |
| Checker aliases that resolve to a missing file | 2 of 3 | 0 (read from `tsconfig.json`) | **0** |
| Context code that receives a pool or a transaction handle | catalog and media server code | — | **0**: a store (D-059) is not a handle |
| Parallel implementations of the media admin API | 2 | — | 1 (3.11a deleted the direct handlers) |

Carried to step 4: where `admin` sits among the contexts; operations scripts, still composition roots; the
`@tower/media` and `@tower/catalog` test-build seams, now imported only by their use cases; the catalog handlers
other than the mutation, which still live in `server/` and are reached through the admin dispatcher.