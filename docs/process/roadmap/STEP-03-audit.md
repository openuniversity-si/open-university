# Step 3 audit: use cases

Roadmap step 3 of 8 (D-054). Audited on `mod/roadmap-integration` c95a8536 (step 2 closed), 2026-10-25, by the
roadmap implementer session. A Torre's baseline audit (main 198aa130) was the starting hypothesis. Each finding is
verified, corrected or extended below with exact counts and file lists.

## How the counts were taken

- **Edge**: one `import`/`export … from`/`import()` resolved by the architecture checker's own graph
  (`scripts/check-architecture.mjs`, `checkArchitecture({ rules })`), from a production file (not `*.test.ts`, not
  `testing/`, not `app/(test)/`). The tsconfig aliases are resolved as `apps/web/tsconfig.json` declares them, not as
  the checker's copy does (see F2).
- **Server module**: a file under `<context>/server/`. **Outside the domain**: a target that is neither a `domain/` file
  (of any context) nor `kernel/`. `zod` and `node:crypto` are pure and not counted.
- **Own translator entry**: an import of `platform/db/<context>/index.ts` from a file of that same context that is not a
  composition root (`deps.ts`, `*-gateway.ts`), the allowance D-057 grants until this step.
- PR 3.2 turns these measures into checker rules, and their counts become the reproducible numbers.

## Baseline

| Measure | A Torre (198aa130) | Verified (c95a8536) |
|---|---|---|
| `app/` edges into `*/server` modules | 48 | **56** edges from 28 files (48 written as `@/…/server/…`, 8 more through the `@tower/media` and `@tower/catalog` aliases the checker resolves to files that do not exist) |
| `app/` edges into anything but an application layer, domain, client, `ui/`, `kernel/` or `app/` | — | **66** edges from **31** files: the 56 above, 4 into `admin/` root modules, 6 into `platform/` |
| An application layer (use cases) | — | **none**: no context has one; `L3.context-layout` allows only `domain`, `ports`, `server`, `client`, `testing` |
| `domain/` edges outside the domain | 6 files | **6** edges from **5** files: 2 into `ui/tokens`, 4 into a `ports/` module |
| Files importing their own translator entry (D-057 allowance) | — | **40** (`catalog/server` 32, `media/server` 8), calling 282 distinct catalog and 21 distinct media statement functions with a transaction handle |
| Files where a transaction starts outside `platform/db` | — | 4 call `withUnitOfWork` (`catalog/server/mutation.ts`, `bundle-apply.ts`, `admin-journal.ts` twice); `media/server/actions.ts` and `admin/http-dispatcher.ts` pass a `MediaTransaction` participant |
| `check-architecture` violations | 0 | 0, and none of the above is reported |

## Findings

### F1. Pages and routes call server modules directly

Verified and extended: 66 edges, not 48. A Torre's count matched the text `/server/`; the aliases and the `admin/` and
`platform/` modules add 18.

| Target | Edges | Importers |
|---|---|---|
| `site/server/site-data.ts` | 15 | every public page, `layout.tsx`, `manifest.ts` |
| `site/server/guard.ts`, `build-info.ts` | 3 | course and lesson layouts (a Next 404/308 wrapper), `api/health` |
| `catalog/server/media.ts` (as `@tower/media`) | 7 | home, authors, universities, course and lesson views, signed-in home |
| `catalog/server/public-routes.ts`, `progress-reading.ts`, `metadata.ts` | 8 | course and lesson layouts and views, `sitemap.ts`, signed-in home. All three are pure functions of the release: domain code filed under `server/` |
| `catalog/server/page-reads.ts`, `preview-token.ts`, `preview-route.ts`, `draft.ts`, `read.ts` (as `@tower/catalog`), `media-owners.ts` | 6 | `catalog-preview.ts`, `api/catalog/preview`, `layout.tsx`, `api/health`, `api/media/revalidate` |
| `catalog/server/routes.ts`, `deps.ts`; `config/server/admin.ts`, `deps.ts`, `read.ts` | 5 | the admin catalog and config routes, `layout.tsx` (served theme) |
| `admin/deps.ts`, `http-dispatcher.ts`, `auth.ts`, `route-specs.ts` | 4 | the admin catalog and media routes |
| `progress/server/viewer.ts`, `handler.ts` | 6 | signed-in pages, course and lesson views, `api/progress` |
| `identity/server/handler.ts`, `session.ts` | 2 | `api/auth`, `api/progress` |
| `media/server/group.ts`, `revalidate.ts`, `invalidate.ts` | 4 | course and lesson views, `api/media/revalidate` |
| `platform/host/vercel.ts`, `observability/context.ts`, `observability/logger.ts`, `security/csp.ts` | 6 | `robots.ts`, `api/progress`, the admin catalog route, `api/csp-report` |

