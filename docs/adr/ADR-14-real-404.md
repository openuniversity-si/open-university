# ADR-14 — Unknown slugs are a 404 at routing

Status: deprecated by D-111 (the Open University product left this repository; PADRAO-DEV F3a).

Date: 2026-10-10 · Status: accepted; the proxy slug set is superseded by the layout guards of [ADR-17](ADR-17-dynamic-catalog.md)

## Context
Course and lesson pages render per request (`force-dynamic`: session and progress) under `c/loading.tsx` (the root one until ADR-16).
The Suspense boundary streams the shell with **HTTP 200** before the page runs, so a `notFound()` there only
swaps in "Page not found": `/c/<anything>` was an indexable soft 404.
`generateStaticParams` + `dynamicParams = false` does not help in Next 16.4: on a dynamic route the params list is
not enforced at routing (the `dynamicRoutes` manifest stays empty) and the check happens during the streamed render.

## Decision
- The catalog closes the set of slugs. `src/proxy.ts` (matcher `/c/:path*`) checks the path against
  `publicCatalogRoutes()` (the same list as the sitemap) and rewrites anything else to an unroutable `_` path,
  so Next serves `not-found.tsx` with a real **404** before any streaming.
- `notFound()` stays in the pages as a safety net.
- The 404 page is `noindex`, has no canonical and is never in the sitemap.

## Rule
A route whose params come from the catalog must be guarded before rendering; never rely on `notFound()` under
`loading.tsx` for the status. Guardians: `src/site/routes.test.ts` (unit) and `e2e/status.production.ts` (HTTP).
