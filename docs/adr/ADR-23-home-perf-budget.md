# ADR-23 — Home performance budget that scales with the catalog

Date: 2026-10-12 · Status: accepted (P8 of the dynamic catalog; mobile LCP target not yet met)

The P8b brief names this record ADR-21; that number already belonged to course editions (ADR-21), and ADR-22 to lesson
slugs, so it is ADR-23.

## Context
The Home went from 5 to 24 courses (P8-BASELINE, 11/10/2026): mobile LCP 2.69 s (median), 2.2 MiB with full scroll, three
poster preloads competing with the hero. The LCP element is the Billboard hero on the media host, not a poster.

## Decision
- **Targets** (lab: Lighthouse mobile simulated and desktop 1440): LCP ≤ 2.5 s, CLS ≤ 0.03, TBT ≤ 100 ms, ≤ 1 MiB transferred
  up to the second card row plus the hero. They hold for 24 and 50 courses.
- **Posters on demand** (P8a): only `EAGER_ROWS` rows, `EAGER_CARDS_IN_HTML` cards each, carry a `src` (`src/ui/Rail/eager.ts`);
  the rest wait for an `IntersectionObserver`. No poster preloads.
- **Budget in the lean CI** (no network, no Lighthouse): `scripts/lib/perf-budget-home.test.ts` renders the snapshot Home
  grown to 24 and 50 courses and audits its HTML (`auditHomeImages`, `homeImageFailures`); the image estimate is one hero
  plus the eager posters at the media budgets (`src/media/budget.ts`): 250 + 3 × 120 = 610 KiB (was 6 posters before #137), the same for any size.
- **Media headers**: R2 objects are content-addressed and uploaded with `Cache-Control: public, max-age=31536000, immutable`;
  the Billboard `preconnect`s to its hero's host because the hero is the LCP.
- **After deploy**: `pnpm perf:budget <url>` (wire bytes and the same HTML audit) and Lighthouse by the executor
  ([daily cycle](../project/CICLO-DIARIO.md)).

## Final numbers
Measured by E8 on 2026-10-14 ~09:00 (UTC-3), production `https://openuniversity.si/` after P8b (#126). Lighthouse 12,
3 runs, median (P8-BASELINE in parentheses, measured on www.thetower.si).

| | Score | LCP | FCP | TBT | CLS | LH bytes / req. |
|---|---|---|---|---|---|---|
| Mobile (simulated) | 0.90 (0.95) | **3.54 s** (2.69) | 1.32 s (1.23) | 54 ms (82) | 0 (0) | 0.47 MiB / 27 (2.23 / 47) |
| Desktop 1440 | 0.99 (0.99) | 0.84 s (0.79) | 0.51 s (0.45) | 0 ms (2) | 0 (0) | 0.44 MiB / 27 (2.11 / 46) |

- Real Chrome (Playwright, wire bytes), initial load: 390 px 468 KiB (24 req., 6 images, 229 KiB), 1440 px 439 KiB
  (6 images). Full scroll: 2155 KiB / 2240 KiB, 24–25 images. 0 broken `<img>`, CLS 0. Up to row 2 + hero: < 0.5 MiB.
- `pnpm perf:budget`: FAIL at 390 (2282 KiB) and 1440 (2252 KiB), a false positive: it counts the 19 `<noscript>`
  poster fallbacks as downloads. Largest image 114.4 KiB (course-10 poster); none ≥ 120 KiB.
- LCP element: Billboard hero (unchanged). Observed (unthrottled) LCP 0.77–1.26 s.
- **Mobile LCP target not met (3.54 s > 2.5 s).** Cause: the simulated run charges document TTFB (0.41–0.59 s) plus
  0.19–0.48 s render delay and a separate connection to the cross-origin media host for the hero; next step: serve the
  hero from the site origin (or cached at the Cloudflare edge, still `cf-cache-status: DYNAMIC`) and make
  `perf:budget` skip `<noscript>`.

## Re-measurement 2026-10-14 (~09:45 UTC-3)
After the move to `media.openuniversity.si` (edge cache on: `cf-cache-status: HIT`, `max-age=31536000, immutable`) and
with `perf:budget` skipping `<noscript>`. Lighthouse 12 mobile simulated, 3 runs on `https://openuniversity.si/`:
LCP 2.94 / 3.64 / 2.88 s → **median 2.94 s** (was 3.54 s); FCP median 1.27 s, TBT 34 ms, CLS 0, 481 KiB / 28 req.,
score 0.95. `pnpm perf:budget`: OK (390 px 489 KiB, 1440 px 460 KiB, largest image 68.3 KiB, one hero download).
**Mobile LCP target still not met (2.94 s > 2.5 s).** Remaining cost: document TTFB, render delay and the separate
connection to the cross-origin media host for the hero; next step: serve the hero from the site origin.

## Same-origin hero (#132), measured 2026-10-14 ~10:10 (UTC-3)
The Billboard hero is served from `/media/covers/*` on the site origin (rewrite to the media host, `x-vercel-cache: HIT`,
`immutable`); the media `preconnect` is gone. Lighthouse 12 mobile simulated, 3 runs: LCP 4.25 / 4.53 / 4.10 s →
**median 4.25 s (worse than 2.94 s)**; FCP 1.49 s, TBT 50 ms, CLS 0, 514 KiB / 29 req., score 0.84. `perf:budget`: OK
(390 px 521 KiB, one hero download). LCP phases (median run): TTFB 0.80 s, load delay 1.15 s, **load time 1.38 s**
(was 0.37 s), render delay 0.77 s. Cause: the hero now shares the single HTTP/2 connection with the ~10 JS chunks
requested in the same instant (one new 34 KiB chunk since the previous measurement), and the simulated throttling
splits the bandwidth between them; the separate media connection had been giving the hero its own bandwidth.
**Mobile LCP target not met.** Next step: revert #132 (or keep same-origin and delay non-critical JS), and attack TTFB
and render delay.

## Revert of #132 (#134), measured 2026-10-14 ~10:30 (UTC-3)
Hero back on `media.openuniversity.si` with `preconnect`. Lighthouse 12 mobile simulated: LCP 3.16 / 3.67 / 3.86 s →
**median 3.67 s**; three extra runs 3.81 / 3.73 / 2.93 s (median of 6: 3.70 s); FCP 1.44 s, TBT 82 ms, CLS 0,
482 KiB / 28 req. Better than same-origin (4.25 s) but **not back to 2.94 s**: run-to-run spread is ~0.9 s, and the JS
grew since the 09:45 measurement (one extra 34 KiB chunk from changes merged in the meantime). **Mobile LCP target not
met.** Next steps: find and defer that chunk, cut TTFB and render delay.

## First rail only eager, posters at low priority (#137), measured 2026-10-14 ~11:40 (UTC-3)
**The "new 34 KiB chunk" was not real.** The initial HTML of the 09:39 deploy (`4d43a9b`) and of current production
lists the same 13 JS/CSS files with the same sizes (one 73 KiB chunk only changed its hash). An interleaved Lighthouse A/B
on the two deployment URLs gave the same LCP (09:39 deploy 2.90 / 3.55 / 3.72 s, current 3.27 / 3.71 / 3.75 s): the
2.94 s of 09:45 was a low draw of a ~0.9 s run-to-run spread, not a regression.
Change: `EAGER_ROWS` 2 → 1 (the second rail is below the fold at 390 px and now waits for the viewport like the rest)
and the eager posters carry `fetchpriority="low"`, so the hero (the LCP, `fetchpriority="high"`) gets the bandwidth
first. No visual change. Lighthouse 12 mobile simulated, 5 runs on production: LCP 3.27 / 3.16 / 3.32 / 3.19 / 2.52 s →
**median 3.19 s** (3.70 s before); FCP 1.37 s, 26 req., JS 151 KiB. **Mobile LCP target still not met (3.19 s > 2.5 s).**
What remains in the simulated LCP: ~150 KiB of framework/app JS and the 37 KiB Inter preload sharing the throttled
link with the hero, and ~0.4 s render delay (JS execution under 4× CPU). TTFB on the wire is 0.12–0.25 s. Next levers,
each needing a decision because they can change what is seen: drop the Inter preload (possible font swap on first
paint), or trim client JS (hydrate the Home rails lazily).

## Inter preload experiments, measured 2026-10-14 ~12:40–13:10 (UTC-3), nothing shipped
Interleaved Lighthouse 12 mobile simulated runs against deployment URLs (production deploy vs. branch previews of
`perf/inter-defer`, never merged):
- **Production (Inter preloaded, high priority)**, 16 runs over three batches: LCP 2.18–3.73 s, **median 2.57 s**;
  CLS 0. The font arrives before the observed first paint in 5 of 6 checked runs (A4: 47 ms after).
- **No Inter preload** (`preload: false`), 11 runs: LCP 2.01–4.95 s, median 2.20 s in the first batch of 5 and 2.58 s in
  the second batch of 6 (vs. production 3.25 / 2.55 s in the same batches). **Rejected: visible change.** The font
  then finishes 0.1–0.4 s *after* the observed first paint in 10 of 11 runs, so Android/Windows/Linux visitors see
  the first frame in metric-matched Arial and then the swap to Inter (no layout shift, but a visible font change).
- **Low-priority preload** (plain `@font-face` on `/fonts/Inter.woff2` + `preload(..., { fetchPriority: "low" })`),
  11 runs: font before first paint (no swap), but LCP median 3.83 s in the 6-run batch (production 2.55 s);
  several runs had simulated FCP 2.2–3.0 s. **Rejected: no measurable gain, likely worse.**
- **Lazy hydration of the below-fold rails: not attempted.** The rails share the `BillboardSelection` client
  component (selecting a card changes the Billboard); its own code is a few KiB, while the ~150 KiB is React/Next
  runtime that every page needs, so deferring the rails cannot remove it without an architecture change.

Conclusion: the run-to-run spread (~1–2.5 s, bimodal on previews) is larger than any effect of these levers. Production
median of 16 runs is 2.57 s, at the 2.5 s target's edge. Inter stays preloaded at default priority. Next lever, if
needed, needs an architecture decision: a server-only Home (cards as links, no client selection) to cut hydration.

## Consequences
- A change that makes more posters eager, or a media budget raise, fails a unit test before review.
- JS, CSS and fonts are not in the CI estimate; they are measured on the wire after deploy.
- Cloudflare edge caching of the media host is a zone setting, outside this repo (`media.openuniversity.si` returns `HIT`).