`app/` also imports `domain/` (33 edges into `site/domain`, 12 into `catalog/domain`, 2 more), `client/` components,
`ui/` and `kernel/`. Those are pure values, types and presentation, and stay allowed.

Why-chain:
1. 31 files under `app/` reach 33 different server, admin and platform modules through 66 edges.
2. The functions a page or route needs (the site manifesto, a course's covers, the viewer's progress, an admin
   dispatch) exist only in those modules; nothing else offers them.
3. A context's `server/` ring is both its adapters (repositories, vendor clients, Next cache wrappers) and the only
   place callers can find an operation. Pure projections (`public-routes.ts`) and framework wrappers (`guard.ts`) land
   there too, because it is the folder callers already import.
4. The layout adopted with CAP-004 (rings since 3.1) names `domain`, `ports`, `server`, `client` and `testing`. It was
   designed to keep vendors behind ports; it never named the layer that answers a caller and owns a transaction, so
   `app/` was left to compose adapters itself.
5. Root cause **R1 (missing abstraction)**: there is no application layer. No ring holds the use cases, so `server/`
   is the de-facto public API of every context and the transaction starts wherever the code happens to be (F4).

### F2. The checker cannot see what `app/` imports

Verified, with three holes.

- No rule says what `app/` may import. `L4.query-consumers` refuses three shapes (the full catalog read, `table-io`,
  `pg`/`platform/db`), the incidents it was written for. Any other server module passes.
- The checker keeps its own alias map, and it is stale: `@tower/media` resolves to `media/index.ts` and
  `@tower/catalog` to `catalog/read.ts`, files that no longer exist. `apps/web/tsconfig.json` points them at
  `catalog/server/media.ts` and `catalog/server/read.ts`. Every rule therefore misses the 8 edges written through
  those aliases.
- `L3.context-layout` rejects any ring other than the five, so a context cannot add an application ring today without
  failing the check.

Why-chain:
1. The checker reports 0 while 66 `app/` edges bypass any application layer.
2. It has no rule for `app/`'s imports and resolves 8 of them to files that do not exist.
3. The alias table was copied into the checker when it was written and never compared with `tsconfig.json`; app
   restrictions were added per incident.
4. The checker reads two sources of truth (its own aliases, its own ring list) instead of the project's, and no test
   compares them.
5. Root cause **R2 (missing gate, duplicated configuration)**: no rule states what `app/` may import, and the checker
   resolves imports from a private copy of the project's configuration.

### F3. Domain files import ports and UI

