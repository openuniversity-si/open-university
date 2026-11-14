# ADR-21 — Course editions

Date: 2026-10-11 · Status: accepted (P6 of the dynamic catalog; builds on ADR-17 and ADR-18)

## Context
The import of 19 courses (RELATORIO-IMPORT-19, finding 3) had no notion of an edition: the Cornell Android course went out
with its Fall 2024 and Spring 2025 playlists flattened into one list, the semester in each title; CMU 11-785 and CMU 15-445
kept only the edition that had covers. Daniel's decision (10/10): **one page per course; editions (semester/year) inside
it, the most recent open by default; a new edition never becomes a new course; Lectures/Labs of the same code are parts
of an edition.** The design is in Figma ("Proto — Dynamic": EditionSelector 575:2023, EditionBadge 575:2024, the Edition
bar of the three Course frames) and in the 16 prints of `figma-dinamico/p0b-edicoes`.

## Decision
- **Model (0009).** `course_editions` (`edition-N` ids from `edition_seq`): `slug` (≤ 40, unique per course), `label`,
  `term` (spring | summer | fall | winter, or null), `year` (1990–2100), `position` (> 0, unique per course; 1 = newest =
  default), `resolution`, `source_playlist_ids` (informative, for a re-import), `revision`. `lessons.edition_id` and
  `lessons.part` (lectures | labs, default lectures). The lesson → edition link is a **composite foreign key**
  `(edition_id, course_id) → course_editions (id, course_id)` (RESTRICT), stronger than the plan's single-column FK: the
  database itself refuses a lesson whose edition belongs to another course. Order is per edition:
  `lessons_edition_position (edition_id, position)` replaces `lessons_course_position`.
- **The label is the term and the year, nothing else** ("Fall 2024", "2026"). The API refuses any other label with 422
  (`editionLabel(term, year)` in contracts.ts); the CLI derives it (`--label "Spring 2024 Lectures"` or `SP24` →
  "Spring 2024"). Words such as Lectures/Labs name a **part**, never an edition.
- **Slugs stay unique per course.** `/c/<course>/<lesson>` carries no edition, so every URL published before editions
  keeps working and the sitemap keeps one entry per course and per lesson. When two editions have a lesson with the same
  title, the second slug gets the usual numeric suffix (`uniqueSlug`: `lecture-1`, `lecture-1-2`); renaming is P7's slug
  command, with a redirect. A shared link to another edition is the course URL plus `?edition=<slug>`.
- **Positions by date, newest first.** A new edition, or one whose year/term changes, takes its place by
  `(year, term)` descending without disturbing the others' relative order (`placeByDate`; in a year, winter < spring <
  summer < fall, and a year without a term sorts before the termed ones). `PUT /courses/:id/editions/order` is the manual
  exception, audited with `manual: true`. Positions move through values above the current maximum, so `position > 0` and
  the unique index hold at every statement.
- **Backfill in the migration, one transaction.** 0009 creates the table and nullable columns, inserts the published
  editions (matched by course **slug**: ids differ per environment), splits Cornell Android by YouTube id (Spring 2025
  position 1, Fall 2024 position 2), gives any other course one edition named after the year it was created, renumbers
  positions per edition (relative order kept), and only then `SET NOT NULL`, adds the composite FK, the part CHECK and the
  new index. Every statement is idempotent (`IF NOT EXISTS`, guarded inserts); running the file again changes no row
  (`catalog-editions.int.test.ts`). Harvard DL Theory has **one** edition (2024): its dated videos are lessons, not
  editions (CATALOGO-AGRUPADO-2024 and raw.json agree). CMU 11-785 has the one published edition, Spring 2024; its other
  editions, CMU 15-445 Fall 2025, Backend, iOS and Berkeley RDI have no covers and are not imported here:
  `import --course … --edition …` adds them later ([editions.md](../catalog/editions.md)).
- **Release v2, old releases untouched.** `RELEASE_SCHEMA_VERSION = 2`: each course carries `editions` (by position,
  with lesson count, duration and lectures/labs counts), each lesson `editionId` and `part`; the schema checks ≥ 1
  edition per course, positions 1..N, counts equal to the lessons, a lesson's edition in its own course and `order`
  contiguous per edition. Stored releases are immutable (trigger of 0007) and never rewritten: `parseRelease` accepts
  version 1 and normalizes it **at read time** to one synthetic edition per course (`<course>-edition`, all lectures,
  same order), so activating release 1 or any other old release still works (`release activate`), and release #1 of the
  snapshot renders exactly as before. The sha always covers the stored bytes. The bake file keeps the stored payload;
  `bakedRelease()` normalizes it. A hidden lesson leaves no gap, and an edition whose lessons are all hidden is left out
  of the release with positions renumbered: hidden lessons are how a new edition is prepared.
