# Step 4 plan: services, bounded contexts and the intents registry

Target: the contexts and their relations are declared data (a context map); a context reaches another only through
that context's `application/` or `domain/` ring and only along a declared dependency; the declared graph is acyclic;
`admin` is a context, the single owner of the admin API, downstream of the contexts it drives; the catalog is split
into cohesive contexts with a size budget; every business intent is registered with its business contract and its
database contract, and a test fails when an entry point has no intent or an intent cites something that does not
exist. No visual or behavior change: the rows stored, the release served, the responses and the pages rendered stay
the same. Root causes and counts: [STEP-04-audit.md](STEP-04-audit.md).

Every PR branches from `origin/mod/roadmap-integration`, targets it, has 3–8 commits, stays under the B5 size budget
(≤ ~600 changed lines without tests and generated files), and ends with `Capability: CAP-009` and
`Fit-Review: not reviewed (Daniel 2026-10-25: no review step)` (D-055). `gate-db` needs Neon credentials this session
does not have; a PR that moves statements or tables between translators is proven on the local PostgreSQL 18
integration tests instead and says so. No migration: a table changes owner in the map and in its translator folder,
not in the database.

## Target (D-060)

### The context map

`scripts/lib/context-map.json` is the one source for the contexts. For each context it names:

- `half`: `site` or `factory` (FACTORY.md); `architectureHalves` is derived from it.
- `dependsOn`: the contexts it may import. The declared graph must be acyclic.
- `tables`: the tables its translator owns; the checker's `tableOwners` is derived from it.
- `budget`: the most production files and lines it may hold; the map's ceiling, or a shrink-only override for a context above it (PR 4.16).

`docs/architecture/CONTEXTS.md` explains the map and lists, for every CONTRACT.md concept, the one context that owns
it. A test fails when the two disagree.

Target dependencies after step 4 (an arrow is "may import"; `kernel/`, `platform/` and `ui/` are not contexts):

| Context | Owns | `dependsOn` |
|---|---|---|
| `site` | the manifesto, reader copy, route registry, origin, build identity | — |
| `identity` | session, viewer, auth | `site` |
| `progress` | lesson progress | `identity` |
| `playback` | engines, source drivers, oEmbed, YouTube identity | `progress`, `site` |
| `media` | media objects, covers, storage | `site` |
| `catalog` | authoring (institutions, lecturers, areas, subareas, courses, editions, lessons, texts, home rows, redirects, imports), the catalog rules, the batch, the compiler, the release cut and activation, and the release tables (D-061) | `media`, `playback`, `progress`, `site` |
| `release` | the served reads of the active release and the draft preview (D-061: no table; the catalog writes the snapshot) | `catalog`, `media`, `playback`, `progress`, `site` |
| `config` | the versioned documents (D-051) | `catalog`, `site` |
| `admin` | the admin API: route specs, guard, permissions, dispatcher, journal, jobs, lifecycle | `catalog`, `release`, `media`, `config`, `site` |
| `factory` | sources to `curated/v1` to a batch | `catalog`, `media`, `playback`, `site` (domain only) |

**Amended (D-061):** the catalog is cut once, into `catalog` (authoring and publication) and `release` (served reads), following the audit's reachability table (F5); there is no `publishing` context.
and is recorded file by file in each split PR's row. If a context still exceeds its budget after its split, the next
cut is planned in that PR, not deferred.

### What may cross a context boundary

- A file of context A imports context B only when B is in A's `dependsOn`, and only B's `application/` (use cases) or
  `domain/` (published types and pure rules). A `client/` file may also import B's `client/`. `ports/`, `server/`,
  `deps.ts`, `testing/` and any root module of B are refused, including from A's composition roots: a gateway binds
  A's own port to B's use case, not to B's adapter (this narrows D-057's "another context's adapters").
- What A needs from B that B does not publish becomes a use case in B (or a domain export, for a pure rule), named
  for what A asks.
- `app/` keeps D-058's rule; operations scripts follow the same rule as a context file from PR 4.17c on.

### The intents registry

An **intent** is one thing a caller can ask the system: an admin route (catalog, media, config), a use case `app/`
calls, or an operation a script runs. Each context declares its intents in `<context>/domain/intents.ts` as data,
typed by `kernel/intents.ts`:

