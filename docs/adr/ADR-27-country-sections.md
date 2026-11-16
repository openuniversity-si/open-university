# ADR-27 — Universities grouped by country

Status: deprecated by D-111 (the Open University product left this repository; PADRAO-DEV F3a).

Date: 2026-10-17 · Status: accepted (Daniel, 17/10: H2 "Small dose, true color" chosen at 17:51; scope set at 17:55)

## Context
With the NPTEL institutions (India) next to the 17 American universities, one mixed grid no longer shows where a
university is from. Europe and Brazil come later. Daniel asked to keep the Universities page exactly as it is (hero,
title, the full grid of cards with their names and counts) and only group that grid by country.

## Decision
- **Figma first.** The component `CountryHeader` (655:3545, page "Concepts — Country section", section "Header — hipoteses")
  has variants Device (Desktop/Mobile) × Country (US/EU/IN/BR). The name and count come from the Country variables; the
  order comes from Country Rank (US 1, Europe 2, India 3, Brazil 4). It is applied to the live frames 622:2813 (1440) and
  622:3121 (390): United States, then India, each followed by its full grid of the same cards. Hypotheses H1–H5 stay archived.
- **One component for every country.** A true-colour lapel flag at its official ratio (US 19:10, India 3:2,
  Brazil 10:7, Europe 3:2; height 20 px desktop / 16 px mobile; the width follows), the name in the UI stack (Inter)
  with the existing section-title style **Display/Rail** (26 px Semi Bold; Display/Rail Mobile 20 px), the same style as
  the rail titles of the university pages, a quiet count "N universities · N courses" (right on desktop, under the name
  on mobile), and a hairline that dissolves on a smoothstep curve.
  No per-country visual tier: the rank order is the only hierarchy.
- **Data, not JSX.** `src/catalog/countries.ts` holds the countries (id, name, rank, place endings). A university belongs
  to the country its release `place` ends with: a U.S. state code ("Cambridge, MA"), "India" ("Chennai, India"), a
  European country, or "Brazil". Groups follow `rank`; inside a group, the Home row order. Adding Brazil or Europe only
  needs publishing universities with such places. No catalog field or migration was added.
- **Empty countries are hidden.** Only universities with published courses exist on the page (`universities()`), so
  India appears by itself once its NPTEL rows are published. A university whose place names no configured country is
  never hidden: it goes in a last group titled `otherCountriesTitle` (`More universities`), without a flag.
- **Flags are inline SVG** (`src/ui/CountrySection/flags.ts`), drawn from the official sheets at 64 units high, with no
  padding and never stretched (CSS sets the height, `aspect-ratio` the width). At this size Brazil omits the motto band and
  stars, like the Figma component.
- **Font (correction, Daniel 17/10 18:25).** PR #157 first set the name in Libre Caslon with a woff2 subset; that was
  wrong: since 08/10 the UI font is the system stack (`-apple-system, BlinkMacSystemFont`, self-hosted Inter,
  `sans-serif`; Inter in Figma) and Libre Caslon belongs only to the logo/wordmark (SVG). The subset, its loader and its
  script were removed; `src/ui/font-identity.test.ts` now fails on any other font family, `@font-face`, font token,
  next/font loader, inline `fontFamily` or served web font outside the logo (src/ui/TowerMark).
- Tests: `countries.test.ts` (rank order from data, hidden empty countries, nothing dropped) and `flags.test.ts`
  (official ratios, flag fills its box exactly), `font-identity.test.ts` (type identity guard).

## Amendment (Daniel, 2026-10-23)
CountryHeader 655:3545 no longer has an EU variant. The countries are United States, France, Italy, Germany, Spain,
Switzerland, the United Kingdom, India and Brazil, in that rank order. The flag set 652:2812 supplies FR 685:4, IT 685:9,
DE 685:14, ES 685:19 (no crest), CH 685:24 and GB 685:29, at the official ratios 3:2, 3:2, 5:3, 3:2, 1:1 and 2:1.
Place endings that named no one of those countries are gone. A university whose place still ends with one of them is
shown under `otherCountriesTitle` (`More universities`), the registered key in
`apps/web/src/catalog/domain/config/values.json`. The UI reads that key. The value is not repeated in code.
