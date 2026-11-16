# ADR-16: Static Home for visitors; signed-in Home by dynamic rewrite

Status: deprecated by D-111 (the Open University product left this repository; PADRAO-DEV F3a).
Accepted 10/10/2026 (v02); closes the ADR-15 backlog item on the Home's TTFB and CLS.

## Decision
- `/` (`src/app/page.tsx`) is ISR (`revalidate = 300`) and reads no request data: `signedOutHome` + `homeMedia()`.
- `src/proxy.ts` checks only the **presence** of the session cookie (`open-university.session_token` or `__Secure-open-university.session_token`,
  `SESSION_COOKIE_NAMES` in `src/auth/settings.ts`) and rewrites such requests to `/signed-in-home` (`force-dynamic`, noindex),
  which renders today's `signedInHome` (or the signed-out Home for an expired cookie). The URL stays `/`; a direct request to
  `/signed-in-home` is a 404. The proxy runs before the Vercel cache, so the cached `/` only ever holds visitor HTML; the
  rewritten response is `private, no-cache, no-store` and is never prerendered.
- The root `loading.tsx` moved to `src/app/c/loading.tsx`: outside `/c` nothing streams a skeleton first, so the Home has no
  skeleton-to-content shift (CLS ~0.03–0.044 before, 0 after) and a render failure is a real 500 (`/fixtures/error`).
- Region stays `iad1`, next to Neon AWS `us-east-1` (`docs/operations/database.md`); `gru1` would lengthen every DB query.

## Media invalidation
Every media change through the admin API / `tower-media` (put, rollback, delete) and `POST /api/media/revalidate` calls
`invalidateMediaTag` (`src/media/invalidate.ts`): `revalidateTag(media…)` **and** `revalidatePath("/")`. The 300 s revalidate is
the safety net. A production build without `APP_DATABASE_URL` (CI on `main`) prerenders the Home without covers (`getMedia`
returns `[]` only in `phase-production-build`); Vercel builds have the variable. The test build's FakeMedia manifest is read
at build time, so `.fidelity-cache/media` must exist before `pnpm build:test` (nightly order).

## Guardians
`scripts/static-home-check.ts` after both builds (`/` in the prerender manifest with revalidate ≤ 300 s; `/signed-in-home` never);
`src/site/home-routing.test.ts` (cookie routing, route config); `e2e/home-static.spec.ts` (390/1440, CLS ≤ 0.03, no signed-in
document/fetch response is `public`/`s-maxage`).
