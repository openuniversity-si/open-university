# Step 4 audit: services, bounded contexts and the intents registry

Roadmap step 4 of 8 (D-054). Audited on `mod/roadmap-integration` 3a86350b (step 3 closed), 2026-10-25, by the
roadmap implementer session. A Torre's baseline audit (main 198aa130, before step 3) was the starting hypothesis. Each
finding is verified, corrected or extended below with exact counts and file lists.

## How the counts were taken

- **Edge**: one `import`/`export … from`/`import()` resolved by the architecture checker's own graph
  (`scripts/check-architecture.mjs`, `checkArchitecture({ rules })`, aliases from `apps/web/tsconfig.json`), from a
  production file (not `*.test.ts`, not `testing/`, not `app/(test)/`).
- **Context**: a folder under `apps/web/src/` named in `architectureHalves` (`site`, `catalog`, `media`, `playback`,
  `progress`, `identity`, `config`, `factory`) plus `admin`. `app/`, `ui/`, `kernel/` and `platform/` are not contexts.
- **Cross-context edge**: an edge whose file and target sit in two different contexts.
- **Leak**: a cross-context edge whose target is not the other context's `application/` (its use cases) or `domain/`
  (its published types and pure rules), or a `client/` target imported from a file that is not itself a client file.
  `ports/`, `server/`, `deps.ts` and `admin/` root modules are leaks: they are the other context's internals.
- **Context cycle**: two or more contexts that reach each other through cross-context edges of any ring.
- PR 4.2 turns these definitions into checker rules, and their counts become the reproducible numbers.

## Baseline

