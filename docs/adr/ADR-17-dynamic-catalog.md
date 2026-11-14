# ADR-17 — The site reads the active catalog release

Date: 2026-10-10 · Status: accepted (supersedes the proxy part of ADR-14)

## Context
Until P3 every page imported `content/catalog/*.json` at module level (`src/catalog/load.ts`), validated against fixed
counts, and `src/proxy.ts` closed the set of `/c/…` slugs at build time (ADR-14). A new course meant a commit, a build
and a deploy, and a lesson without a Mux asset was a 404. P1/P2 put the catalog in the database: `catalog_releases`
holds immutable, schema-validated payloads (`releaseSchema`, `src/catalog/release.ts`) and exactly one is active.

## Decision
- **One read path.** `getCatalog()` (`src/catalog/read.ts`, imported as `@tower/catalog`) returns the active release as
  `PublicCatalog`: React `cache` (one read per request) over `unstable_cache` with tag `catalog` and **no TTL**. The
  database is read on a cache miss only: a release activation (`revalidateTag("catalog")`, P4), a new deployment
  (the build commit is part of the key) or a cold Data Cache. `queries.ts`, `home.ts`, `site/metadata.ts`,
  `site/routes.ts` and `progress/view.ts` stay pure functions of a `PublicCatalog`.
- **Fallback.** `pnpm build` runs `catalog:bake` instead of `catalog:check`: it writes the active release of the build's
  database (`APP_DATABASE_URL`, Vercel) to `src/catalog/generated/release.json` (gitignored), or the versioned
  too, so lint, typecheck and unit tests see the file). A configured but unreadable database fails the build.
  At runtime, a cache miss with the database down serves that baked release and logs `{"event":"CATALOG_FALLBACK"}`;
  `/api/health` reports `catalog: { release, sha, source }` with `source` `database`, `fallback` or `fake`.
  The runtime never reads the snapshot or the legacy JSON.
- **Test build.** `TOWER_BUILD_TARGET=test` aliases `@tower/catalog` to `src/catalog/fake.ts`: the snapshot plus two
  test-only redirects, no database (same pattern as `@tower/media`). Vitest maps it the same way.
- **404 and 308 by layout guard.** `c/[courseSlug]/(course)/layout.tsx` and `c/[courseSlug]/[lessonSlug]/layout.tsx`
  call `guardCatalogPath()`: a path the release publishes renders; a `slug_redirects` source answers `permanentRedirect`
  (308); anything else `notFound()`. Each route's `loading.tsx` sits **below** its guard, so the status is decided
  before the shell streams (a real 404, never a soft one). The course guard lives in a route group so its loading
  boundary does not wrap the lesson route, whose guard needs both slugs. The proxy keeps only the Home routing
  (ADR-16); its static slug set is gone. The pages keep `notFound()` as a safety net.
- **Media, grouped.** `getCourseMedia()` reads every active course asset in one cached query (tag `media`);
  `getLessonMedia(courseId)` one course's lesson covers (tags `media`, `media:course:<id>`). `MediaImage` receives
  the asset. Home: 5 reads → 1; course and player: 1 + N → 2 (catalog included).
- **Playback.** The player needs only `lesson.youtubeId` (ADR-11); Mux is optional and token refresh reads
  `lesson_videos(provider='mux')`. The admin media API resolves owners from the catalog tables, so a draft course can
  get covers before it is published.
- **Draft preview hook.** `registerDraftCatalog()` lets the P4 preview API serve an uncached draft in draft mode.
  Until something registers, `draftMode()` is never called, so the visitor Home stays static.

## Consequences
- Publishing a course is a database change plus a tag revalidation; no deploy. Until P4 adds `release activate`,
  a new release reaches the site with the next deployment (new cache key) or a Data Cache purge.
- Rollback of code: promote the previous Vercel deployment (it carries its own baked release). Rollback of content:
  `content/catalog/*.json` and `catalog:check` leave in P8.

## Rule
Guardians: `src/catalog/read.test.ts` (database, fallback + log, build without database), `src/site/routes.test.ts`
(live/redirect/missing from the release), `e2e/catalog-routing.spec.ts` and `e2e/status.production.ts` (HTTP 404/308),
`e2e/health.spec.ts`. Parity with the static site: `scripts/html-snapshot.ts` against two test builds gives the same
normalized HTML for the 136 public pages (5 static + 131 catalog).