```ts
{
  id: "course.publish",                       // the admin action when there is one; otherwise <context>.<verb>
  context: "publishing",
  kind: "command",                            // command | query
  entry: { route: "catalog:POST /courses/:id/publish", useCase: "publishing/application/publish.ts#publishCourse" },
  business: { meaning: "…", invariants: ["INV-R5", "INV-M5"], decisions: ["D-053"] },
  db: { reads: ["courses", …], writes: ["courses", "catalog_releases", …], transaction: "one",
        idempotency: "required", audit: true },
  proof: ["test/int/publish.int.test.ts › \"…\""],
}
```

`apps/web/scripts/lib/intents.test.ts` (unit stage) fails when:

1. an admin route spec (any scope) is the entry of no intent, or of more than one;
2. an exported function of an `application/` ring is the entry of no intent;
3. an intent's entry names a route, a file or an export that does not exist;
4. an invariant or guarantee is not in CONTRACT.md, or a decision is not in DECISIONS.md;
5. a table is not in the context map, or a written table is owned neither by the intent's context nor by a context in
   its `dependsOn`;
6. the declared idempotency differs from the route spec's, or a command with writes has no integration proof, or a
   proof's file or test title does not exist;
7. `docs/domain/INTENTS.md` differs from the document generated from the registry.