| Measure | A Torre (198aa130) | Verified (3a86350b) |
|---|---|---|
| Catalog size | 118 files | **110** production files, **10,181** lines (domain 59, server 41, application 8, ports 2), plus 11 `testing/` files and 67 tests; its translator `platform/db/catalog/` has 274 statement functions |
| Cross-context edges | — | **125** from 66 files |
| Leaks | catalog→media/server 16, catalog→admin 8, catalog→playback/server 6, admin→catalog/server 8, admin→media/server 6, media→admin 4 (48 total) | **48** from **20** files: catalog→admin **11**, catalog→media **10** (6 `server`, 4 `ports`), catalog→playback **8** (3 `server`, 5 `ports`), admin→catalog/server **8**, admin→media/server **5**, media→admin **3**, catalog→config/server **1**, config→admin **1**, site/server→playback/client **1** |
| Context cycles | — | **7** two-context cycles (admin↔catalog, admin↔media, catalog↔media, catalog↔site, catalog↔playback, catalog↔config, playback↔progress) and the three-context cycle identity→playback→progress→identity |
| Contexts declared with who may depend on them | — | **0**: no file says which context may import which |
| Rules about one context importing another | 0 violations reported | **12** incident rules, each a deny list for one pair or one file list (F2); none would refuse a new leak between two other contexts |
| `admin` | — | not a context: 11 root modules outside any ring, outside `L3.context-layout`; 2 rings (`application`, `server`) |
| Admin route registries | — | **2**: `ADMIN_ROUTE_SPECS` (77 routes: catalog 69, media 8) and `matchConfigRequest` (16 config routes: 4 kinds × read, history, write, rollback) |
| Business intents registered | none on main (PR #291 had one) | **0**. 93 admin routes (61 writes: 53 catalog and media routes with 52 distinct actions, 8 config writes) and 29 exports of 22 use-case files, none with a written business or database contract |
| Operations scripts that import a context's `server/` | — | **24** files, 45 edges (`media/server` 31, `catalog/server` 12, `playback/server` 2) |

## Findings

### F1. Contexts leak into each other's internals

Verified, with corrections: 48 leaks from 20 files, not the same split A Torre counted on main before step 3. Step 3
moved `app/` onto use cases but did not touch context-to-context edges. Per pair:

| From → to | Edges | Files and targets |
|---|---|---|
| catalog → admin | 11 | `catalog/server/deps.ts` → `admin/auth.ts`, `admin/permissions.ts`, `admin/ports/jobs.ts`; `http.ts` → `admin/auth.ts`, `admin/route-specs.ts`, `admin/permissions.ts`; `routes.ts` → `admin/server/job-handlers.ts`, `admin/server/lifecycle-handlers.ts`, `admin/lifecycle-body.ts`, `admin/job-body.ts`; `admin-journal.ts` → `admin/http-dispatcher.ts` |
| catalog → media | 10 | `catalog/server/media-gateway.ts` → `media/server/index.ts`, `inheritance.ts`, `institution-cover.ts`, `public-hosts.ts`, `media/ports/owner.ts`; `deps.ts` → `media/server/invalidate.ts`, `media/server/storage.ts`, `media/ports/storage.ts`; `deletion.ts` → `media/ports/storage.ts`; `media-owners.ts` → `media/ports/owner.ts` |
| catalog → playback | 8 | `bundle-apply.ts`, `bundles.ts`, `courses.ts`, `imports.ts`, `deps.ts` → `playback/ports/oembed.ts`; `bundles.ts`, `deps.ts` → `playback/server/oembed-resolver.ts`; `playback-gateway.ts` → `playback/server/source-registry.ts` |
| admin → catalog | 8 | `admin/deps.ts` → `catalog/server/media-owners.ts`, `admin-journal.ts`, `deps.ts`, `routes.ts`, `media-gateway.ts`; `admin/server/job-handlers.ts` → `catalog/server/http.ts`; `lifecycle-handlers.ts` → `catalog/server/lifecycle-refs.ts`, `http.ts` |
| admin → media | 5 | `admin/deps.ts` → `media/server/invalidate.ts`, `deps.ts`, `storage.ts`, `admin.ts`, `actions.ts` |
| media → admin | 3 | `media/server/actions.ts` → `admin/media-contracts.ts`; `admin.ts`, `revalidate.ts` → `admin/auth.ts` |
| catalog → config | 1 | `catalog/server/deps.ts` → `config/server/read.ts` |
| config → admin | 1 | `config/server/admin.ts` → `admin/auth.ts` |
| site → playback | 1 | `site/server/build-info.ts` → `playback/client/youtube.ts` (through `@tower/playback-engine`) |

The other 77 cross-context edges go into a `domain/`, `application/` or (client to client) `client/` ring. They are
allowed shapes, but they still form the cycles of F3.

Why-chain:
1. 20 files in five contexts import 48 times into another context's `server/`, `ports/` or `admin/` root modules.
2. The functions they need (the admin guard, a cover read, an oEmbed resolver, the served editorial rules, the catalog
   admin routes) are exported only from those modules; the owning context offers no use case for them.
3. Step 3 gave each context an application ring for `app/`, and D-057 let a gateway (`*-gateway.ts`) or a `deps.ts`
   bind another context's adapters. Composition roots became the sanctioned way to import another context's server,
   and the rest of the server code followed (`http.ts`, `routes.ts`, `bundles.ts`, `deletion.ts`).
4. Nothing states which context may depend on which, or through what. The contexts are a list of folder names
   (`architectureHalves`); the map of their relations exists only as twelve incident rules (F2).
5. Root cause **R1 (missing rule)**: there is no declared context map. No artifact names each context's dependencies
   and its published surface, so no check can refuse an edge that is neither.

### F2. The checker reports 0 because its context rules are incident deny lists

Verified: A Torre's "the checker is too permissive" is the same root cause seen from the gate. The rules that look at
one context importing another are written per incident:

| Rule | What it refuses |
|---|---|
| `L1.progress-domain-pure`, `L1.catalog-no-progress-value` | progress domain impurity; a catalog value import of progress |
| `L1.shelf-boundary` | four hand-listed shelf files imported from playback, progress, identity, factory; media domain → catalog |
| `L1.site-data-boundary`, `L1.client-no-site-data` | site data imports from named places |
| `L2.media-no-catalog`, `L2.progress-no-catalog`, `L2.site-no-catalog`, `L2.site-route-domain` | one pair each |
| `L7.catalog-http-ports` | `catalog/server/http.ts` → media or playback `server/` |
| `L7.catalog-no-media-server` | ten hand-listed catalog files → `media/server/` (`media-gateway.ts`, `deps.ts` and `deletion.ts` are not on the list) |
| `L7.identity-domain` | identity domain → site |

None of them covers admin, config, playback or the client rings, and each new pair needs a new rule. 0 violations
means "no repeat of an old incident", not "no leak".

Why-chain:
1. `check-architecture` reports 0 violations while 48 leaks and 8 cycles exist.
2. Each cross-context rule refuses one pair or one file list, the incident it was written for.
3. When a leak was found, the fix was a rule for that leak, because there was no general rule to extend.
4. A general rule needs data: which contexts exist, what each publishes, and who may import it. That data was never
   written down (F1, level 4).
5. Root cause **R1** again, plus **R2 (wrong abstraction in the gate)**: boundaries are deny lists of known bad edges
   instead of an allow list derived from a declared map, so anything not yet seen passes.

### F3. The contexts form cycles

New finding. Seven two-context cycles and one three-context cycle; the edges that close each one:

| Cycle | Edges against the majority direction |
|---|---|
| admin ↔ catalog | catalog → admin 11 (F1); admin → catalog 8 |
| admin ↔ media | media → admin 3; admin → media 5 |
| catalog ↔ media | `media/server/inheritance.ts` → `catalog/domain/cover-resolve.ts` (1) against 29 catalog → media |
| catalog ↔ site | `site/domain/metadata.ts` → `catalog/domain/cover-resolve.ts` (1) against 10 catalog → site (`reader-copy`, `page-characters`, `route-registry`, `metadata`, `catalog-paths`) |
| catalog ↔ playback | `playback/domain/drivers/youtube.ts` → `catalog/domain/youtube-identity.ts` (1) against 8 catalog → playback |
| catalog ↔ config | `config/domain/documents.ts` → `catalog/domain/` (`course-status`, `lesson-kind`, `rules/status`, `schema/fields`; 4) and `config/server/admin.ts` → `catalog/domain/contracts.ts` (1), against `catalog/server/deps.ts` → `config/server/read.ts` and `config/domain/documents.ts` (2) |
| playback ↔ progress | `playback/client/persistence.ts`, `progress-bridge.ts` → `progress/client/client.ts` (2); `progress/client` → `playback/domain` (1) |
| identity → playback → progress → identity | `identity/client/AuthProvider.tsx` → `playback/client/completion.ts`, `persistence.ts` (2); playback → progress (2); `progress/application/viewer.ts` → `identity/application/session.ts` (1) |

Why-chain:
1. Eight cycles join eight of the nine contexts; only `factory` is outside every cycle.
2. Each cycle is closed by one to five edges that point against the direction the rest of the pair uses: a shared rule
   or word filed in the context that happened to need it first (`cover-resolve.ts`, `youtube-identity.ts`), or a
   provider that composes another context's client (`AuthProvider.tsx`).
3. A file is placed where its first caller is; nothing asks which context owns the word or the rule.
4. No direction is declared between contexts, so neither the author nor the checker can tell a downstream import
   from an upstream one (`L5.cycles` counts file cycles, not context cycles).
5. Root cause **R1**: the context map, if it existed, would carry the direction; an acyclic declared graph is the
   check.

### F4. `admin` has no place among the contexts

Verified and extended. Step 3 left "where admin sits" to this step.

- `admin/` has 11 root modules (`auth.ts`, `deps.ts`, `http-dispatcher.ts`, `job-body.ts`, `jobs.ts`,
  `lifecycle-body.ts`, `lifecycle.ts`, `media-contracts.ts`, `permissions.ts`, `route-specs.ts`) and two rings. It is
  not in `architectureHalves`, so `L3.context-layout`, `L3.inner-pure` and `L3.domain-pure` never look at it.
- The catalog's admin HTTP translation lives in the catalog: `catalog/server/http.ts` (141 lines: guard, permission,
  envelope) and `routes.ts` (109 lines: the handler table, including admin's own job and lifecycle handlers). The
  catalog's composition root `catalog/server/deps.ts` wires the admin guard, the permissions, the job store, media
  storage and invalidation, the oEmbed resolver and the served configuration.
- Two route registries: `ADMIN_ROUTE_SPECS` (catalog and media, with permission, idempotency, body limit and timeout)
  and the config API's `matchConfigRequest`, which dispatches 16 routes through its own guard call in
  `config/server/admin.ts`.
- The shared guard `admin/auth.ts` is imported by catalog, media (`admin.ts`, `revalidate.ts`) and config.

Why-chain:
1. Admin and catalog import each other 19 times, admin and media 8 times; admin's own files sit outside every ring rule.
2. The admin API's HTTP translation is split: the dispatcher is in `admin/`, the catalog's route table and envelope in
   `catalog/server/`, the config API's matcher in `config/`, so each half imports the other.
3. The admin API grew from the catalog's (ADR-18) and media and config were added beside it; nobody moved the catalog
   half out when `admin/` became the dispatcher for all three.
4. `admin` was never classified: it is neither in the context list nor declared as the driving adapter above catalog,
   media and config, so it could not have a direction or a layout.
5. Root cause **R3 (unclear ownership)**: the admin API has no single owner context, and the contexts it drives own
   pieces of its HTTP surface.

### F5. The catalog holds three contexts

Verified and corrected: 110 production files (A Torre's 118 counted differently before step 3), 10,181 lines, one
translator of 274 statements and one composition root. Reachability in the import graph from `app/` (the public site,
admin routes excluded) and from the admin API (`catalog/server/routes.ts`, `admin/deps.ts`):

| Reached from | Files | What they are |
|---|---|---|
| the site only | 27 | served reads of a release: `server/read.ts`, `page-reads.ts`, `media.ts`, `draft.ts`, `preview-route.ts`; `domain/view-model.ts`, `home.ts`, `queries.ts`, `universities.ts`, `countries.ts`, `credits.ts`, `cover-read.ts`, `page-frame.ts`, `page-read.ts`, `preview.ts`, `public-routes.ts`, `metadata.ts`, `progress-reading.ts`, `baked.ts`, `fallback.ts`, `config/index.ts`; six use cases |
| the admin API only | 46 | authoring (`courses`, `editions`, `lessons`, `lesson-slugs`, `authors`, `texts`, `reference`, `redirects`, `home`, `deletion`, `imports`, `list-projection`, `misc`, `common`, `refs`, `cover-kinds`, `doctor`, `tables`), publication (`releases`, `release-routes`, `ship-batch`, `batch-apply`, `bundle-apply`, `bundles`; `domain/batch-plan`, `batch-v2`, `ship-batch`, `rules/batch-v2`, `rules/lifecycle`, `schema/batch-v2`), the admin HTTP (`http`, `routes`, `admin-journal`, `errors`, `lifecycle-refs`) and the mutation use cases |
| both | 35 | the shared vocabulary and rules (`contracts`, `fields`, `schema/*`, `rules/*`, `cover-*`, `edition-variant`, `hierarchy`, `youtube-identity`, `video-share`), the compiler (`compile.ts`, `incremental-compile.ts` 683 lines, `release.ts`), `server/deps.ts`, `invalidate.ts`, `media-gateway.ts`, `media-owners.ts`, `preview-token.ts` |
| neither | 2 | `domain/batch-convert.ts`, `domain/schema/doc.ts` (reached only from tests and tooling) |

The site reaches the compiler through the draft preview (`catalog/application/preview.ts` → `server/draft.ts` →
`domain/compile.ts`), and the catalog composition root through media revalidation
(`catalog/application/media-revalidation.ts` → `server/deps.ts`), which is why the site's reach includes the admin
wiring.

Three cohesive parts appear, matching CONTRACT.md's concepts: **authoring** (institutions, lecturers, areas,
courses, editions, lessons, texts, home rows, redirects: the editable state), the **release** (the compiler, the cut,
activation and the served reads of an immutable snapshot, ADR-37) and the **batch** (the unit of publication that
writes authoring rows and cuts a release, D-053). The release tables (`catalog_releases`,
`catalog_course_projections`, `catalog_release_index`, `catalog_redirects`) and the batch tables
(`catalog_ship_batches`, `catalog_ship_chunks`) are already separable in `tableOwners`; the home revision
(`catalog_home`) and playlist imports (`catalog_imports`) are authoring state.

Why-chain:
1. One context of 110 files and 10,181 lines holds authoring, publication and served reads, and one composition root
   wires five other contexts.
2. Every catalog feature (a release cut, a served page read, a batch apply, an admin editor) was added to `catalog/`,
   the only context whose name fit.
3. The contexts were cut once, by product area (ADR-36), and never re-cut as the catalog grew from a JSON loader into
   an editor, a compiler and a publisher.
4. No limit says when a context is too large, and no map records the concepts each context owns, so growth never
   triggered a split.
5. Root cause **R4 (missing gate)**: no size budget per context and no concept-to-context ownership; a context can
   grow without bound and nothing fails.

### F6. Business intents are not registered

Verified: no intents registry exists on the integration branch. PR #291 (closed, branch
`cursor/m10-no-literal-f2a9`, `packages/business/src/kernel/intents.ts`) registered one catalog command
(`changeCourseStatus`, its port method and seven contract case ids) and five "operations" pointing at the file and
symbol of a domain law. Its test checked only that the seven case ids appear in the contract file. Useful ideas kept
for this step: an intent is named for the operation, not the method; it points at the proof (case ids) that a test
verifies exists. Missing there: a database contract, coverage (nothing failed when an operation had no entry) and the
other 92 entry points.

