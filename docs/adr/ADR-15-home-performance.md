# ADR-15 — Home weight: right-sized media at the origin, one hero, woff2 subset, budgets

Date: 2026-10-10 · Status: accepted

## Context
Production Lighthouse (10/10/2026): Home 2,934 KiB, LCP 4.0 s desktop / 10.1 s mobile. Five 1080×1920 JPEG posters
of 306–461 KiB for ~208 px cards, the 296 KB full Inter TTF, both hero crops downloaded (`preload` on two
`next/image`s, one hidden by CSS) and zod (~34 KB gzip) in every page's shell. The Vercel image optimizer stays off
on purpose (cost): media must be small **at the origin**. Ingestion made it worse: `prepareMedia` re-encoded every
upload (JPEG/WebP at q95).

## Decision
- **Media**: posters are 540×960 WebP (q≈78), heroes WebP at their current size; uploaded as new default versions
  with `tower-media put` (history and `rollback` kept). `prepareMedia` stores a *bare* WebP (only VP8/VP8L/VP8X/ALPH
  RIFF chunks: no EXIF/XMP/ICC) byte for byte; everything else is still re-encoded and stripped.
- **Budgets per kind** (`src/media/budget.ts`): poster_9x16 120 KiB, hero_* 250 KiB, still_16x9 200 KiB,
  thumb 60 KiB, cover_16x9/cover_9x16 300 KiB (the measured p95 of the 126 lesson covers is 297 KiB; 77 are over
  200 KiB, so 200 KiB would refuse today's catalog). The API answers 413, `media:put` and `tower-media put` exit ≠ 0;
  `--force-oversize` is the conscious exception. `tower-media check --budget` lists active assets above budget.
- **Hero**: one `<picture>` (desktop `<source>` at the CSS breakpoint `(width >= 1024px)`, mobile `<img>` fallback),
  `fetchPriority="high"`, intrinsic width/height, no preload. Course switching keeps the same element, so the
  browser shows the previous hero until the next one decodes (unchanged UX, loaded on demand).
- **Cards**: first rail eager, the rest lazy; `decoding="async"`; fixed frames, so no CLS. Since P8 (2026-10-12):
  only the cards of the first `EAGER_ROWS` (2) rows that fit the narrowest viewport (`EAGER_CARDS_PER_ROW`,
  `src/ui/Rail/eager.ts`) are in the HTML, `loading="eager"` inside a `<picture>` so React does not preload them; every
  other poster is a `LazyPoster` (no `src` until it is within 200 px of the viewport or of its rail's edge, one shared
  `IntersectionObserver`, `<noscript>` fallback, native `loading="lazy"` without `IntersectionObserver`).
- **Font**: Inter variable (wght 100–900) subset to `scripts/fonts/inter-unicodes.txt` → `Inter.woff2` (~37 KB),
  built by `pnpm fonts:subset`; metric-matched Arial fallback. Libre Caslon Text has no `@font-face` (the footer slogan that
  used it was removed in the 2026-10-11 rebrand), so it is never downloaded.
- **JS**: `return-ui.ts` validates by hand instead of zod: the Home's own initial JS went from 51.7 to 21.2 KB gzip.
- **Cache**: `/icons`, `/brand`, `/fonts`, `/favicon.ico` get `public, max-age=86400, stale-while-revalidate=604800`
  (stable names, so not `immutable`); `/_next/static` and R2 covers are already immutable.

## Rule
Guardians: `src/ui/fonts.test.ts` (woff2 ≤ 60 KB, no tofu for static text, manifest hash),
`scripts/lib/perf-budget.test.ts` (perf:budget logic; every `unoptimized` carries
`// perf: pre-optimized at the origin`), `src/media/budget.test.ts` and `src/media/admin.test.ts` (413 / force),
`bundle:check` (Home own initial JS ≤ 21.2 KB + 5%; needs a production build and `next start`, so it is a manual
check, not a PR unit test), and `pnpm perf:budget [url]` after each deploy.

## Backlog
- Lesson covers: 126 `cover_16x9` JPEGs, median 209 KiB, 6 above the 300 KiB budget (`tower-media check --budget`).
  Re-encode them like the posters (Course page and player, not the Home).
- ~~Home HTML `private, no-store`, ~0.7 s TTFB, root `loading.tsx` CLS~~: done in ADR-16 (static Home for visitors).
- Prod media went through the pre-ADR ingestion (q95 re-encode of the q78 WebPs, ~2× the bytes, all within budget).
  After this deploys, re-run the same `tower-media put --target prod` for the exact bytes (preview already has them).
- Apple devices render the system font first (`--tower-font-ui`) yet still fetch the preloaded Inter (~37 KB).
- The remaining initial JS is the Next/React runtime (129 KB gzip), not app code.
