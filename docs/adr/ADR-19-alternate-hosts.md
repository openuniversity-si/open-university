# ADR-19: Alternate hosts (Open University, openuniversity.si)

Status: deprecated by D-111 (the Open University product left this repository; PADRAO-DEV F3a).
Accepted 11/10/2026. **Superseded the same day by ADR-20 (rebrand):** `openuniversity.si` became the canonical host and `thetower.si` and `www.thetower.si` redirect to it with a
temporary 307; the mechanism below (one list in `hosts.ts`, nothing built from the request host) stays, but the alternate hosts no longer serve pages or send a `Link` canonical
header: `alternateHostRedirects()` replaces `alternateHostHeaders()`. The text below is the original decision, kept as history.

## Decision
- `www.thetower.si` stays the one canonical host and the brand. `openuniversity.si` ("Open University", an open initiative of The Tower) is an
  extra address of the **same app**: it answers 200 with the same pages, and `www.openuniversity.si`, `theopenuniversity.si` and
  `www.theopenuniversity.si` are listed as well (the Vercel project redirects the www/second-domain hosts to `openuniversity.si`).
- **One list**: `ALTERNATE_HOSTS` in `src/site/hosts.ts`. A new address is one more entry there plus the domain in the Vercel project.
- **Nothing is built from the request host.** `metadataBase`, every `<link rel=canonical>`, `og:url`, the sitemap URLs and the robots.txt
  `Sitemap:` line come from `PRODUCTION_ORIGIN`, so they name `https://www.thetower.si` whatever host answered.
- `next.config.ts` adds `Link: <https://www.thetower.si/…>; rel="canonical"` on every path of an alternate host (`alternateHostHeaders()`:
  one rule for `/`, one for `/:path+`, matched with `has: host`). Next leaves an empty `:path*` uninterpolated, hence the two rules.
- **No noindex** on alternate hosts (ADR-12 holds: production is indexable, previews are noindex); they only point at the canonical.
- Copy: About, Terms, Privacy and Contact say that The Tower is also reached at openuniversity.si as Open University, free to use today,
  lectures credited to their sources; the Terms disclaim any affiliation with The Open University (United Kingdom) or any institution.
  The brand never calls itself a university; "Open University" is only the name of the address and initiative (`legal.test.ts`).

## Guardians
`src/site/hosts.test.ts` (list, roles, header rules, next.config wiring, no alternate host in metadata/sitemap/robots),
`src/site/pages/legal.test.ts` ("Open University copy"), `e2e/alternate-host.spec.ts` (HTTP with a `Host` header on the test server) and
`e2e/alternate-host.production.ts` (production-like: no X-Robots-Tag, `index, follow`, canonical pointers only).