What a caller can ask today, and where it is written:

| Entry points | Count | Where its contract is today |
|---|---|---|
| catalog admin routes | 69 (22 reads, 47 writes, 46 distinct actions) | `ADMIN_ROUTE_SPECS`: method, path, schemas, idempotency, permission, timeout. No business meaning, invariant or tables |
| media admin routes | 8 (2 reads, 6 writes) | the same |
| config admin routes | 16 (4 kinds × read, history, write, rollback) | `matchConfigRequest`; no spec at all |
| use cases called by `app/` | 29 exports in 22 files | the function signature |
| operations scripts | 24 files reach `server/` directly | nowhere (F7) |

Which invariants (`INV-H*`, `INV-M*`, `INV-R*`, `G-1`…`G-6`) and decisions an operation upholds, which tables it reads
and writes, whether it runs in one transaction, whether it is idempotent and audited: none of this is written next to
the operation. It is spread over CONTRACT.md, DECISIONS.md, the translator and the integration tests.

Why-chain:
1. 93 admin routes and 29 use cases have no registered business or database contract.
2. The route spec records the HTTP shape because the dispatcher needs it; nothing needs the business shape at run
   time, so it was never written as data.
3. The business contract lives in prose (CONTRACT.md, DECISIONS.md) and the database contract in code (statements,
   `withUnitOfWork`), and the link between an operation and both is in the author's head.