Verified and corrected: 6 edges from 5 files (A Torre's "6 files" counted edges).

| File | Imports | Why it is wrong |
|---|---|---|
| `config/domain/documents.ts` | `ui/tokens/names.ts`, `ui/tokens/values.ts` | The theme document's contract (D-051, D-052) reads the generated token tables, which are filed under `ui/` |
| `catalog/domain/transition.ts` | `catalog/ports/commands.ts` (`CatalogStatePort`) | A status transition that reads state through a port and writes through a port is a use case, not a rule |
| `playback/domain/drivers/youtube.ts`, `institutional-url.ts` | `playback/ports/source-driver.ts` | The `SourceDriver` contract is declared in `ports/` and implemented by pure validators in `domain/` |
| `playback/domain/types.ts` | `playback/ports/engine.ts` | The port re-exports `domain/engine.ts`; the domain reads its own type back through the port |

Why-chain:
1. 5 domain files import outside the domain.
2. Each needs a type or table that is filed in another ring: theme tokens under `ui/`, a driver contract under
   `ports/`, a transition that needs state.
3. The rules allowed it. `L3.inner-pure` refuses only `server/`, `client/` and `testing/` targets (and frameworks,
   `platform/`, JSON). `L1.no-backend-to-ui` lists top-level folders by hand and omits `config` and `factory`.
4. Both rules are deny lists written for past incidents; a new kind of target (`ui/`, `ports/`, `app/`) is allowed
   until someone adds it. There is also no place for the transition to go, because there is no application ring (R1).
5. Root cause **R3 (rule as a deny list)**: the domain rule says what the domain may not import instead of the only
   things it may import (`domain/`, `kernel/`, pure packages). Ownership of the generated token tables follows from it:
   they belong to the theme contract, not to the components.

### F4. Contexts still import their own translator entry and start transactions in handlers

Carried from step 2 (D-057's allowance, "until step 3 moves transactions into use cases"). Verified: 40 files.

- `catalog/server` (32): `admin-journal`, `authors`, `batch-apply`, `bundle-apply`, `common`, `courses`, `cover-kinds`,
  `deletion`, `doctor`, `draft`, `editions`, `errors`, `home`, `http`, `imports`, `lesson-slugs`, `lessons`,
  `lifecycle-refs`, `list-projection`, `media-owners`, `misc`, `mutation`, `page-reads`, `read`, `redirects`,
  `reference`, `refs`, `release-routes`, `releases`, `ship-batch`, `tables`, `texts`.
- `media/server` (8): `actions`, `admin`, `index`, `inheritance`, `institution-cover`, `objects`, `owner-list`,
  `revalidate`.
- They import 282 distinct catalog statement functions and 21 media ones, plus the handle types (`CatalogDatabase` in
  21 files, `MediaDatabase`, `MediaTransaction`, `CatalogTransaction`) and `withUnitOfWork`.
- The transaction starts in `catalog/server/mutation.ts` (`runMutation`, called by the HTTP layer `http.ts`),
  `bundle-apply.ts` and `admin-journal.ts`; media's admin actions receive the transaction as an optional participant
  from `admin/http-dispatcher.ts`.

Why-chain:
1. 40 server files import their own context's translator entry.
2. Their functions receive a transaction handle and call statement functions with it (`lockRow(tx, …)`).
3. Step 2 moved each statement behind the package and kept every transaction where it was (step 2 plan, out of scope);
   D-057 allowed the import until this step.
4. No layer above the handlers owns the transaction: the HTTP layer opens it and passes the handle down, so the handle,
   not a port, is what the handlers know.
5. Root cause **R1** again: without an application layer there is no owner for "one operation, one transaction", so
   the database handle travels through the context instead of a port bound to one transaction.

## Root causes

| Id | Root cause | Kind | Findings |
|---|---|---|---|
| R1 | No application layer: `server/` is every context's public API and transactions start wherever the code is | missing abstraction | F1, F4 |
| R2 | No rule says what `app/` may import; the checker resolves aliases from a stale private copy | missing gate, duplicated configuration | F2 |
| R3 | The domain rule is a deny list (`L3.inner-pure`, `L1.no-backend-to-ui`'s hand-written roots) | missing gate (allow list) | F3 |

The plan ([STEP-03-plan.md](STEP-03-plan.md)) names the check that closes each one.
