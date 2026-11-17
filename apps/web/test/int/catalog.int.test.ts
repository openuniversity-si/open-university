import { createHash } from "node:crypto";
import pg from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { releaseSchema } from "../../src/catalog/domain/release.ts";
import { runMigrations } from "../../scripts/lib/migrations.ts";
import { validateDatabaseUrl } from "../../scripts/lib/database-target.ts";
import { resetCatalogTables } from "../fixtures/catalog-reset.ts";
import { releaseFixture } from "../fixtures/release.ts";

// Every case runs in a rolled-back transaction on the migrated PG18 test database.
describe("catalog schema (migration 0005) on PG18", () => {
  let client: pg.Client;

  beforeAll(async () => {
    const connectionString = process.env.TEST_DATABASE_URL;
    if (!connectionString) throw new Error("TEST_DATABASE_URL is required; no database mocks.");
    validateDatabaseUrl(connectionString, "container");
    await runMigrations(connectionString, false);
    await resetCatalogTables(connectionString);
    client = new pg.Client({ connectionString });
    await client.connect();
  });

  afterAll(async () => { await client.end(); });

  async function inRollback(run: () => Promise<void>) {
    await client.query("BEGIN");
    try { await run(); } finally { await client.query("ROLLBACK"); }
  }
  async function rejects(sql: string, code: string, constraint?: string) {
    await client.query("SAVEPOINT probe");
    try {
      await expect(client.query(sql)).rejects.toMatchObject(constraint ? { code, constraint } : { code });
    } finally { await client.query("ROLLBACK TO SAVEPOINT probe"); }
  }
  async function seedDraftCourses() {
    await client.query("INSERT INTO licenses (code, name, requires_attribution) VALUES ('cc-by-nc-sa-3.0', 'CC BY-NC-SA 3.0', true)");
    await client.query("INSERT INTO content_sources (id, kind, title, publisher, url) VALUES ('site-test', 'institution-site', 'Test', 'Test University', 'https://example.org')");
    await client.query("INSERT INTO authors (id, slug, name, monogram, kind) VALUES ('author-t', 'test-lecturer', 'Test Lecturer', 'TL', 'person')");
    await client.query(`INSERT INTO courses (id, slug, author_id, title, source_id, license_code, canonical_url, rights_status, area_id, cover_from, shared_with)
      VALUES ('course-a', 'course-a', 'author-t', 'A', 'site-test', 'cc-by-nc-sa-3.0', 'https://example.org/a', 'cleared', 'computer-science', 'own', '{}'),
             ('course-b', 'course-b', 'author-t', 'B', 'site-test', 'cc-by-nc-sa-3.0', 'https://example.org/b', 'cleared', 'computer-science', 'own', '{}'),
             ('course-c', 'course-c', 'author-t', 'C', NULL, NULL, NULL, 'unverified', 'computer-science', 'own', '{}')`);
  }

  it("continues the static id series from the sequences", async () => {
    await inRollback(async () => {
      const { rows } = await client.query<{ id: string }>("INSERT INTO authors (slug, name, monogram, kind) VALUES ('seq-probe', 'Probe', 'P', 'person') RETURNING id");
      expect(rows[0]?.id).toMatch(/^author-\d+$/);
      expect(Number(rows[0]?.id.slice("author-".length))).toBeGreaterThanOrEqual(3);
    });
  });

  it("refuses to publish a course without rights", async () => {
    await inRollback(async () => {
      await seedDraftCourses();
      await rejects("UPDATE courses SET status='published' WHERE id='course-c'", "23514", "courses_published_rights");
      await rejects("UPDATE courses SET status='published', rights_status='unverified' WHERE id='course-a'", "23514", "courses_published_rights");
      await client.query("UPDATE courses SET status='published' WHERE id='course-a'");
    });
  });

  it("allows only one published featured course", async () => {
    await inRollback(async () => {
      await seedDraftCourses();
      await client.query("UPDATE courses SET status='published', featured=true WHERE id='course-a'");
      await client.query("UPDATE courses SET featured=true WHERE id='course-b'");
      await rejects("UPDATE courses SET status='published' WHERE id='course-b'", "23505", "courses_one_featured");
    });
  });

  it("pins approval to the approved text hash and accepts the automatic reviewer", async () => {
    await inRollback(async () => {
      const insert = (hash: string, by = "catalog-bot") => client.query(`INSERT INTO catalog_texts (entity_kind, entity_id, field, text, source, source_ref, confidence, status, approved_by, approved_at, approved_sha256)
        VALUES ('course', 'course-a', 'subtitle', 'A subtitle', 'llm', 'draft-copy', 'medium', 'approved', $1, now(), $2)`, [by, hash]);
      const hash = createHash("sha256").update("A subtitle").digest("hex");
      await client.query("SAVEPOINT probe");
      await expect(insert("0".repeat(64))).rejects.toMatchObject({ code: "23514", constraint: "catalog_texts_approval" });
      await client.query("ROLLBACK TO SAVEPOINT probe");
      await expect(insert(hash, "  ")).rejects.toMatchObject({ code: "23514", constraint: "catalog_texts_approved_by" });
      await client.query("ROLLBACK TO SAVEPOINT probe");
      await insert(hash);
      // Editing the text without re-approval breaks the pinned hash.
      await rejects("UPDATE catalog_texts SET text='Another subtitle' WHERE entity_id='course-a'", "23514", "catalog_texts_approval");
      await rejects("INSERT INTO catalog_texts (entity_kind, entity_id, field, text, source, source_ref, confidence) VALUES ('lesson', 'lesson-1', 'subtitle', 'x', 'manual', 'm', 'high')", "23514", "catalog_texts_field");
    });
  });

  it("rejects invalid slugs and duplicate positions", async () => {
    await inRollback(async () => {
      await seedDraftCourses();
      await rejects("INSERT INTO authors (slug, name, monogram, kind) VALUES ('Bad Slug', 'X', 'X', 'person')", "23514", "authors_slug");
      await rejects("UPDATE courses SET slug='course_a' WHERE id='course-a'", "23514", "courses_slug");
      await client.query("INSERT INTO course_editions (id, course_id, slug, label, term, year, position) VALUES ('edition-a1', 'course-a', 'fall-2025', 'Fall 2025', 'fall', 2025, 1), ('edition-a2', 'course-a', 'fall-2024', 'Fall 2024', 'fall', 2024, 2), ('edition-b1', 'course-b', '2025', '2025', NULL, 2025, 1)");
      await rejects("INSERT INTO course_editions (course_id, slug, label, year, position) VALUES ('course-a', 'fall-2025', 'Again', 2023, 3)", "23505", "course_editions_course_slug");
      await rejects("INSERT INTO course_editions (course_id, slug, label, year, position) VALUES ('course-a', 'x', 'X', 2023, 2)", "23505", "course_editions_course_position");
      await rejects("INSERT INTO course_editions (course_id, slug, label, year, position) VALUES ('course-a', 'y', 'Y', 2023, 0)", "23514", "course_editions_position");
      await rejects("INSERT INTO course_editions (course_id, slug, label, term, year, position) VALUES ('course-a', 'z', 'Z', 'autumn', 2023, 3)", "23514", "course_editions_term");
      await rejects("INSERT INTO course_editions (course_id, slug, label, year, position) VALUES ('course-a', 'w', 'W', 1989, 3)", "23514", "course_editions_year");
      await rejects("INSERT INTO course_editions (course_id, slug, label, year, position) VALUES ('course-a', 'again-2025', 'Again 2025', 2025, 3)", "23505", "course_editions_course_year_variant");
      await client.query("INSERT INTO course_editions (id, course_id, slug, label, year, position, variant_kind, variant_label) VALUES ('edition-ss', 'course-a', 'ss-2026', 'SS 2026', 2026, 4, 'term', 'SS'), ('edition-ws', 'course-a', 'ws-2026', 'WS 2026', 2026, 5, 'term', 'WS')");
      await rejects("INSERT INTO course_editions (course_id, slug, label, year, position, variant_kind, variant_label) VALUES ('course-a', 'ss-again', 'SS again', 2026, 6, 'term', 'SS')", "23505", "course_editions_course_year_variant");
      await rejects("INSERT INTO course_editions (course_id, slug, label, year, position, variant_kind, variant_label) VALUES ('course-a', 'half', 'Half', 2027, 6, 'language', 'English')", "23514", "course_editions_language_variant");
      await client.query("INSERT INTO lessons (id, course_id, edition_id, slug, position, youtube_title, duration_seconds) VALUES ('lesson-x1', 'course-a', 'edition-a1', 'one', 1, 'One', 60)");
      await rejects("INSERT INTO lessons (id, course_id, edition_id, slug, position, youtube_title, duration_seconds) VALUES ('lesson-x2', 'course-a', 'edition-a1', 'two', 1, 'Two', 60)", "23505", "lessons_edition_position");
      // Order is per edition: position 1 is free in the other edition; the slug stays unique per course.
      await client.query("INSERT INTO lessons (id, course_id, edition_id, slug, position, youtube_title, duration_seconds) VALUES ('lesson-x3', 'course-a', 'edition-a2', 'three', 1, 'Three', 60)");
      await rejects("INSERT INTO lessons (id, course_id, edition_id, slug, position, youtube_title, duration_seconds) VALUES ('lesson-x2', 'course-a', 'edition-a2', 'one', 2, 'Two', 60)", "23505", "lessons_course_slug");
      await rejects("INSERT INTO lessons (id, course_id, edition_id, slug, position, youtube_title, duration_seconds) VALUES ('lesson-x2', 'course-a', 'edition-b1', 'two', 1, 'Two', 60)", "23503", "lessons_edition_course_fk");
      await rejects("INSERT INTO lessons (id, course_id, slug, position, youtube_title, duration_seconds) VALUES ('lesson-x2', 'course-a', 'two', 2, 'Two', 60)", "23502");
      await rejects("INSERT INTO lessons (id, course_id, edition_id, part, slug, position, youtube_title, duration_seconds) VALUES ('lesson-x2', 'course-a', 'edition-a1', 'recitations', 'two', 2, 'Two', 60)", "23514", "lessons_part");
      await rejects("DELETE FROM course_editions WHERE id = 'edition-a1'", "23001", "lessons_edition_course_fk");
      await client.query("INSERT INTO home_rows (id, kind, author_id, position) VALUES ('test-lecturer', 'author', 'author-t', 1)");
      await rejects("INSERT INTO home_rows (id, kind, institution_id, title, position) VALUES ('curated-test', 'curated', 'author-t', 'Curated', 1)", "23505", "home_rows_position_unique");
      await client.query("INSERT INTO home_row_items (row_id, course_id, position) VALUES ('test-lecturer', 'course-a', 1)");
      await rejects("INSERT INTO home_row_items (row_id, course_id, position) VALUES ('test-lecturer', 'course-b', 1)", "23505", "home_row_items_position_unique");
      await rejects("INSERT INTO lesson_videos (lesson_id, provider, external_id, status, checked_at, checked_by) VALUES ('lesson-x1', 'youtube', 'short', 'ok', now(), 'oembed')", "23514", "lesson_videos_youtube_id");
      await client.query("INSERT INTO lessons (id, course_id, edition_id, slug, position, youtube_title, duration_seconds) VALUES ('lesson-b1', 'course-b', 'edition-b1', 'one', 1, 'Shared', 60)");
      await client.query("INSERT INTO lesson_videos (lesson_id, provider, external_id, status, checked_at, checked_by) VALUES ('lesson-x1', 'youtube', 'abcdefghijk', 'ok', now(), 'oembed')");
      await client.query("INSERT INTO lesson_videos (lesson_id, provider, external_id, status, checked_at, checked_by) VALUES ('lesson-b1', 'youtube', 'abcdefghijk', 'ok', now(), 'oembed')");
      await rejects("INSERT INTO lesson_videos (lesson_id, provider, external_id, status, checked_at, checked_by) VALUES ('lesson-x3', 'youtube', 'abcdefghijk', 'ok', now(), 'oembed')", "23505", "lesson_videos_youtube_course");
      await client.query("INSERT INTO lesson_videos (lesson_id, provider, external_id, status, checked_at, checked_by) VALUES ('lesson-x1', 'mux', 'muxasset001', 'ok', now(), 'oembed')");
      await rejects("INSERT INTO lesson_videos (lesson_id, provider, external_id, status, checked_at, checked_by) VALUES ('lesson-b1', 'mux', 'muxasset001', 'ok', now(), 'oembed')", "23505", "lesson_videos_mux_external");
    });
  });

  it("stores a release payload that round-trips through releaseSchema, with one active release", async () => {
    await inRollback(async () => {
      const payload = JSON.stringify(releaseFixture());
      const hash = createHash("sha256").update(payload).digest("hex");
      const insert = (number: number) => client.query(`INSERT INTO catalog_releases (number, schema_version, payload, payload_sha256, counts, note, created_by, is_active, activated_at)
        VALUES ($1, 1, $2, $3, '{"courses":2}', 'test', 'test', true, now())`, [number, payload, hash]);
      await insert(1);
      const { rows } = await client.query<{ payload: unknown }>("SELECT payload FROM catalog_releases WHERE number=1");
      expect(releaseSchema.parse(rows[0]?.payload).courses).toHaveLength(2);
      await client.query("SAVEPOINT probe");
      await expect(insert(2)).rejects.toMatchObject({ code: "23505", constraint: "catalog_releases_one_active" });
      await client.query("ROLLBACK TO SAVEPOINT probe");
    });
  });

  it("D-029: the legacy asset tables and cover columns are gone", async () => {
    const { rows } = await client.query<{ rel: string | null }>(`SELECT to_regclass(name) AS rel FROM unnest(ARRAY['public.course_assets','public.lesson_assets','public.subarea_assets']) AS name`);
    expect(rows.map((row) => row.rel)).toEqual([null, null, null]);
    const columns = await client.query("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name IN ('authors', 'home_rows') AND column_name IN ('media_sha256', 'og_media_sha256')");
    expect(columns.rows).toEqual([]);
  });
});