4. The one attempt (PR #291) was a list without a coverage check, so it covered one intent and was closed.
5. Root cause **R5 (missing rule and test)**: no registry with coverage enforced by a test; an operation can be added
   without saying what it guarantees and what it touches.

### F7. Operations scripts bind server modules

Carried from step 3. 24 files under `apps/web/scripts/` import 45 times into `media/server` (31), `catalog/server`
(12) and `playback/server` (2): `lib/catalog-cli/responses.ts` (7), `lib/media-content-migrate.ts`,
`lib/media-storage.ts`, `lib/r2-bulk.ts` (4 each), `lib/catalog-cli/commands/covers.ts`, `commands/media.ts` (3 each)
and 18 more with one or two. Some are composition roots (D-057 allows scripts to bind adapters); others import a type
or a pure helper that sits in `server/` only because it has no other home.

Why-chain:
1. 24 scripts reach into context internals.
2. A script needs a cover rule, a storage adapter or a response type, and those exist in `server/`.
3. D-057 classified every script as a composition root, so any import from a script passes `L2.db-package`.
4. The context map (R1) does not exist, so a script cannot be told what each context publishes.
5. Root cause **R1** (no published surface) and **R3** (scripts own no context, so every script is treated as root).

## Root causes

| Id | Kind | Statement | Findings |
|---|---|---|---|
| R1 | missing rule | No declared context map: no artifact names each context, its dependencies (a direction) and its published surface | F1, F2, F3, F7 |
| R2 | wrong abstraction (gate) | Context boundaries are incident deny lists, not an allow list derived from the map | F2 |
| R3 | unclear ownership | The admin API has no owner context; catalog, media and config each own a piece of its HTTP surface, and scripts belong to no context | F4, F7 |
| R4 | missing gate | No size budget per context and no concept-to-context ownership, so the catalog grew into three contexts | F5 |
| R5 | missing rule and test | No intents registry with coverage: an operation's business and database contracts are written nowhere and checked by nothing | F6 |

The plan ([STEP-04-plan.md](STEP-04-plan.md)) names the PRs and, per root cause, the enforcement that makes recurrence
fail the gate.