- **Publish preconditions (412, complete list):** `editions.exists`, `editions.contiguous`, `editions.lessons` (an
  edition without any lesson), `lessons.edition`, `lessons.contiguous` (now per edition), `editions.ambiguous` (more than
  one edition and a year repeated without a term). The doctor adds `editions.orphan`, `lessons.edition_course`,
  `editions.gaps`, `lessons.gaps`, `editions.ambiguous`, `edition_seq` in `sequences.behind`, and the info finding
  `lesson.title.edition_prefix` (titles such as "[FA24] …"): approved copy is not edited by this change; editorial
  review (P7) decides.
- **API (ADR-18 contract).** `GET|POST /courses/:id/editions`, `PATCH|DELETE /editions/:id`,
  `PUT /courses/:id/editions/order`, `PUT /editions/:id/lessons/order`; audit actions `edition.create|update|reorder|delete`.
  Every lesson or edition change bumps the course revision. `POST /courses/:id/lessons` requires `editionId` (422 for
  another course's) and takes `part`; `PATCH /lessons/:id` moves a lesson to the end of another edition and compacts both.
  `PUT /courses/:id/lessons/order` stays for a course with one edition (409 `state_conflict` otherwise).
  `DELETE /editions/:id` is a dry run unless `confirm=true`; an edition with lessons needs `mode=with-lessons` (each
  lesson deleted as `DELETE /lessons/:id` would: progress kept, redirects to the course page when published, R2 after the
  commit); the last edition of a course is never deleted (409 `has_dependents`). Imports: `POST /imports/:id/draft`
  takes `courseId` + `edition` (a new edition, or more lessons for an existing one) and `part`; the import report
  suggests `labs` when a title or the playlist says Lab/Recitation.
- **Site.** Queries are per edition (`editionsForCourse`, `lessonsForEdition`, `editionOf`); `lessonNeighbors` never
  crosses editions; "Lecture N of M" counts inside the edition (N = position in the edition, M = its lesson count, as
  the Figma kicker "LECTURE 4 OF 26" of a 12 + 14 edition); a Labs lesson reads "Lab". Progress stays per lesson id; the
  Continue card's "of M" is the lesson's edition. Home cards and the course hero describe the default edition, where a
  course opens. A course with more than one edition gets the Edition bar under the hero (EditionSelector, a
  `tablist` labelled "Edition", arrow keys/Home/End, roving tabindex, the system focus ring), a summary line, one lesson
  list per edition (a `tabpanel`; "LECTURES · n" / "LABS · n" headers when both parts exist), the hero meta and the About
  "Length"/"Edition" rows of the selected edition. Every edition is in the server HTML with the others `hidden`, the
  default shown: no flash, no layout shift. The choice is client state mirrored to `?edition=` with
  `history.replaceState` (read through `useSyncExternalStore`, so the server never depends on the query). The Player
  shows the lesson's edition: its rail, the kicker prefix ("SPRING 2026 · …") and the EditionBadge; there is no edition
  switch there. A course with one edition renders the same HTML as before (proved with `scripts/html-snapshot.ts` on the
  test build, main vs this branch).

## Divergences from the brief (the repository wins)
- The course route was already `force-dynamic` (per-viewer progress, F11), so "keep the route static/ISR" does not apply;
  what the brief protects still holds: the server HTML never depends on `?edition=`.
- The CLI's course command is `course get` (P5), not `course show`; it lists the editions.
- `lessons_course_position` was the old index name; the single-column FK of the plan became the composite FK above.
- The release diff of the migration shows `editions` and `editionId` for every course and lesson, **plus** `order` for
  the 12 Spring 2025 lessons of Cornell Android (14..25 → 1..12): numbering per edition is the point of the change.
- Figma tokens could not be fetched (no `FIGMA_TOKEN` in the session): measurements come from the prints. Provisional
  until the Design answers `FIGMA-GAP-P6.md`: more tabs than fit scroll horizontally at the same 40 px height and 88 px per
  tab; hover has no visual change; the hero keeps whole hours while the bar summary uses one decimal, as printed.

## Rollout and rollback
- Prerequisite: the code before this change inserts lessons only through the admin API/import, which would fail after
  0009 (`edition_id` NOT NULL; the integration test proves the 23502). So: apply 0009 on each target, then promote the
  deploy, and run no import/publish in between.
- Rollback: `tower-catalog release activate <previous> --target prod --yes` (v1 releases stay readable); a failed deploy
  is Vercel's Instant Rollback; 0009 is additive (a course with one edition looks exactly as before).
