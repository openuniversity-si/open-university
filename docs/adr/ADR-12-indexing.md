# ADR-12 indexing: production fully indexable, everything else noindex (v02)

Decision (Daniel, 10 Oct 2026; origin moved to `https://openuniversity.si` on 11 Oct 2026, ADR-20): the production origin is open to crawlers and search indexing; Vercel previews, development, CI and local builds stay noindex.

## Why
Until v02, indexing depended on a hand-set variable: only `SITE_INDEXABLE === "true"` made the site indexable, and an absent variable silently meant noindex. Production never had it, so it served `X-Robots-Tag: noindex, nofollow` on every response and a `robots.txt` with `Disallow: /`. AWS Activate rejected the application for that reason ("unable to validate your website; ensure robots.txt enables web crawlers").

## Rule
One pure function, `isSiteIndexable(env)` in `apps/web/src/site/indexing.ts`: indexable when `VERCEL_ENV === "production"` (Vercel sets it at build and runtime, nobody has to remember it) or `SITE_INDEXABLE === "true"` (explicit opt-in for a local verification build). It is the only copy of the rule; `next.config.ts` (header, evaluated at build), `src/app/robots.ts` and the root layout (`robotsMetadata`, `metadata.robots`) all call it.

- Production: no `X-Robots-Tag` on any path (including `/robots.txt` and `/sitemap.xml`), `<meta name="robots" content="index, follow">`, `robots.txt` = `Allow: /`, `Disallow: /api/`, `Sitemap: https://openuniversity.si/sitemap.xml`.
- Elsewhere: `X-Robots-Tag: noindex, nofollow` everywhere, `Disallow: /`, `noindex, nofollow` meta.
- `/api/` is hidden from crawling only (admin lives under `/api/admin`); access is unchanged: the admin API still answers 401 without credentials. No page is blocked.

## Sitemap
`src/app/sitemap.ts` lists the home, the 5 courses and the 126 lessons from the static catalog (`/c/<course>`, `/c/<course>/<lesson>`), absolute URLs on `PRODUCTION_ORIGIN` (`src/site/origin.ts`, shared with the auth default). No `lastModified`: the catalog has no real dates.

## Guardian tests
- `test/site/noindex.test.ts`: with `VERCEL_ENV=production` and any `SITE_INDEXABLE` there is no `X-Robots-Tag`, robots allows `/` with only `/api/` disallowed plus the sitemap, metadata is index/follow; preview/absent stays noindex with `Disallow: /`.
- `src/app/sitemap.test.ts`: every sitemap URL maps to a catalog course/lesson the routes serve (1 + 5 + 126).
- `pnpm e2e:production` (`playwright.production.config.ts`, `e2e/indexing.production.ts`): test build with `VERCEL_ENV=production` and `SITE_INDEXABLE=false` in its own dist dir; HTTP requests only (no browser page, no video) over home, a course, a lesson, `/api/health`, `/robots.txt`, `/sitemap.xml` (every URL 200) and the admin 401. `e2e/noindex.spec.ts` keeps the default (non-production) mode noindex.

## Consequences
Making production noindex again requires changing the guardian tests and this ADR. There is no Figma counterpart (technical configuration), so the Figma + site rule does not apply.
