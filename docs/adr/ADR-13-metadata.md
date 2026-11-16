# ADR-13 metadata: titles, descriptions, Open Graph, favicon and manifest (v02)

Status: deprecated by D-111 (the Open University product left this repository; PADRAO-DEV F3a).

Decision (Daniel, 10 Oct 2026): every public page ships its own title, description, canonical, Open Graph and Twitter card, plus the site icons and manifest. Production Lighthouse SEO was 50: every page was `<title>The Tower</title>` with no description, OG, canonical or favicon.

## Single source
- `apps/web/src/site/metadata.ts` holds all of it: `siteMetadata` (root layout: `metadataBase` = `PRODUCTION_ORIGIN` from `src/site/origin.ts`, title default "The Tower — Great lecture courses, in order", template `%s · The Tower`, default description, `applicationName`, icons), `staticPageMetadata(route)`, `courseMetadata(slug)` and `lessonMetadata(course, lesson)`. Pages only call these; `robots` stays as ADR-12 defines it.
- `apps/web/src/site/routes.ts`: `PUBLIC_STATIC_ROUTES` (`/`, `/privacy`, `/terms`, `/contact`) and the catalog routes. The sitemap (135 URLs) and the guardians read it; a new static page adds its path there and its entry in `metadata.ts` (typecheck fails otherwise).
- Courses: "<course> by <author>"; lessons: "<lesson> · <course>" (the template is dropped, then the course, when the result would pass 70 characters). Descriptions come from the catalog (lesson About, else the course), cut to 160 characters on whole sentences or whole words + "…".
- Canonical is per page (`alternates.canonical` = its own path, absolute through `metadataBase`), never the home for everything.
- `src/app/manifest.ts` serves `/manifest.webmanifest` (standalone, `TOWER_THEME_COLOR`, icons 192/512).

## Images
- Open Graph/Twitter image for every page: the brand card `public/brand/og.jpg` (1200×630). Course art is not used: the metadata would need its own media lookup, which this ADR rules out.
- Icons in `public/icons/` (`favicon.ico` 16/32/48, `apple-touch-icon.png` 180, `icon-192/512.png`); `/favicon.ico` is a rewrite to `/icons/favicon.ico`. `pnpm brand:icons` regenerates them from the Saturn PNGs on `#0c0c0d` (D-028). A unit test fails if those files drift.
- `og.jpg` is a one-off composition (mark, reduced and darkened Genesis cover, tagline); replace the file by hand at the same size. `repo:assets-check` allows `public/brand/og.*` for it.

## Guardians
- `src/site/metadata.test.ts`: every static route, course and lesson resolves a unique title ≤ 70 characters, a 50–160 character description, an absolute canonical equal to its URL, OG title/description/1200×630 https image and `summary_large_image`.
- `e2e/metadata.production.ts` (`pnpm e2e:production`, HTTP only, no browser or video): the rendered tags on `/`, the legal pages, a course and a lesson, and 200 + content type for the icons, `/favicon.ico`, the manifest and `og.jpg`.
