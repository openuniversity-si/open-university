# ADR-22 — Lesson slugs: one rule, renames with permanent redirects carried by the release

Status: deprecated by D-111 (the Open University product left this repository; PADRAO-DEV F3a).

Date: 2026-10-12 · Status: accepted (P7 of the dynamic catalog; builds on ADR-17, ADR-18 and ADR-21)

The P7 brief names this record ADR-20; that number already belonged to the Open University rebrand (ADR-20), and ADR-21
to course editions, so it is ADR-22.

## Context
The 386 lessons of the 19 imported courses got their slugs from raw YouTube titles (RELATORIO-IMPORT-19, finding 4):
long, with edition tags, course and channel names (`fa24-intro-to-android-bonus-lecture-2-industry-standards`). Daniel's
rule: fix it for good, with no SQL renames, no hand-written slug lists and no old URL that turns into a 404. The 126
lessons of the five original courses (2017) are legacy identity and stay.

## Decision
- **One rule** (`cleanLessonSlug`, `src/catalog/slug.ts`; [slugs](../catalog/slugs.md)): pure, deterministic, ≤ 60
  characters, `lecture-NN` when the title has a number. The import, `tower-catalog lesson reslug` and `doctor` use it;
  a 386-row fixture of production fails the tests when the rule moves a slug.
- **Renames are explicit and keep the old URL**: `PATCH /lessons/:id {slug}` for one lesson, `PUT /lessons/slugs` for
  one course's batch (all or nothing, swaps through an internal temporary slug, `Idempotency-Key` required). Both write
  `slug_redirects` in the same transaction: old path → new path, chains flattened (A→B→C becomes A→C, B→C), a return to
  an earlier slug drops its redirect, never a cycle or a self-redirect. Generation never renames an existing lesson.
- **Legacy by a fixed list**: `LEGACY_LESSON_IDS` (`src/catalog/slug-course.ts`), the same ids as the fixture.
- **The redirect lives in the release, not in a table read at run time.** `slug_redirects` is an authoring table; the
  release compiler copies it into the release payload, and the site answers 308 from the active release
  (`redirectFor`, `src/site/guard.ts`). Why:
  - **Atomic with the slugs.** A release is one immutable snapshot: the new slug and the redirect from the old one go
    live, and go away, together. A run-time table would change at commit time, while the pages still serve the active
    release: for a while the old URL would redirect to a page that does not exist yet (404), or the new slug would have
    no redirect from the old one.
  - **Rollback is one command.** `release activate <n before>` restores the old slugs and removes their redirects at
    once, with no table to edit by hand and no risk of redirects pointing at slugs the active release does not have.
  - **The same read path as everything else.** The site already reads the active release from the tagged Data Cache
    (ADR-17); one more lookup in it costs nothing, while a table read per request would add a database query to every
    `/c/…` page and a second source of truth for the sitemap, canonical URLs and the 404 page.
  - **Testable and diffable.** `release diff` shows the redirects that a publish adds or removes next to the slugs;
    `doctor` checks the table against the lessons before anything is published.
- **Proof on the live site** with reads only: `scripts/verify-slug-redirects.ts` (308 in one hop to the new slug, the new
  slug 200 with its canonical and `og:url`, the sitemap with the new paths and none of the old, a missing slug 404).

## Consequences
- A rename is visible only after the next publish; until then `doctor` reports `release.drift`.
- Activating an older release brings back older slugs, and the tables still hold the new ones: the next publish restores
  them. The runbook says so.
- An old path that another lesson takes over in a swap shows that lesson; it cannot redirect. The batch reports it
  (`plan.reused`).
- The reslug of the 386 production lessons is an executor's job (E7) after this code is deployed: dry-run, review, apply,
  publish, verify, first on preview and then on prod.
