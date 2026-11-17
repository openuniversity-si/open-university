import { cpSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { drizzle } from "drizzle-orm/node-postgres";
import { migrate } from "drizzle-orm/node-postgres/migrator";
import pg from "pg";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
vi.mock("server-only", () => ({}));
vi.mock("next/cache", () => ({ unstable_cache: (read: () => unknown) => read }));
vi.mock("next/headers", () => ({ draftMode: () => Promise.resolve({ isEnabled: false }) }));
import { migrationsFolder, runMigrations } from "../../scripts/lib/migrations.ts";
import { readActiveRelease } from "../../src/catalog/server/read.ts";
import { swapMedia } from "../../src/media/server/repository.ts";
import {
  approvedText, auditRows, call, coverInput, createHarness, defaultEdition, newVideoId, revisionOf, seedCatalog, seedDraftCourse, seedLesson, seedProgress, testDatabaseUrl,
  type DeleteReportData, type DoctorData, type Harness, type LessonData, type PublicationData, type ReleaseData, type Seed,
} from "../fixtures/admin-catalog.ts";
import { asReleaseV1 } from "../fixtures/release.ts";
import { MIGRATION_COUNT } from "../fixtures/migrations.ts";

// Course editions (ADR-21) on PG18: the 0009 backfill on a database shaped like the real one, and the edition routes.

/** The 24 published courses by slug (prod/preview ids differ, so the backfill matches slugs), the 25 Cornell videos by edition. */
const SLUGS = [
  "biblical-series-genesis", "maps-of-meaning", "personality-and-its-transformations", "awakening-from-the-meaning-crisis", "after-socrates",
  "mit-perception", "mit-public-finance", "mit-deep-learning", "mit-social-problems-of-nuclear-energy", "mit-game-theory", "yale-can-it-happen-here-again",
  "yale-america-at-250", "yale-marxs-capital", "harvard-cs50x", "harvard-cs50-for-business", "harvard-cs50-2d-game-development", "harvard-deep-learning-theory",
  "stanford-understand-energy", "stanford-economics-of-transformative-ai", "stanford-lung-cancer-journey", "cmu-introduction-to-deep-learning",
  "cmu-intro-to-database-systems", "cmu-advanced-database-systems", "cornell-android-course",
];
const FALL_2024 = ["r2t59qN5uHM", "EKlThtzdSak", "bitltGz7_yM", "ncZYovxdDIA", "Su_-GcFpY18", "llTohaKL_7Y", "elfX3fMqTkA", "IILAuo8nZGY", "Bc2Hu8mA-44", "sLa4zDLIC10", "vbGMOYKulv8", "jz-mhdVnU2E", "NkMKEhXsYU4"];
const SPRING_2025 = ["3KuD7j-B2nA", "7_yF4pMkrqU", "Ri6oLJTIj20", "dLSDcOnuYys", "osxlrcVAYaI", "p9JbsHTSeMU", "OlTXvLaEGE8", "co-8xgAI98c", "9nAhBs6pdJM", "-t67tvKghSQ", "6sPTzvw8JNk", "LY9e7PvTZH0"];

/** The migrations folder up to (and including) `last`, for a database "as it was" before 0009. */
function migrationsUpTo(last: number): string {
  const folder = mkdtempSync(join(tmpdir(), "tower-migrations-"));
  cpSync(migrationsFolder, folder, { recursive: true });
  const journalPath = join(folder, "meta", "_journal.json");
  const journal = JSON.parse(readFileSync(journalPath, "utf8")) as { entries: { idx: number }[] };
  writeFileSync(journalPath, JSON.stringify({ ...journal, entries: journal.entries.filter((entry) => entry.idx <= last) }));
  return folder;
}

const STATE = `SELECT
  (SELECT coalesce(jsonb_agg(to_jsonb(e) - 'created_at' - 'updated_at' ORDER BY e.id), '[]') FROM course_editions e) AS editions,
  (SELECT jsonb_agg(jsonb_build_object('id', l.id, 'edition', l.edition_id, 'part', l.part, 'position', l.position) ORDER BY l.id) FROM lessons l) AS lessons`;

describe("migration 0009 (course editions) on PG18", () => {
  let client: pg.Client;
  beforeAll(async () => {
    client = new pg.Client({ connectionString: testDatabaseUrl() });
    await client.connect();
  });
  afterAll(async () => {
    // Leave the database fully migrated and empty for the next suite.
    await client.query("DROP SCHEMA public CASCADE; CREATE SCHEMA public; DROP SCHEMA IF EXISTS drizzle CASCADE");
    await runMigrations(testDatabaseUrl(), false);
    await client.end();
  });

  it("backfills one edition per course (two for Cornell Android), renumbers per edition, then requires the edition; a second run changes nothing", async () => {
    await client.query("DROP SCHEMA public CASCADE; CREATE SCHEMA public; DROP SCHEMA IF EXISTS drizzle CASCADE");
    await migrate(drizzle(client), { migrationsFolder: migrationsUpTo(8) });
    await client.query("INSERT INTO authors (id, slug, name, monogram) VALUES ('author-1', 'a', 'A', 'A')");
    // Course ids out of slug order, as on preview (course-7..25 there, course-6..24 in prod), plus one course the backfill does not know.
    const slugs = [...SLUGS, "made-after-the-import"];
    for (const [index, slug] of slugs.entries()) {
      await client.query("INSERT INTO courses (id, slug, author_id, title, created_at) VALUES ($1, $2, 'author-1', $2, '2026-03-01T00:00:00Z')", [`course-${String(index + 7)}`, slug]);
    }
    let lessonNumber = 0;
    const addLesson = async (courseId: string, position: number, youtubeId: string) => {
      lessonNumber += 1;
      const id = `lesson-${String(lessonNumber)}`;
      await client.query("INSERT INTO lessons (id, course_id, slug, position, youtube_title, duration_seconds) VALUES ($1, $2, $3, $4, $3, 600)", [id, courseId, `l-${String(lessonNumber)}`, position]);
      await client.query("INSERT INTO lesson_videos (lesson_id, provider, external_id, status, checked_at, checked_by) VALUES ($1, 'youtube', $2, 'ok', now(), 'oembed')", [id, youtubeId]);
      return id;
    };
    const cornell = `course-${String(SLUGS.indexOf("cornell-android-course") + 7)}`;
    // Cornell as imported: Fall 2024 at 1..13, then Spring 2025 at 14..25 (order within each playlist preserved).
    const cornellLessons = [];
    for (const [index, youtubeId] of [...FALL_2024, ...SPRING_2025].entries()) cornellLessons.push(await addLesson(cornell, index + 1, youtubeId));
    for (const [index] of slugs.entries()) {
      const courseId = `course-${String(index + 7)}`;
      if (courseId === cornell) continue;
      for (let position = 1; position <= 2; position += 1) await addLesson(courseId, position, `v${String(index).padStart(3, "0")}000000${String(position)}`);
    }

    expect(await runMigrations(testDatabaseUrl(), false)).toEqual({ applied: MIGRATION_COUNT, pending: 0 });

    const { rows: editions } = await client.query<{ course_id: string; slug: string; label: string; term: string | null; year: number; position: number; source_playlist_ids: string[] }>(
      "SELECT e.course_id, e.slug, e.label, e.term, e.year, e.position, e.source_playlist_ids FROM course_editions e ORDER BY e.course_id, e.position");
    const byCourse = (courseId: string) => editions.filter((edition) => edition.course_id === courseId);
    expect(byCourse(cornell).map((edition) => [edition.slug, edition.label, edition.term, edition.year, edition.position])).toEqual([
      ["spring-2025", "Spring 2025", "spring", 2025, 1], ["fall-2024", "Fall 2024", "fall", 2024, 2],
    ]);
    for (const [index, slug] of slugs.entries()) if (slug !== "cornell-android-course") expect(byCourse(`course-${String(index + 7)}`), slug).toHaveLength(1);
    const edition = (slug: string) => byCourse(`course-${String(slugs.indexOf(slug) + 7)}`)[0];
    expect(edition("biblical-series-genesis")).toMatchObject({ slug: "2017", label: "2017", term: null, year: 2017, source_playlist_ids: ["PL22J3VaeABQD_IZs7y60I3lUrrFTzkpat"] });
    expect(edition("harvard-deep-learning-theory")).toMatchObject({ slug: "2024", label: "2024", term: null, year: 2024 });
    expect(edition("cmu-introduction-to-deep-learning")).toMatchObject({ slug: "spring-2024", label: "Spring 2024", term: "spring", year: 2024 });
    expect(edition("yale-can-it-happen-here-again")).toMatchObject({ slug: "2024", label: "2024" });
    expect(edition("stanford-economics-of-transformative-ai")).toMatchObject({ slug: "summer-2025", label: "Summer 2025", term: "summer" });
    expect(edition("made-after-the-import")).toMatchObject({ slug: "2026", label: "2026", term: null, year: 2026, source_playlist_ids: [] });

    const { rows: lessons } = await client.query<{ id: string; slug: string; position: number; part: string }>(
      "SELECT l.id, e.slug, l.position, l.part FROM lessons l JOIN course_editions e ON e.id = l.edition_id AND e.course_id = l.course_id WHERE l.course_id = $1 ORDER BY e.position, l.position", [cornell]);
    expect(lessons.map((lesson) => [lesson.id, lesson.slug, lesson.position])).toEqual([
      ...cornellLessons.slice(13).map((id, index) => [id, "spring-2025", index + 1]), ...cornellLessons.slice(0, 13).map((id, index) => [id, "fall-2024", index + 1]),
    ]);
    expect(new Set(lessons.map((lesson) => lesson.part))).toEqual(new Set(["lectures"]));
    const { rows: [nullable] } = await client.query<{ is_nullable: string }>("SELECT is_nullable FROM information_schema.columns WHERE table_name = 'lessons' AND column_name = 'edition_id'");
    expect(nullable?.is_nullable).toBe("NO");
    const { rows: indexes } = await client.query<{ indexname: string }>("SELECT indexname FROM pg_indexes WHERE tablename = 'lessons' ORDER BY 1");
    expect(indexes.map((row) => row.indexname)).toEqual(["lessons_course_slug", "lessons_edition_position", "lessons_pkey"]);

    // The previous deploy inserts lessons without an edition; after 0009 that fails, hence no import/publish between the migration and the promotion (ADR-21).
    await expect(client.query("INSERT INTO lessons (course_id, slug, position, youtube_title, duration_seconds) VALUES ($1, 'old-code', 99, 'Old', 60)", [cornell])).rejects.toMatchObject({ code: "23502" });

    // Idempotent: the whole file again, statement by statement, changes no row.
    const before: unknown = (await client.query(STATE)).rows[0];
    const sql = readFileSync(join(migrationsFolder, "0009_course_editions.sql"), "utf8");
    await client.query("BEGIN");
    for (const statement of sql.split("--> statement-breakpoint")) await client.query(statement);
    await client.query("COMMIT");
    expect((await client.query(STATE)).rows[0]).toEqual(before);
    expect(await runMigrations(testDatabaseUrl(), false)).toEqual({ applied: MIGRATION_COUNT, pending: 0 });
  });
});

describe("admin catalog: course editions on PG18", () => {
  let h: Harness;
  let seed: Seed;
  beforeAll(() => { h = createHarness(); });
  afterAll(async () => { await h.close(); });
  beforeEach(async () => { seed = await seedCatalog(h); });
  const key = () => `k-${Math.random().toString(36).slice(2)}`;
  const order = async (courseId: string) => (await h.pool.query<{ slug: string }>("SELECT slug FROM course_editions WHERE course_id = $1 ORDER BY position", [courseId])).rows.map((row) => row.slug);
  const lessonOrder = async (editionId: string) => (await h.pool.query<{ id: string }>("SELECT id FROM lessons WHERE edition_id = $1 ORDER BY position", [editionId])).rows.map((row) => row.id);
  const create = (courseId: string, body: Record<string, unknown>) => call<{ edition: { id: string; position: number }; order: string[]; courseRevision: number }>(h, "POST", `/courses/${courseId}/editions`, { key: key(), body });

  it("places a new edition by year and term, newest first, and keeps the others' relative order", async () => {
    const before = await revisionOf(h, "courses", seed.courses.alpha);
    const spring = await create(seed.courses.alpha, { slug: "spring-2026", label: "Spring 2026", term: "spring", year: 2026, resolution: "1080p", sourcePlaylistIds: ["PLspring2026x"] });
    expect([spring.status, spring.data.edition.position, spring.data.courseRevision]).toEqual([201, 1, before + 1]);
    await create(seed.courses.alpha, { slug: "2024", label: "2024", year: 2024 });
    const sameYear = await create(seed.courses.alpha, { slug: "fall-2024", label: "Fall 2024", term: "fall", year: 2024 });
    expect(sameYear.status).toBe(422);
    expect(sameYear.body.error?.message).toMatch(/share the year 2024 without a distinct variant/);
    const fall = await create(seed.courses.alpha, { slug: "fall-2024", label: "Fall 2024", term: "fall", year: 2024, variant: { kind: "term", label: "fall" } });
    expect(fall.status).toBe(201);
    const winter = await create(seed.courses.alpha, { slug: "winter-2025", label: "Winter 2025", term: "winter", year: 2025 });
    expect(winter.status).toBe(422);
    expect(await order(seed.courses.alpha)).toEqual(["spring-2026", "fall-2025", "fall-2024", "2024"]);
    expect((await auditRows(h, { action: "edition.create" })).map((row) => row.entity_kind)).toEqual(["edition", "edition", "edition"]);

    const taken = await create(seed.courses.alpha, { slug: "fall-2024", label: "Fall 2024", term: "fall", year: 2024 });
    expect([taken.status, taken.body.error?.code]).toEqual([409, "slug_taken"]);
    const label = await create(seed.courses.alpha, { slug: "spring-2024", label: "Spring 2024 Lectures", term: "spring", year: 2024 });
    expect([label.status, label.body.error?.code, label.body.error?.details]).toEqual([422, "unprocessable", { expected: "Spring 2024" }]);

    const listed = await call<{ editions: { slug: string; counts: { lessons: number } }[] }>(h, "GET", `/courses/${seed.courses.alpha}/editions`);
    expect(listed.data.editions.map((edition) => [edition.slug, edition.counts.lessons])).toEqual([["spring-2026", 0], ["fall-2025", 3], ["fall-2024", 0], ["2024", 0]]);
  });

  it("re-dates an edition into its place (PATCH) and takes a manual order (PUT …/editions/order) with an exact permutation", async () => {
    const older = await create(seed.courses.alpha, { slug: "fall-2024", label: "Fall 2024", term: "fall", year: 2024 });
    const id = older.data.edition.id;
    const patched = await call<{ edition: { position: number; revision: number } }>(h, "PATCH", `/editions/${id}`, { body: { expectedRevision: 1, slug: "fall-2026", label: "Fall 2026", year: 2026 } });
    expect(patched.data.edition).toMatchObject({ position: 1, revision: 2 });
    expect(await order(seed.courses.alpha)).toEqual(["fall-2026", "fall-2025"]);
    const stale = await call(h, "PATCH", `/editions/${id}`, { body: { expectedRevision: 1, resolution: "720p" } });
    expect([stale.status, stale.body.error?.code]).toEqual([409, "revision_conflict"]);
    const mismatch = await call(h, "PATCH", `/editions/${id}`, { body: { expectedRevision: 2, year: 2027 } });
    expect([mismatch.status, mismatch.body.error?.code]).toEqual([422, "unprocessable"]);

    const revision = await revisionOf(h, "courses", seed.courses.alpha);
    const partial = await call(h, "PUT", `/courses/${seed.courses.alpha}/editions/order`, { body: { editionIds: [id], expectedRevision: revision } });
    expect([partial.status, partial.body.error?.details]).toEqual([422, { missing: [seed.editions.alpha], unknown: [], duplicated: [] }]);
    const manual = await call(h, "PUT", `/courses/${seed.courses.alpha}/editions/order`, { body: { editionIds: [seed.editions.alpha, id], expectedRevision: revision } });
    expect(manual.data).toEqual({ editionIds: [seed.editions.alpha, id], revision: revision + 1 });
    expect(await order(seed.courses.alpha)).toEqual(["fall-2025", "fall-2026"]);
    expect(await auditRows(h, { action: "edition.reorder" })).toMatchObject([{ after: { manual: true } }]);
  });

  it("keeps lessons inside an edition: create with editionId (422 for another course's), move between editions, reorder per edition", async () => {
    const spring = (await create(seed.courses.alpha, { slug: "spring-2026", label: "Spring 2026", term: "spring", year: 2026 })).data.edition.id;
    const foreign = await call(h, "POST", `/courses/${seed.courses.alpha}/lessons`, { key: key(), body: { editionId: seed.editions.beta, youtubeId: newVideoId(), durationSeconds: 600 } });
    expect([foreign.status, foreign.body.error?.code]).toEqual([422, "unprocessable"]);
    const lab = await call<LessonData>(h, "POST", `/courses/${seed.courses.alpha}/lessons`, { key: key(), body: { editionId: spring, part: "labs", youtubeId: newVideoId(), durationSeconds: 600 } });
    expect(lab.data.lesson).toMatchObject({ editionId: spring, part: "labs", position: 1 });

    const [first, second, third] = seed.lessons.alpha;
    const revision = await revisionOf(h, "lessons", second ?? "");
    const moved = await call<LessonData>(h, "PATCH", `/lessons/${second ?? ""}`, { body: { expectedRevision: revision, editionId: spring } });
    expect(moved.data.lesson).toMatchObject({ editionId: spring, position: 2 });
    expect(await lessonOrder(seed.editions.alpha)).toEqual([first, third]);
    expect((await h.pool.query<{ position: number }>("SELECT position FROM lessons WHERE edition_id = $1 ORDER BY position", [seed.editions.alpha])).rows.map((row) => row.position)).toEqual([1, 2]);

    const courseRevision = await revisionOf(h, "courses", seed.courses.alpha);
    const old = await call(h, "PUT", `/courses/${seed.courses.alpha}/lessons/order`, { body: { lessonIds: [third, first], expectedRevision: courseRevision } });
    expect([old.status, old.body.error?.code]).toEqual([409, "state_conflict"]);
    const outside = await call(h, "PUT", `/editions/${spring}/lessons/order`, { body: { lessonIds: [second, lab.data.lesson.id, first], expectedRevision: courseRevision } });
    expect([outside.status, outside.body.error?.details]).toEqual([422, { missing: [], unknown: [first], duplicated: [] }]);
    const reordered = await call(h, "PUT", `/editions/${spring}/lessons/order`, { body: { lessonIds: [second, lab.data.lesson.id], expectedRevision: courseRevision } });
    expect(reordered.data).toEqual({ editionId: spring, lessonIds: [second, lab.data.lesson.id], revision: courseRevision + 1 });

    // GET /courses/:id: editions with counts, lessons with their edition and part.
    const detail = await call<{ editions: { slug: string; counts: { parts: { lectures: number; labs: number } } }[]; lessons: { id: string; editionId: string; part: string }[] }>(h, "GET", `/courses/${seed.courses.alpha}`);
    expect(detail.data.editions.map((edition) => [edition.slug, edition.counts.parts])).toEqual([["spring-2026", { lectures: 1, labs: 1 }], ["fall-2025", { lectures: 2, labs: 0 }]]);
    expect(detail.data.lessons.map((lesson) => lesson.id)).toEqual([second, lab.data.lesson.id, first, third]);
  });

  it("publishes release v2 with editions, parts and per-edition order; refuses an empty edition and an ambiguous year (412)", async () => {
    const draft = await seedDraftCourse(h, seed, "two-editions", { lessons: 2 });
    await h.pool.query("UPDATE courses SET status = 'review' WHERE id = $1", [draft.id]);
    const older = (await create(draft.id, { slug: "2024", label: "2024", year: 2024 })).data.edition.id;
    const publish = () => revisionOf(h, "courses", draft.id).then((revision) => call<PublicationData>(h, "POST", `/courses/${draft.id}/publish`, { key: key(), body: { expectedRevision: revision, note: "Editions", allowOrphan: true } }));
    const empty = await publish();
    expect([empty.status, (empty.body.error?.details as { failed: { rule: string; entity: string }[] }).failed]).toEqual([412, [{ rule: "editions.lessons", entity: `edition:${older}`, message: "Edition 2024 has no lesson." }]]);
    const lab = await seedLesson(h.pool, draft.id, { editionId: older, part: "labs" });
    await expect(h.pool.query("INSERT INTO course_editions (course_id, slug, label, year, position) VALUES ($1, 'second-2024', '2024', 2024, 3)", [draft.id])).rejects.toMatchObject({ code: "23505", constraint: "course_editions_course_year_variant" });
    const published = await publish();
    expect(published.status).toBe(200);
    const release = (await call<ReleaseData>(h, "GET", `/releases/${String(published.data.release.number)}`)).data.release.payload;
    expect(release.schemaVersion).toBe(2);
    const course = release.courses.find((entry) => entry.id === draft.id);
    expect(course?.editions.map((edition) => [edition.slug, edition.position, edition.lessonCount, edition.parts])).toEqual([["fall-2025", 1, 2, { lectures: 2, labs: 0 }], ["2024", 2, 1, { lectures: 0, labs: 1 }]]);
    expect(release.lessons.filter((lesson) => lesson.courseId === draft.id).map((lesson) => [lesson.id, lesson.editionId, lesson.part, lesson.order])).toEqual([
      [draft.lessons[0], draft.edition, "lectures", 1], [draft.lessons[1], draft.edition, "lectures", 2], [lab.id, older, "labs", 1],
    ]);
  });

  it("deletes an edition: dry run by default, never the last one, with-lessons keeps progress and redirects the published pages", async () => {
    const last = await call<DeleteReportData>(h, "DELETE", `/editions/${seed.editions.beta}?confirm=true&expectedRevision=1`);
    expect([last.status, last.body.error?.code]).toEqual([409, "has_dependents"]);
    const older = (await create(seed.courses.alpha, { slug: "fall-2024", label: "Fall 2024", term: "fall", year: 2024 })).data.edition.id;
    const lesson = await seedLesson(h.pool, seed.courses.alpha, { editionId: older });
    await swapMedia(h.pool, "lesson", coverInput("lesson", lesson.id, "cover_16x9"));
    await seedProgress(h, lesson.id, seed.courses.alpha);
    const report = await call<DeleteReportData>(h, "DELETE", `/editions/${older}`);
    expect(report.data).toMatchObject({ dryRun: true, report: { mode: "empty", lessons: [{ id: lesson.id, slug: "lesson-4", visible: true }], lessonProgressRows: 1, r2Candidates: [coverInput("lesson", lesson.id, "cover_16x9").pathname], r2Objects: [], redirects: [{ from: "/c/alpha/lesson-4", to: "/c/alpha" }] } });
    expect(report.data.report.blockedBy.map((blocker) => blocker.rule)).toEqual(["has_dependents"]);
    const refused = await call(h, "DELETE", `/editions/${older}?confirm=true&expectedRevision=1`);
    expect([refused.status, refused.body.error?.code]).toEqual([409, "has_dependents"]);
    const deleted = await call(h, "DELETE", `/editions/${older}?confirm=true&expectedRevision=1&mode=with-lessons`);
    expect(deleted.status).toBe(200);
    expect(await order(seed.courses.alpha)).toEqual(["fall-2025"]);
    expect((await h.pool.query("SELECT 1 FROM lessons WHERE id = $1", [lesson.id])).rows).toEqual([]);
    expect((await h.pool.query("SELECT 1 FROM lesson_progress WHERE lesson_id = $1", [lesson.id])).rows).toHaveLength(1);
    expect((await call(h, "GET", "/redirects")).data).toMatchObject({ redirects: [{ from: "/c/alpha/lesson-4", to: "/c/alpha" }] });
    expect(h.store.deleted).toEqual([]);
    expect(await auditRows(h, { action: "edition.delete" })).toHaveLength(1);
  });

  it("drafts an import into a new or existing edition of an existing course, suggesting Labs from the titles", async () => {
    const items = [{ id: newVideoId(), title: "Lab 1: Tensors", duration: 1800, playlistIndex: 1 }, { id: newVideoId(), title: "Lecture 2 - Backprop", duration: 1900, playlistIndex: 2 }];
    const stored = await call<{ import: { id: string; report: { accepted: { suggestedPart: string }[] } } }>(h, "POST", "/imports", { key: key(), body: { playlistUrl: "https://www.youtube.com/playlist?list=PLspring000001", items } });
    expect(stored.data.import.report.accepted.map((item) => item.suggestedPart)).toEqual(["labs", "lectures"]);
    const mixed = await call(h, "POST", `/imports/${stored.data.import.id}/draft`, { key: key(), body: { courseId: seed.courses.alpha, edition: { slug: "spring-2026", label: "Spring 2026", term: "spring", year: 2026 }, slug: "nope" } });
    expect([mixed.status, mixed.body.error?.code]).toEqual([400, "invalid"]);
    const drafted = await call<{ import: { courseId: string; editionId: string }; edition: { slug: string; position: number; sourcePlaylistIds: string[] }; lessons: { part: string; position: number }[] }>(h, "POST", `/imports/${stored.data.import.id}/draft`, {
      key: key(), body: { courseId: seed.courses.alpha, edition: { slug: "spring-2026", label: "Spring 2026", term: "spring", year: 2026 } },
    });
    expect(drafted.status).toBe(201);
    expect(drafted.data.edition).toMatchObject({ slug: "spring-2026", position: 1, sourcePlaylistIds: ["PLspring000001"] });
    expect(drafted.data.lessons.map((lesson) => [lesson.part, lesson.position])).toEqual([["labs", 1], ["lectures", 2]]);
    expect((await h.pool.query<{ status: string }>("SELECT status FROM courses WHERE id = $1", [seed.courses.alpha])).rows[0]?.status).toBe("published");
    // A second playlist into the same edition, all as Labs.
    // Same title again: the slug gets a suffix instead of a 409, because slugs are unique per course.
    const labs = await call<{ import: { id: string } }>(h, "POST", "/imports", { key: key(), body: { playlistUrl: "https://www.youtube.com/playlist?list=PLspring000002", items: [{ id: newVideoId(), title: "Lab 1: Tensors", duration: 1700, playlistIndex: 1 }] } });
    const more = await call<{ edition: { id: string; sourcePlaylistIds: string[] }; lessons: { part: string; position: number; slug: string }[] }>(h, "POST", `/imports/${labs.data.import.id}/draft`, {
      key: key(), body: { courseId: seed.courses.alpha, edition: { slug: "spring-2026", label: "Spring 2026", term: "spring", year: 2026 }, part: "labs" },
    });
    expect(more.data.edition.id).toBe(drafted.data.import.editionId);
    expect(more.data.lessons.map((lesson) => [lesson.part, lesson.position, lesson.slug])).toEqual([["labs", 3, "lab-01-tensors-2"]]);
    expect((await h.pool.query<{ source_playlist_ids: string[] }>("SELECT source_playlist_ids FROM course_editions WHERE id = $1", [more.data.edition.id])).rows[0]?.source_playlist_ids).toEqual(["PLspring000001", "PLspring000002"]);
  });

  it("activates an old version 1 release and back (rollback); the reader serves it as one edition per course", async () => {
    const active = (await call<ReleaseData>(h, "GET", "/releases/1")).data.release.payload;
    const v1 = { ...asReleaseV1(active), number: 2 };
    const { createHash } = await import("node:crypto");
    await h.pool.query(`INSERT INTO catalog_releases (number, schema_version, payload, payload_sha256, counts, note, created_by) VALUES (2, 1, $1::jsonb, $2, '{}'::jsonb, 'v1', 'test')`,
      [JSON.stringify(v1), createHash("sha256").update(JSON.stringify(v1)).digest("hex")]);
    const activated = await call(h, "POST", "/releases/2/activate", { key: key(), body: { note: "Roll back to v1" } });
    expect(activated.status).toBe(200);
    const served = await readActiveRelease(h.pool);
    expect(served.release.schemaVersion).toBe(2);
    expect(served.release.courses.map((course) => course.editions.map((edition) => [edition.id, edition.lessonCount]))).toEqual([[[`${seed.courses.alpha}-edition`, 3]], [[`${seed.courses.beta}-edition`, 2]]]);
    expect((await call<DoctorData>(h, "GET", "/doctor")).data.findings.map((finding) => finding.code)).toContain("release.drift");
    const back = await call(h, "POST", "/releases/1/activate", { key: key(), body: { note: "Forward again" } });
    expect(back.status).toBe(200);
    expect((await readActiveRelease(h.pool)).release.courses[0]?.editions[0]?.id).toBe(seed.editions.alpha);
  });

  it("doctor: orphan editions, gaps and lesson titles that name their semester", async () => {
    await create(seed.courses.alpha, { slug: "fall-2024", label: "Fall 2024", term: "fall", year: 2024 });
    await approvedText(h.pool, "lesson", seed.lessons.alpha[0] ?? "", "displayTitle", "[FA24] Intro to Android L1 - Layouts");
    await h.pool.query("UPDATE lessons SET position = 7 WHERE id = $1", [seed.lessons.beta[1]]);
    const doctor = (await call<DoctorData>(h, "GET", "/doctor")).data;
    const finding = (code: string) => doctor.findings.find((entry) => entry.code === code);
    expect(finding("editions.orphan")).toMatchObject({ severity: "warning", sample: [`${seed.courses.alpha}/fall-2024`] });
    expect(finding("lessons.gaps")).toMatchObject({ severity: "error", sample: [`${seed.editions.beta}: 2 lesson(s)`] });
    expect(finding("lesson.title.edition_prefix")).toMatchObject({ severity: "info", sample: [{ id: seed.lessons.alpha[0], title: "[FA24] Intro to Android L1 - Layouts" }] });
    expect(doctor.ok).toBe(false);
    expect(await defaultEdition(h.pool, seed.courses.alpha)).toBe(seed.editions.alpha);
  });
});
