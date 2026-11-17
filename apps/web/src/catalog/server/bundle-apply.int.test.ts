import pg from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { validateCourseBundle } from "../domain/bundle.ts";
import { applyCourseBundle, prepareCourseBundle } from "./bundle-apply.ts";
import { activeCoverKinds } from "./cover-kinds.ts";
import { REQUIRED_COVERS } from "../domain/rules/status.ts";
import { createFakeOEmbedResolver } from "../../playback/testing/fake-oembed.ts";
import { testDatabaseUrl } from "../../../test/fixtures/admin-catalog.ts";
import { resetCatalogTables } from "../../../test/fixtures/catalog-reset.ts";
import { runMigrations } from "../../../scripts/lib/migrations.ts";

function video(index: number): string {
  const alphabet = "abcdefghijklmnopqrstuvwxyz0123456789";
  return `abcdefghi${alphabet[Math.floor(index / 36)] ?? "a"}${alphabet[index % 36] ?? "a"}`;
}

function bundleOf(count: number) {
  const lessons = Array.from({ length: count }, (_, index) => ({
    id: `lesson-${String(index + 1)}`, editionId: "edition-1", slug: `lecture-${String(index + 1)}`, title: `Lecture ${String(index + 1)}`,
    position: index + 1, youtubeId: video(index), durationSeconds: 60,
  }));
  const parsed = validateCourseBundle({
    version: 1,
    author: { id: "author-a", slug: "ann", name: "Ann", monogram: "A", kind: "person" },
    course: { id: "course-live", slug: "contracts", title: "Contracts", authorId: "author-a", coverFrom: "own", sharedWith: [] },
    editions: [{ id: "edition-1", slug: "original", label: "Original", position: 1, year: 2020 }],
    lessons,
  });
  if (!parsed.ok) throw parsed.error;
  return parsed.value;
}

async function counts(pool: pg.Pool) {
  const tables = ["courses", "course_editions", "lessons", "lesson_videos", "catalog_texts", "home_rows", "home_row_items", "catalog_audit"];
  const values = await Promise.all(tables.map(async (table) => Number((await pool.query<{ n: number }>(`SELECT count(*)::int AS n FROM ${table}`)).rows[0]?.n)));
  const home = Number((await pool.query<{ revision: number }>("SELECT revision FROM catalog_home")).rows[0]?.revision);
  return { rows: values, home };
}

