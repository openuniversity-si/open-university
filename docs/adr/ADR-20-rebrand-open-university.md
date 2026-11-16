# ADR-20: Rebrand to Open University

Status: deprecated by D-111 (the Open University product left this repository; PADRAO-DEV F3a).
Accepted 11/10/2026 (Daniel's decision, 11:02 BRT). Figma first (file `t1sPlxRI6pcEk9LRxotS4w`), code after.

## Decision
- The whole site is **Open University** (`openuniversity.si`), "the free initiative of The Tower". The Tower stays as the organization behind it (About, Terms,
  Privacy, Contact) and as the future home of its own site. The repository, the `tower-*` test ids and CSS tokens, `TowerMark` and the `x-tower-actor` API header keep
  the old name: they are internal and not user-visible. Cookie names and storage keys are user-visible and carry the product name (see "Cookie prefix" below).
- **PR A (this one) = brand and copy.** `SITE_NAME`, `DEFAULT_TITLE` ("Open University — Great lecture courses, in order"), `TITLE_TEMPLATE` ("%s · Open University"),
  the OG alt, the TopNav `aria-label` ("Open University, Home"), the auth `appName`, the manifest (it reads `SITE_NAME`), `legal.ts` (Terms, Privacy, Contact, Home intro "About Open University") from `rebrand/pages.rebrand.json`, and a new `public/brand/og.jpg`.
  **PR B = origin and hosts**, described under "Origin and hosts" below.
- **Slogan removed.** "Make Education Great Again" (footer `FOOTER_MEGA`, `.mega` CSS, `--tower-footer-mega-*` tokens, the e2e test, the `Footer/MEGA` fidelity
  region) is gone from code and tests; a guardian in `legal.test.ts` and `e2e/shell.spec.ts` keeps it out. Old phase docs (`docs/phases`, `docs/fidelity`) keep their
  historical mentions of Addendum 2.8 on purpose: they describe what was built then.
- **About is interim.** Daniel (11:35 BRT) is rewriting the About (it read like a social network; the focus becomes support for university courses), so the long v3 draft in
  `pages.rebrand.json` was NOT used. `/about` keeps the production text (version 2B) with only the brand name changed (H1 "Open University", one sentence naming The Tower as
  the organization behind it), in its own file `src/site/pages/about.ts`: the single place to replace, together with the exact-text guardian in `legal.test.ts`. The new text
  and its Figma frame ship in a separate PR.
- **Permanent free commitment.** The Terms have a "Free, permanently" section ("Open University is free to use, permanently. We will not show ads, put lectures behind a paywall
  or charge anyone to watch.") and the Privacy says Open University "has committed never to" show advertising. It is limited to **cost and access**, and the Terms say it is not a
  promise that every lecture stays online (YouTube can remove videos). The test that forbade fixed promises was rewritten **on purpose** (see the comment in `legal.test.ts`): it
  now pins where "permanently" may appear (Terms description and section, Privacy "committed never to") and what it may cover. The About closing line of the v3 draft is not live
  yet; it comes with the rewritten About. Changing the commitment means changing About, Terms, Privacy and that test together.
- **Not open source.** The repository is private, so no copy says "open source" / "código aberto" ("open" means open to everyone). A guardian rejects the phrase.
  Opening the code is the founder's intent for later; when the repository is published, the copy can say so.
- **Not a university.** "Open University" is the name of an initiative, not of an educational institution; it grants no degrees or credit and is not affiliated with
  or endorsed by The Open University (United Kingdom) or any other institution. The literal notice stays in the Terms ("Name and affiliation") and is guarded.
  Risk accepted by the founder: the UK institution holds the "The Open University" mark (US, Madrid registration); no search was run at INPI/EUIPO/UKIPO.
- **Contact** is `contact@example.org` (Cloudflare Email Routing, since 14 October 2026; the old domain address is retired).
- **Header, icons and favicon stay.** The header shows only the TowerMark (the name lives in `<title>`, the `aria-label` and About), so no layout changed. The Figma
  wordmark option B (mark + name) is kept as a future switch.
- **OG card.** The Figma frame "OG image — 1200x630" (page 18:3, node `591:10621`) is the source of `public/brand/og.jpg`; `pnpm brand:og` renders it with the same numbers
  (dark #0c0c0c, silver glows, glass card, TowerMark, Inter, no slogan, no tree art). Change the frame first, then `scripts/brand-og.ts`.
- **Cookie prefix** is `open-university` (changed 2026-10-11, after the host switch had already signed everyone out once): `open-university.session_token` (`__Secure-` on HTTPS), `open-university-preview` (admin draft preview) and the `open-university:*` sessionStorage keys. One constant, `BRAND_ID` in `src/site/brand-ids.ts`; `brand-ids.test.ts` fails if a name says "tower" or is hard-coded elsewhere. The Privacy page cites the prefix (Figma 540:10515 / 540:10355 first). Still named "tower" on purpose, not user-visible: `data-testid="tower-*"`, CSS tokens, `x-tower-actor`, bucket `the-tower-media`, `media.thetower.si` (media host, own migration).

## Origin and hosts (PR B)
- `PRODUCTION_ORIGIN = https://openuniversity.si` (apex, no www). It feeds `metadataBase`, every canonical link and `og:url`, `sitemap.ts`, the `Sitemap:` line of `robots.ts`, the
  auth fallback (`resolveAuthBaseURL`), `perf-budget` and the production e2e. `CANONICAL_HOST` is derived from it.
- `src/site/hosts.ts` has one list per kind of redirect. **`thetower.si` and `www.thetower.si` redirect temporarily (307)** to the same path and query on `openuniversity.si`:
  The Tower will get its own site later, so browsers and search engines must not cache the move as permanent. `www.openuniversity.si`, `theopenuniversity.si` and
  `www.theopenuniversity.si` redirect permanently (308) to the apex. `next.config.ts` `redirects()` carries these rules (`has: host`); the Vercel project redirects the same
  hosts at the edge, so the code is the declarative record and the fallback. `alternateHostHeaders()` (ADR-19) is gone: an alternate host no longer serves pages.
- **Media host (2026-10-11):** `media.thetower.si` is replaced by **`media.openuniversity.si`**, a custom domain on the new bucket `open-university-media` (R2 cannot rename buckets), with no fallback and no coexistence period. One constant (`MEDIA_PUBLIC_HOST`, `src/media/types.ts`) and a guardian test (`media-host.test.ts`); runbook in `docs/media/README.md`. The CSP, `next.config.ts` `remotePatterns`, the URL schema and the tools derive from it.
- **Auth.** `AUTH_URL` (Production) must be `https://openuniversity.si`; the cookie prefix stays `tower`. Cookies are per host, so everyone signs in again once. Google OAuth must
  list the new callback URI and origin (`docs/operations/google-oauth.md`); until it does, sign-in fails with `redirect_uri_mismatch`.
- **tower-catalog** may send the admin secret to `openuniversity.si` (exact host) and the project's `vercel.app` deployments; `TOWER_MEDIA_URL_PROD` should (thetower.si was removed from the allow-list in #119, for tower-media too)
  name `openuniversity.si`, because a redirect drops the Authorization header.
- **SEO.** With a 307 Google keeps thetower.si indexed, so the Search Console property and sitemap for `openuniversity.si` are added by the founder (not by code).

## Guardians
`src/site/pages/legal.test.ts` (interim About text, university rule, non-affiliation, the permanent commitment, no slogan, no "open source"), `src/site/metadata.test.ts`,
`e2e/about.spec.ts`, `e2e/shell.spec.ts` (footer without slogan), `e2e/metadata.production.ts` (titles, `og:site_name`, manifest name), `src/site/hosts.test.ts`, `e2e/alternate-host.spec.ts`
(307/308, path, query and method kept) and `e2e/alternate-host.production.ts`.