PR 4.15 adds the database half of the check: the tables each use case actually reaches (the store methods it calls,
mapped to the tables their SQL names by the checker's table parser) must equal the declared `reads` and `writes`.

## PRs

| PR | What | Before → after | Root causes | Enforcement it adds |
|---|---|---|---|---|
| 4.1 | This audit and plan, D-060, CAP-009, `STATUS.md` | leaks 48, cycles 8, intents 0 (unchanged) | all (record) | `structure-check` covers the docs |
| 4.2 #439 | Context map `scripts/lib/context-map.json` with `dependsOn`, `tables` and `half` (catalog keeps `progress` until the release split takes the served reads; `admin` has no half until 4.6; the three asset tables retired in migration 0027 leave the owners); `architectureHalves` and `tableOwners` derived from it; `L3.context-ports` (a cross-context edge goes into `application/` or `domain/`, client to client allowed) and `L3.context-dag` (the declared graph is acyclic; every cross-context edge follows a declared dependency), with one shrink-only baseline `scripts/lib/context-baseline.json` (a new edge fails; a listed edge that is gone fails until removed); `admin` in the map | leaks 48 → 48 listed; edges against the declared map **25** listed (11 into admin from catalog, 3 from media, 1 from config; 2 catalog → config; 8 against the map's direction: the edges that close the other cycles and `site/server/build-info.ts` → playback) | R1, R2 | the two rules + `check-architecture.test.ts` cases; a test that the map's tables equal the schema's |
| 4.3 #440 | Intents registry: `kernel/intents.ts`, `scripts/lib/intents.test.ts` (checks 1 and 3–7), `docs/domain/INTENTS.md` generated by `pnpm intents:generate`; media (8 intents, one per route) and config (4 intents over the 16 routes, confirmed through `matchConfigRequest`). **Amended:** the config routes stay in `matchConfigRequest` here; they join `ADMIN_ROUTE_SPECS` in 4.7, when config's HTTP moves into admin, because the config API answers with its own envelope today | intents 0 → 12, routes covered 0 → 24 of 93 | R5 | coverage limited to the covered scopes (`coveredScopes`, a list that may only grow) |
| 4.4 #441 | Catalog route intents: `catalog/domain/intents.ts` (62) and `admin/domain/intents.ts` (the 7 job and lifecycle routes admin's handlers serve); tables derived from the store calls of each handler and the translator's statements, hand-checked where a statement takes its table as a parameter; the per-route integration cases as proof; a command named for its route's action, a query for its context; the admin journal's tables implied, never listed; `L4.projection-boundary` and `L4.job-boundary` let a registry name tables as data, never SQL | intents 12 → 81; routes covered 24 → **93 of 93**; `coveredScopes` deleted | R5 | check 1 without exceptions |
| 4.5 #442 | Use-case intents: an intent's entry names the application exports its request passes through (`entry.useCases`: the admin dispatchers, the catalog mutation, the idempotency check, `createTransition`); 14 intents for what `app/` asks (catalog 6, site 4, identity 1, progress 2, config 1); a command writes or has an effect (`cookie` added), `transaction: each` for statements that commit one by one; no export was unexported, since each of the 29 has a caller | intents 81 → **95**; application exports named by an intent 0 → 29 of 29 | R5 | check 2 without exceptions |
| 4.6 #443 | `admin` becomes a context: job vocabulary and stage rules in `admin/domain/jobs.ts`, the store in `admin/ports/jobs.ts`, lease operations and the preview reset in `admin/application/` (named by their intents); route specs, permissions, job, lifecycle and media request bodies in `admin/domain/`; guard, dispatcher and composition root in `admin/server/`; `admin` in the map's site half, so `L3.context-layout`, `L3.inner-pure` and `L3.domain-pure` cover it and the checker's admin special cases go | admin root modules 11 → **0**; leaks 48 → **42** (six imports now reach admin's domain ring; still undeclared under `L3.context-dag`) | R3 | the layout rules cover `admin` |
| 4.7a #444 | Media's admin HTTP through media: the Bearer check in `platform/security/bearer.ts` (media revalidation stops importing the admin guard); media's request bodies in `media/domain/admin-requests.ts`; media's actions are use cases in `media/application/actions.ts` with `mediaActionDeps`, so admin's composition root imports only media's application ring | leaks 42 → **35**; edges against the map 25 → **22** (admin → media/server 5 → 0, media → admin 3 → 0) | R3, R1 | baseline shrinks |
| 4.7b #445 | Config's admin API through admin: config use cases in `config/application/documents.ts` (`configDocument`, `configHistory`, `writeConfig`, `rollbackConfig`, `configServices`); the handler in `admin/server/config-routes.ts`, its entry in `admin/application/config-request.ts`; the 16 config routes in `ADMIN_ROUTE_SPECS` (scope `config`) with the responses unchanged; `matchConfigRequest` deleted; `L3.inner-pure` no longer reads an object key named `document` as the DOM global | leaks 35 → **34**; edges against the map 22 → **21** (config → admin 1 → 0); admin route registries 2 → **1** | R3, R1 | baseline shrinks; one registry |
| 4.8a #446 | The catalog owns its handler contract (`CatalogRequest`, `CatalogHandlerDeps`) and publishes `catalogAdminHandlers` (62 handlers by route, translating their own database errors) and `catalogAdminServices`; `http.ts` and `routes.ts` move to `admin/server/catalog-http.ts` and `catalog-routes.ts`; admin's guard, job store, request ids and credential scope are admin's. **Amended:** the handler files stay in `catalog/server/` behind the published table instead of moving into `catalog/application/` one by one; they export about 30 helpers that other server files share, which would otherwise become application exports without an intent | leaks 34 → **26**; edges against the map 21 → **11** (catalog → admin 11 → 1) | R3, R1 | baseline shrinks |
| 4.8b #447 | The admin journal (`catalog_audit`, `admin_idempotency`) as `catalog/application/admin-journal.ts` with catalog-owned types; `catalogMediaOwners` for media's admin actions; the lifecycle references in `catalog/application/lifecycle-refs.ts`; the unused `catalogMediaGateway` re-exports deleted | leaks 26 → **20**; edges against the map 11 → **10**; admin ↔ catalog **0** both ways | R3, R1 | baseline shrinks |
| 4.9a #448 | Playback, config and site through published rings: the health route adds the playback engine (the site's build identity no longer imports playback); the oEmbed vocabulary in `playback/domain/oembed.ts`; playback's video services in `playback/application/video.ts`, registered as playback intents, and the catalog's re-exporting `playback-gateway.ts` deleted; the served editorial transitions bound in admin's composition root | leaks 20 → **10**; edges against the map 10 → **6** | R1 | baseline shrinks |
| 4.9b #449 | Catalog → media through media's rings: the owner graph and object-store contract in `media/domain/`; media's services for the catalog in `media/application/catalog-services.ts` (object store, read invalidation, public cover reads, cover graph, institution covers), registered as five media intents; `L3.context-ports` reads no baseline | leaks 10 → **0**; edges against the map 6 → 6 | R1 | `L3.context-ports` without a baseline |
| 4.10 #450 | Cycles: the share image resolved in the catalog (site metadata no longer imports the cover resolver); the YouTube id schema in `playback/domain/youtube-identity.ts` (`L3.source-registry` names its new owner); media's prune asks the catalog's owners for the redundant lesson covers; the lesson identity in `progress/domain/`; the identity provider takes `onSignedIn` and `useMarkComplete` moves to playback's client (playback declares identity); `L3.context-dag` with no baseline and the baseline file deleted. **Amended:** config ↔ catalog was resolved in 4.9a | cycles 8 → **0**; edges against the map 6 → **0**; baseline deleted | R1 | `L3.context-dag` and `L3.context-ports` without a baseline |
| 4.11 #451 | `release` context, part 1: the served reads (page reads, covers, draft preview, progress reading, health read; 26 files) move to `release/`; its composition root binds the catalog translator until 4.12; the preview token, the read-queries contract and the cache tag published in the catalog's domain; `L3.contract-coverage` checks contracts in domain rings (seven had stopped being checked since they left `ports/`); the media and progress rules refuse the release as they refuse the catalog | catalog production files 110 → **85**; release 0 → 29; contracts checked 14 → 21 | R4 | the map's `release` entry; contract coverage over domain rings |
| 4.12 | **Amended (D-061):** the catalog keeps the compiler, the cut, activation and the batch, and the release tables they write; `release` stays the served reads. Concept ownership: the context map names the CONTRACT.md concepts each context owns, `docs/architecture/CONTEXTS.md` is generated from the map, and a test fails when a concept has no owner or two, or the document is stale | concepts without an owner — → 0 | R4 | `contexts.test.ts` |
| 4.13 | **Dropped (D-061):** no `publishing` context; the batch, bundles and publication stay the catalog's | — | R4 | — |
| 4.14 | **Dropped (D-061):** concept ownership is 4.12 | — | R4 | — |
| 4.15 #453 | Intents' database contracts read from the source: `scripts/lib/intent-tables.ts` follows each code entry through its imports and store method calls to the translator statements and their tables; the test fails on a written table the intent does not declare. **Amended:** declared and derived writes are compared one way (derived ⊆ declared), because a store reached through an injected dependency or a template hole the parser cannot resolve is not seen; four media intents gained the writes the derivation found (`media.check` became a command) | intents whose code writes only declared tables 0 checked → **103 of 103**; exact matches 85 of 103 | R5 | `intents.test.ts` database check |
| 4.16 | Context size budget: `L3.context-size` holds each context's production files and lines to the map's budget. **Amended:** one ceiling (60 files, 4000 lines) for every context, and a shrink-only override for the one context above it (catalog, 85 files and 9120 lines), instead of a budget per context at its measured size: a budget equal to every context's size would need a map edit for every added line, and the override must equal catalog's size and goes when catalog fits | contexts without a budget 10 → 0; contexts above the ceiling 1 (catalog, held at its size) | R4 | `L3.context-size`; raising the ceiling or an override needs a decision |
| 4.17a | Operations scripts, media: media publishes what its scripts ask in `media/application/operations.ts` (inspect an upload, render a link preview, open a store, bulk work within the R2 budget) and `media/application/hosts.ts` (registers the public hosts); pure names come from `media/domain`; script-only intents registered; `scripts/lib/media-storage.ts` and `scripts/lib/r2.ts` (re-exports of `media/server`) deleted. **Amended:** 4.17 is split in three; the `@tower/media` and `@tower/catalog` seams already resolve inside `release` to its own `server/` since 4.11, which its application ring may import, so they need no change | tooling files into `media/server/` 16 → 0 (and `fidelity/references/storage.ts`) | R1, R3, R5 | the intents test over the new application exports |
| 4.17b | Operations scripts, catalog, playback and factory: the catalog CLI's response types come from the shapes `catalog/application/admin-handlers.ts` publishes for admin clients, release diffs from the catalog's domain, oEmbed from `playback/application/operations.ts` (not `server-only`: the CLI runs under Node), and the YouTube adapter from a new `factory/application/ingest.ts` with the factory's first intents registry. **Amended:** the ship and factory benches time catalog write stages inside a test harness, so they reach them through `catalog/testing/bench.ts`, not an application export; three dead catalog exports go so catalog stays within its size budget | tooling files into another context's `server/` or `ports/` 8 → 0 | R1, R3, R5 | the intents test over the new application exports; `L3.context-size` |
| 4.17c | `L3.context-ports` over tooling edges: a production file of `apps/web/scripts/` reaches a context only through its `application/`, `domain/` or `testing/` ring, with no baseline | tooling leaks → 0, checked | R1 | the rule over tooling edges |
| 4.18 | Close: the twelve incident rules that the map now covers are deleted or folded into `L3.context-ports` (each named with the map entry that replaces it); D-060 proven, CAP-009 done, step metrics. **Amended:** catalog's production code no longer imports progress (only its testing ring does), so `progress` leaves catalog's `dependsOn` and `L3.context-dag` replaces `L1.catalog-no-progress-value`; `L1.shelf-boundary` keeps only its lesson-summary checks, as `L1.lesson-summary`; `L7.identity-domain` stays, because identity depends on site from its server ring and the map cannot narrow a dependency to one ring; `L1.site-data-boundary`, `L1.client-no-site-data` and `L2.site-route-domain` are not cross-context rules (a data folder, client against server, and site's own rings) and stay | incident cross-context rules 12 → 1 (`L7.identity-domain`) | all | every new rule stands with no baseline; each deleted rule's fixture fails the map rule that replaces it |

4.2, 4.6, 4.10, 4.16, 4.17c and 4.18 change `scripts/check-architecture.mjs`, which the gate's unit stage runs, so their
bodies cite D-060. The estimates (~) are corrected in each PR's row when it is opened, and a file that has to move
with another group is recorded in the next PR's row, not left behind.

## Enforcement per root cause

| Root cause | Check that stops it recurring | PR |
|---|---|---|
| R1 no context map | `scripts/lib/context-map.json` is the only list of contexts; `L3.context-ports` refuses an edge into another context's internals; `L3.context-dag` refuses an undeclared dependency and a cyclic map; tooling edges included | 4.2, 4.10, 4.17 |
| R2 deny lists in the gate | the two rules are derived from the map, so a new pair is covered without a new rule; the incident rules the map covers are deleted | 4.2, 4.18 |
| R3 admin without an owner | `admin` is a context with `dependsOn` and the layout rules; one route registry; no other context imports `admin` (the map makes it a sink) | 4.3, 4.6, 4.7, 4.8 |
| R4 no size budget, no concept owner | `L3.context-size` from the map's budgets; the concept-ownership test over CONTEXTS.md, the map and the schema | 4.14, 4.16 |
| R5 no intents registry | `intents.test.ts`: coverage of every route and use case, citations that exist, tables owned, idempotency equal to the spec, a proof that exists, the generated document, and the database tables derived from the use case | 4.3, 4.4, 4.5, 4.15 |

## Out of scope for step 4

- Vendors (Blob, Mux) behind ports (step 5), literals and the absolute gate (step 6), the anti-mess structure rules
  beyond these (step 7), host portability (step 8).
- Database migrations: no table is renamed or moved between schemas; ownership changes in the map and the translator
  folders only.
- Integration and e2e tests, which may import any ring.

## Metrics

| Measure | Before (3a86350b) | Target after step 4 | After step 4 (PR 4.18) |
|---|---|---|---|
| Leaks (cross-context edges into another context's internals) | 48 from 20 files | 0; `L3.context-ports` with no baseline | 0, no baseline (PR 4.9b) |
| Context cycles | 8 (7 of two contexts, 1 of three) | 0; `L3.context-dag` with no baseline | 0, no baseline (PR 4.10) |
| Contexts declared with dependencies and tables | 0 | every context, in one map | 10 of 10 in `scripts/lib/context-map.json`, with concepts and a size budget |
| Incident cross-context rules | 12 | only those the map cannot express | 1 (`L7.identity-domain`, a dependency narrowed to one ring) |
| `admin` root modules outside a ring | 11 | 0 | 0 |
| Admin route registries | 2 | 1 | 1 |
| Largest context (production files / lines) | catalog 110 / 10,181 | within its budget; no context without one | catalog 85 / 9,114 at its shrink-only override; every other context under the ceiling of 60 / 4,000 |
| Business intents registered | 0 of 93 routes and 29 use-case exports | all, with business and database contracts checked | 108 intents: 93 of 93 routes and every application export (76 use cases); written tables derived from the code |
| Operations scripts importing a context's `server/` | 24 files, 45 edges | 0 | 0, checked by `L3.context-ports` with no baseline (PR 4.17c) |
