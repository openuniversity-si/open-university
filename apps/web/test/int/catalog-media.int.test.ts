import { cpSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { drizzle } from "drizzle-orm/node-postgres";
import { migrate } from "drizzle-orm/node-postgres/migrator";
import pg from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { migrationsFolder, runMigrations } from "../../scripts/lib/migrations.ts";
import { MEDIA_PUBLIC_HOST, type AssetInput } from "../../src/media/domain/types.ts";
import { readActiveMedia, swapMedia } from "../../src/media/server/repository.ts";
import { testDatabaseUrl } from "../fixtures/admin-catalog.ts";

// Verifies: D-015
/** Migrations up to and including journal idx `last` (0023 is 23; 0024 is the cutover under test). */
function migrationsUpTo(last: number): string {
  const folder = mkdtempSync(join(tmpdir(), "tower-migrations-"));
  cpSync(migrationsFolder, folder, { recursive: true });
  const journalPath = join(folder, "meta", "_journal.json");
  const journal = JSON.parse(readFileSync(journalPath, "utf8")) as { entries: { idx: number }[] };
  writeFileSync(journalPath, JSON.stringify({ ...journal, entries: journal.entries.filter((entry) => entry.idx <= last) }));
  return folder;
}

const sha = (digit: string) => digit.repeat(64);
const pathHash = (digit: string) => digit.repeat(40);
const cover = (owner: string, kind: string, digit: string, alt: string) => JSON.stringify({
  url: `https://media.openuniversity.si/covers/${owner}/${kind}/${pathHash(digit)}.jpg`,
  width: 540, height: 960, sha256: sha(digit), alt,
});

describe("migration 0024 catalog_media", () => {
  let client: pg.Client;
  let pool: pg.Pool;
  beforeAll(async () => {
    client = new pg.Client({ connectionString: testDatabaseUrl() });
    await client.connect();
    pool = new pg.Pool({ connectionString: testDatabaseUrl(), max: 2 });
  });
  afterAll(async () => {
    await client.query("DROP SCHEMA public CASCADE; CREATE SCHEMA public; DROP SCHEMA IF EXISTS drizzle CASCADE");
    await runMigrations(testDatabaseUrl(), false);
    await client.end();
    await pool.end();
  });

  it("backfills every legacy place, refuses a legacy write, and attaches an area cover", async () => {
    await client.query("DROP SCHEMA public CASCADE; CREATE SCHEMA public; DROP SCHEMA IF EXISTS drizzle CASCADE");
    await migrate(drizzle(client), { migrationsFolder: migrationsUpTo(23) });

    await client.query("INSERT INTO authors (id, slug, name, monogram, cover) VALUES ('author-s05a', 'ada-s05a', 'Ada', 'A', $1::jsonb)", [cover("author-s05a", "author_cover_9x16", "a", "Ada")]);
    await client.query("INSERT INTO subject_subareas (id, area_id, title, position) SELECT 's05a-algebra', 'computer-science', 'S05a algebra', COALESCE(MAX(position), 0) + 1 FROM subject_subareas WHERE area_id = 'computer-science'");
    await client.query("INSERT INTO courses (id, slug, author_id, title) VALUES ('course-s05a', 'alpha-s05a', 'author-s05a', 'Alpha')");
    await client.query("INSERT INTO course_editions (id, course_id, slug, label, year, position) VALUES ('edition-s05a', 'course-s05a', '2024', '2024', 2024, 1)");
    await client.query("INSERT INTO lessons (id, course_id, edition_id, slug, position, youtube_title, duration_seconds) VALUES ('lesson-s05a', 'course-s05a', 'edition-s05a', 'one', 1, 'One', 60)");
    await client.query(
      "INSERT INTO home_rows (id, kind, title, position, cover) SELECT 'yale-s05a', 'curated', 'Yale S05a', COALESCE(MAX(position), 0) + 1, $1::jsonb FROM home_rows",
      [JSON.stringify({ ...JSON.parse(cover("yale-s05a", "university_cover_9x16", "b", "Yale")), og: { url: `https://media.openuniversity.si/covers/yale-s05a/og/${pathHash("c")}.jpg`, width: 1200, height: 630, sha256: sha("c") } })],
    );
    const asset = async (table: string, column: string, id: string, ownerId: string, kind: string, digit: string) => {
      await client.query(
        `INSERT INTO ${table} (id, ${column}, kind, variant, url, pathname, width, height, sha256, alt, design_status, version)
         VALUES ($1, $2, $3, 'default', $4, $5, 540, 960, $6, $3, 'approved', 1)`,
        [id, ownerId, kind, `https://media.openuniversity.si/covers/${ownerId}/${kind}/${pathHash(digit)}.jpg`, `covers/${ownerId}/${kind}/${pathHash(digit)}.jpg`, sha(digit)],
      );
    };
    await asset("course_assets", "course_id", "asset-course", "course-s05a", "poster_9x16", "d");
    await asset("lesson_assets", "lesson_id", "asset-lesson", "lesson-s05a", "cover_16x9", "e");
    await asset("subarea_assets", "subarea_id", "asset-subarea", "s05a-algebra", "poster_9x16", "f");

    await migrate(drizzle(client), { migrationsFolder: migrationsUpTo(24) });
    await migrate(drizzle(client), { migrationsFolder: migrationsUpTo(24) });

    const { rows: [counts] } = await client.query<{ media: number; legacy: number }>(`SELECT
      (SELECT count(*)::int FROM catalog_media) AS media,
      (SELECT count(*)::int FROM course_assets)
        + (SELECT count(*)::int FROM lesson_assets)
        + (SELECT count(*)::int FROM subarea_assets)
        + (SELECT count(*)::int FROM authors WHERE cover IS NOT NULL OR media_sha256 IS NOT NULL)
        + (SELECT count(*)::int FROM home_rows WHERE cover IS NOT NULL OR media_sha256 IS NOT NULL)
        + (SELECT count(*)::int FROM home_rows WHERE cover->'og' IS NOT NULL OR og_media_sha256 IS NOT NULL) AS legacy`);
    expect(counts).toEqual({ media: 6, legacy: 6 });
    const { rows } = await client.query<{ owner_kind: string; owner_id: string; kind: string }>(
      "SELECT owner_kind, owner_id, kind FROM catalog_media ORDER BY owner_kind, owner_id, kind");
    expect(rows).toEqual([
      { owner_kind: "course", owner_id: "course-s05a", kind: "poster_9x16" },
      { owner_kind: "institution", owner_id: "author-s05a", kind: "author_cover_9x16" },
      { owner_kind: "institution", owner_id: "yale-s05a", kind: "og" },
      { owner_kind: "institution", owner_id: "yale-s05a", kind: "university_cover_9x16" },
      { owner_kind: "lesson", owner_id: "lesson-s05a", kind: "cover_16x9" },
      { owner_kind: "subarea", owner_id: "s05a-algebra", kind: "poster_9x16" },
    ]);

    await expect(client.query(`INSERT INTO course_assets (id, course_id, kind, variant, url, pathname, width, height, sha256, alt, design_status, version)
      VALUES ('again', 'course-s05a', 'thumb', 'default', 'https://media.openuniversity.si/covers/course-s05a/thumb/${pathHash("1")}.jpg', 'covers/course-s05a/thumb/${pathHash("1")}.jpg', 1, 1, '${sha("1")}', 'x', 'approved', 1)`)).rejects.toMatchObject({ code: "55000" });

    const input: AssetInput = {
      ownerId: "computer-science", kind: "poster_9x16", variant: "default",
      url: `https://${MEDIA_PUBLIC_HOST}/covers/computer-science/poster_9x16/${pathHash("9")}.jpg`,
      pathname: `covers/computer-science/poster_9x16/${pathHash("9")}.jpg`,
      width: 540, height: 960, sha256: sha("9"), alt: "Computer Science poster", transform: null, designStatus: "approved",
    };
    expect((await swapMedia(pool, "area", input)).ownerId).toBe("computer-science");
    expect(await readActiveMedia(pool, "area", "computer-science")).toMatchObject([{ ownerId: "computer-science", kind: "poster_9x16", alt: "Computer Science poster" }]);
  });

  it("D-029: the full migration leaves no legacy asset table or cover column", async () => {
    await client.query("DROP SCHEMA public CASCADE; CREATE SCHEMA public; DROP SCHEMA IF EXISTS drizzle CASCADE");
    await runMigrations(testDatabaseUrl(), false);
    const { rows } = await client.query<{ rel: string | null }>("SELECT to_regclass(name) AS rel FROM unnest(ARRAY['public.course_assets','public.lesson_assets','public.subarea_assets']) AS name");
    expect(rows.map((row) => row.rel)).toEqual([null, null, null]);
    const columns = await client.query("SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name IN ('authors', 'home_rows') AND column_name IN ('media_sha256', 'og_media_sha256')");
    expect(columns.rows).toEqual([]);
    expect((await client.query<{ rel: string | null }>("SELECT to_regclass('public.catalog_media') AS rel")).rows[0]?.rel).toBe("catalog_media");
  });
});