describe("bundle apply", () => {
  let pool: pg.Pool;
  beforeAll(async () => {
    const connectionString = testDatabaseUrl();
    await runMigrations(connectionString, false);
    await resetCatalogTables(connectionString);
    pool = new pg.Pool({ connectionString });
  });
  afterAll(async () => { await pool.end(); });

  it("rolls back lesson 149 of 150 and leaves the catalog untouched", async () => {
    const before = await counts(pool);
    const bundle = bundleOf(150);
    const prepared = await prepareCourseBundle(bundle, {
      now: () => new Date("2020-01-01T00:00:00.000Z"),
      resolver: createFakeOEmbedResolver({
        now: () => new Date("2020-01-01T00:00:00.000Z"),
        transport: (identity) => Promise.resolve({ status: "resolved" as const, verifiedAt: "2020-01-01T00:00:00.000Z", title: identity.externalId }),
      }),
    });
    await expect(applyCourseBundle(prepared, {
      pool,
      actor: "test",
      requestId: "bundle-rollback",
      replayKey: "rollback",
      beforeLesson: (index) => { if (index === 148) throw new Error("stop at lesson 149"); },
    })).rejects.toThrow("stop at lesson 149");
    expect(await counts(pool)).toEqual(before);
  });

  it("reapplies the same hash without a second lesson row", async () => {
    const bundle = bundleOf(1);
    const prepared = await prepareCourseBundle(bundle, {
      now: () => new Date("2020-01-01T00:00:00.000Z"),
      resolver: createFakeOEmbedResolver({
        now: () => new Date("2020-01-01T00:00:00.000Z"),
        transport: () => Promise.resolve({ status: "resolved" as const, verifiedAt: "2020-01-01T00:00:00.000Z" }),
      }),
    });
    const deps = { pool, actor: "test", requestId: "bundle-once", replayKey: "once" };
    const first = await applyCourseBundle(prepared, deps);
    const second = await applyCourseBundle(prepared, { ...deps, requestId: "bundle-replay" });
    expect(first.data).toMatchObject({ applied: true });
    expect(second.noop).toBe(true);
    expect(Number((await pool.query<{ n: number }>("SELECT count(*)::int AS n FROM lessons")).rows[0]?.n)).toBe(1);
    const changed = validateCourseBundle({ ...bundle, course: { ...bundle.course, title: "Other" } });
    if (!changed.ok) throw changed.error;
    const conflict = await prepareCourseBundle(changed.value, {
      now: () => new Date("2020-01-01T00:00:00.000Z"),
      resolver: createFakeOEmbedResolver({ now: () => new Date("2020-01-01T00:00:00.000Z"), transport: () => Promise.resolve({ status: "resolved" as const, verifiedAt: "2020-01-01T00:00:00.000Z" }) }),
    });
    await expect(applyCourseBundle(conflict, deps)).rejects.toThrow("different bundle");
  });

  it("applies two bundles that share an author without losing the slug race", async () => {
    // ship --batch runs two applies at once. INSERT ... ON CONFLICT (id) still raises
    // authors_slug_unique when both speculative inserts meet on the slug index
    // (measured: 8/100 unaligned pairs, 3/12 pairs released on the same timestamp).
    const gate = `CREATE OR REPLACE FUNCTION ou_author_race_gate() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE n int; wake timestamptz;
      BEGIN
        IF current_setting('ou.author_race', true) IS DISTINCT FROM '1' THEN RETURN NEW; END IF;
        PERFORM set_config('ou.author_race', '0', true);
        PERFORM pg_advisory_lock(900100, pg_backend_pid());
        LOOP
          SELECT count(*) INTO n FROM pg_locks WHERE locktype = 'advisory' AND classid = 900100 AND granted;
          EXIT WHEN n >= 2;
          PERFORM pg_sleep(0.005);
        END LOOP;
        wake := current_setting('ou.author_race_at', true)::timestamptz;
        PERFORM pg_sleep(GREATEST(0, EXTRACT(EPOCH FROM (wake - clock_timestamp()))));
        RETURN NEW;
      END $$`;
    const racePool = new pg.Pool({ connectionString: testDatabaseUrl(), max: 2 });
    const courseIds = ["course-race-a", "course-race-b"];
    const lessonIds = ["lesson-race-a", "lesson-race-b"];
    const clear = async () => {
      await racePool.query("DELETE FROM catalog_audit WHERE entity_id = ANY($1::text[])", [courseIds]);
      await racePool.query("DELETE FROM catalog_texts WHERE entity_id = ANY($1::text[])", [[...courseIds, ...lessonIds]]);
      await racePool.query("DELETE FROM lesson_videos WHERE lesson_id = ANY($1::text[])", [lessonIds]);
      await racePool.query("DELETE FROM lessons WHERE id = ANY($1::text[])", [lessonIds]);
      await racePool.query("DELETE FROM course_editions WHERE course_id = ANY($1::text[])", [courseIds]);
      await racePool.query("DELETE FROM courses WHERE id = ANY($1::text[])", [courseIds]);
      await racePool.query("DELETE FROM authors WHERE id = 'author-race'");
    };
    const arm = async (wake: string) => {
      const clients = await Promise.all([racePool.connect(), racePool.connect()]);
      try {
        for (const client of clients) {
          await client.query("SELECT pg_advisory_unlock_all()");
          await client.query("SELECT set_config('ou.author_race', '1', false), set_config('ou.author_race_at', $1, false)", [wake]);
        }
      } finally {
        for (const client of clients) client.release();
      }
    };
    try {
      await racePool.query(gate);
      await racePool.query("DROP TRIGGER IF EXISTS ou_author_race_gate ON authors");
      await racePool.query("CREATE TRIGGER ou_author_race_gate BEFORE INSERT ON authors FOR EACH ROW EXECUTE FUNCTION ou_author_race_gate()");
      const prepared = await Promise.all(courseIds.map(async (id, index) => {
        const parsed = validateCourseBundle({
          version: 1,
          author: { id: "author-race", slug: "ada-race", name: "Ada", monogram: "A", kind: "person" },
          course: { id, slug: id, title: "Contracts", authorId: "author-race", coverFrom: "own", sharedWith: [] },
          editions: [{ id: `edition-${id}`, slug: "original", label: "Original", position: 1, year: 2020 }],
          lessons: [{ id: lessonIds[index], editionId: `edition-${id}`, slug: "lecture-1", title: "Lecture 1", position: 1, youtubeId: video(20 + index), durationSeconds: 60 }],
        });
        if (!parsed.ok) throw parsed.error;
        return prepareCourseBundle(parsed.value, {
          now: () => new Date("2020-01-01T00:00:00.000Z"),
          resolver: createFakeOEmbedResolver({
            now: () => new Date("2020-01-01T00:00:00.000Z"),
            transport: () => Promise.resolve({ status: "resolved" as const, verifiedAt: "2020-01-01T00:00:00.000Z" }),
          }),
        });
      }));
      for (let round = 0; round < 24; round += 1) {
        await clear();
        await arm(new Date(Date.now() + 250).toISOString());
        const applied = await Promise.all(prepared.map((bundle, index) => applyCourseBundle(bundle, {
          pool: racePool, actor: "test", requestId: `author-race-${String(round)}-${String(index)}`, replayKey: `author-race-${String(round)}-${String(index)}`,
        })));
        expect(applied.map((result) => result.data)).toEqual([
          { courseId: "course-race-a", hash: prepared[0]?.hash, applied: true },
          { courseId: "course-race-b", hash: prepared[1]?.hash, applied: true },
        ]);
      }
      const authors = await racePool.query<{ id: string; slug: string }>("SELECT id, slug FROM authors WHERE slug = 'ada-race'");
      expect(authors.rows).toEqual([{ id: "author-race", slug: "ada-race" }]);
    } finally {
      await racePool.query("DROP TRIGGER IF EXISTS ou_author_race_gate ON authors");
      await racePool.query("DROP FUNCTION IF EXISTS ou_author_race_gate()");
      await clear();
      const clients = await Promise.all([racePool.connect(), racePool.connect()]);
      for (const client of clients) {
        await client.query("SELECT pg_advisory_unlock_all()");
        client.release();
      }
      await racePool.end();
    }
  });

  it("lets a provisional course without covers inherit its subarea poster and heroes (ADR-30)", async () => {
    const subarea = "mechanical-engineering";
    const classified = (id: string, video: string, extra: Record<string, unknown>) => {
      const parsed = validateCourseBundle({
        version: 1,
        author: { id: "author-cover", slug: "cover-author", name: "Cover Author", monogram: "CA", kind: "person" },
        course: { id, slug: id, title: "Thermodynamics", authorId: "author-cover", areaId: "engineering", subareaId: subarea, sharedWith: [], ...extra },
        editions: [{ id: `${id}-edition`, slug: "original", label: "Original", position: 1, year: 2024 }],
        lessons: [{ id: `${id}-lesson`, editionId: `${id}-edition`, slug: "lecture-1", title: "Lecture 1", position: 1, youtubeId: video, durationSeconds: 60 }],
      });
      if (!parsed.ok) throw parsed.error;
      return prepareCourseBundle(parsed.value, {
        now: () => new Date("2020-01-01T00:00:00.000Z"),
        resolver: createFakeOEmbedResolver({ now: () => new Date("2020-01-01T00:00:00.000Z"), transport: () => Promise.resolve({ status: "resolved" as const, verifiedAt: "2020-01-01T00:00:00.000Z" }) }),
      });
    };
    for (const [index, kind] of REQUIRED_COVERS.entries()) {
      await pool.query(`INSERT INTO catalog_media (id, owner_kind, owner_id, kind, url, pathname, width, height, sha256, alt, design_status, version)
        VALUES ($1, 'subarea', $2, $3, 'https://example.org/c.jpg', 'c.jpg', 100, 100, $4, 'Cover', 'approved', 1)`, [`subarea-cover-${kind}`, subarea, kind, String(index).repeat(64)]);
    }
    const deps = (requestId: string) => ({ pool, actor: "test", requestId, replayKey: requestId });
    await applyCourseBundle(await classified("course-provisional", "provisiona1", { coverFrom: `subarea:${subarea}` }), deps("cover-provisional"));
    await applyCourseBundle(await classified("course-own-covers", "owncovers01", { coverFrom: "own", sharedWith: [] }), deps("cover-own"));
    const flags = await pool.query<{ id: string; cover_from: string }>("SELECT id, cover_from FROM courses WHERE id = ANY($1::text[]) ORDER BY id", [["course-own-covers", "course-provisional"]]);
    expect(flags.rows).toEqual([{ id: "course-own-covers", cover_from: "own" }, { id: "course-provisional", cover_from: `subarea:${subarea}` }]);
    const kinds = await activeCoverKinds(pool);
    expect([...(kinds.get("course-provisional") ?? [])].sort()).toEqual([...REQUIRED_COVERS].sort());
    expect([...(kinds.get("course-own-covers") ?? [])]).toEqual([]);

    // A published course that lives on inherited covers cannot drop the flag through a bundle.
    await pool.query("INSERT INTO licenses (code, name, requires_attribution) VALUES ('cc-by-sa-4.0', 'CC BY-SA 4.0', true) ON CONFLICT DO NOTHING");
    await pool.query("INSERT INTO content_sources (id, kind, title, publisher, url) VALUES ('cover-source', 'institution-site', 'Test', 'Test University', 'https://example.org') ON CONFLICT DO NOTHING");
    await pool.query(`UPDATE courses SET status = 'published', license_code = 'cc-by-sa-4.0', source_id = 'cover-source', canonical_url = 'https://example.org/c', rights_status = 'cleared'
      WHERE id = 'course-provisional'`);
    await expect(applyCourseBundle(await classified("course-provisional", "provisiona1", { coverFrom: "own", sharedWith: [], title: "Thermodynamics II" }), deps("cover-drop")))
      .rejects.toMatchObject({ code: "preconditions_failed" });
    const kept = await pool.query<{ cover_from: string; title: string }>("SELECT cover_from, title FROM courses WHERE id = 'course-provisional'");
    expect(kept.rows).toEqual([{ cover_from: `subarea:${subarea}`, title: "Thermodynamics" }]);
  });

  it("refuses to attach a course to a university row that has no cover", async () => {
    await pool.query("INSERT INTO authors (id, slug, name, monogram, kind) VALUES ('iit-roorkee-institution', 'iit-roorkee', 'IIT Roorkee', 'IR', 'institution') ON CONFLICT (id) DO NOTHING");
    await pool.query("INSERT INTO home_rows (id, kind, institution_id, title, position, visible, cover) VALUES ('iit-roorkee', 'curated', 'iit-roorkee-institution', 'IIT Roorkee', 50, true, NULL) ON CONFLICT (id) DO UPDATE SET cover = NULL, visible = true, kind = 'curated'");
    const revision = (await pool.query<{ revision: number }>("SELECT revision FROM catalog_home")).rows[0]?.revision ?? 0;
    const base = bundleOf(1);
    const lesson = base.lessons[0];
    if (!lesson) throw new Error("lesson");
    const parsed = validateCourseBundle({
      ...base,
      author: { id: "author-iit", slug: "author-iit", name: "IIT Author", monogram: "IA", kind: "person" },
      course: { ...base.course, id: "course-iit-cover", slug: "iit-cover", authorId: "author-iit" },
      lessons: [{ ...lesson, id: "lesson-iit-cover", youtubeId: "covertest0a" }],
      home: { rowId: "iit-roorkee", expectedRevision: revision },
    });
    if (!parsed.ok) throw parsed.error;
    const prepared = await prepareCourseBundle(parsed.value, {
      now: () => new Date("2020-01-01T00:00:00.000Z"),
      resolver: createFakeOEmbedResolver({ now: () => new Date("2020-01-01T00:00:00.000Z"), transport: () => Promise.resolve({ status: "resolved" as const, verifiedAt: "2020-01-01T00:00:00.000Z" }) }),
    });
    await expect(applyCourseBundle(prepared, { pool, actor: "test", requestId: "bundle-no-cover", replayKey: "no-cover" })).rejects.toThrow("Curated row iit-roorkee needs a cover.");
    expect(Number((await pool.query<{ n: number }>("SELECT count(*)::int AS n FROM home_row_items WHERE row_id = 'iit-roorkee'")).rows[0]?.n)).toBe(0);
  });
});
