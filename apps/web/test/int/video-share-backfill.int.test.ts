import { cpSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { drizzle } from "drizzle-orm/node-postgres";
import { migrate } from "drizzle-orm/node-postgres/migrator";
import pg from "pg";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { migrationsFolder, runMigrations } from "../../scripts/lib/migrations.ts";
import { testDatabaseUrl } from "../fixtures/admin-catalog.ts";

describe("0029 (D-032): backfill declares a mutual share where videos already overlap", () => {
  let db: pg.Client;
  const reset = () => db.query("DROP SCHEMA public CASCADE; CREATE SCHEMA public; DROP SCHEMA IF EXISTS drizzle CASCADE");

  beforeEach(async () => {
    db = new pg.Client({ connectionString: testDatabaseUrl() });
    await db.connect();
    await reset();
    const folder = mkdtempSync(join(tmpdir(), "video-share-"));
    cpSync(migrationsFolder, folder, { recursive: true });
    const file = join(folder, "meta/_journal.json");
    const journal = JSON.parse(readFileSync(file, "utf8")) as { entries: { idx: number }[] };
    writeFileSync(file, JSON.stringify({ ...journal, entries: journal.entries.filter((entry) => entry.idx <= 27) }));
    await migrate(drizzle(db), { migrationsFolder: folder });
    await db.query("INSERT INTO authors (id, slug, name, monogram, kind) VALUES ('lecturer-1', 'lecturer-1', 'Lecturer', 'L', 'person')");
    for (const id of ["share-a", "share-b", "alone"]) await course(id);
    await video("share-a", "abcdefghijk");
    await video("share-b", "abcdefghijk");
    await video("share-a", "zzzzzzzzzz1");
    await video("alone", "yyyyyyyyyy1");
  });

  afterEach(async () => {
    await reset();
    await db.end();
    await runMigrations(testDatabaseUrl(), false);
  });

  async function course(id: string) {
    await db.query(`INSERT INTO courses (id, slug, author_id, title, cover_provisional)
      VALUES ($1, $1, 'lecturer-1', $1, false)`, [id]);
    await db.query(`INSERT INTO course_editions (id, course_id, slug, label, year, position)
      VALUES ($1, $2, 'original', 'Original', 2020, 1)`, [`${id}-e`, id]);
  }

  async function video(courseId: string, youtubeId: string) {
    const lessonId = `${courseId}-${youtubeId}`;
    await db.query(`INSERT INTO lessons (id, course_id, edition_id, slug, position, youtube_title, duration_seconds)
      VALUES ($1, $2, $3, $4, (SELECT coalesce(max(position), 0) + 1 FROM lessons WHERE edition_id = $3), $4, 60)`,
    [lessonId, courseId, `${courseId}-e`, youtubeId.slice(0, 12)]);
    await db.query(`INSERT INTO lesson_videos (lesson_id, course_id, provider, external_id, status, checked_at, checked_by)
      VALUES ($1, $2, 'youtube', $3, 'ok', now(), 'migration')`, [lessonId, courseId, youtubeId]);
  }

  it("D-032: backfill names both courses of an overlapping video and leaves the others empty", async () => {
    expect((await runMigrations(testDatabaseUrl(), false)).pending).toBe(0);
    expect((await runMigrations(testDatabaseUrl(), false)).pending).toBe(0);
    const rows = (await db.query<{ id: string; shared_with: string[] }>("SELECT id, shared_with FROM courses ORDER BY id")).rows;
    expect(rows).toEqual([
      { id: "alone", shared_with: [] },
      { id: "share-a", shared_with: ["share-b"] },
      { id: "share-b", shared_with: ["share-a"] },
    ]);
    const audit = (await db.query<{ entity_id: string; shared: string[] }>(
      "SELECT entity_id, after->'sharedWith' AS shared FROM catalog_audit WHERE action = 'video.share.backfill' ORDER BY entity_id")).rows;
    expect(audit).toEqual([
      { entity_id: "share-a", shared: ["share-b"] },
      { entity_id: "share-b", shared: ["share-a"] },
    ]);
    await expect(db.query("UPDATE courses SET shared_with = '{}' WHERE id = 'share-a'")).rejects.toMatchObject({ code: "23514" });
    await db.query("BEGIN");
    await db.query("UPDATE courses SET shared_with = '{}' WHERE id = 'share-a'");
    await db.query("UPDATE courses SET shared_with = '{}' WHERE id = 'share-b'");
    await db.query("COMMIT");
    const cleared = (await db.query<{ id: string; shared_with: string[] }>("SELECT id, shared_with FROM courses WHERE id = 'share-a'")).rows;
    expect(cleared).toEqual([{ id: "share-a", shared_with: [] }]);
  });
});
