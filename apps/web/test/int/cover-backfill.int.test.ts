import { cpSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { drizzle } from "drizzle-orm/node-postgres";
import { migrate } from "drizzle-orm/node-postgres/migrator";
import pg from "pg";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { migrationsFolder, runMigrations } from "../../scripts/lib/migrations.ts";
import { testDatabaseUrl } from "../fixtures/admin-catalog.ts";

const KINDS = ["poster_9x16", "hero_desktop_16x9", "hero_present", "hero_mobile_9x16"] as const;

describe("0028 (D-031): backfill declares coverFrom and holds a course whose owner has no cover", () => {
  let db: pg.Client;
  const reset = () => db.query("DROP SCHEMA public CASCADE; CREATE SCHEMA public; DROP SCHEMA IF EXISTS drizzle CASCADE");

  beforeEach(async () => {
    db = new pg.Client({ connectionString: testDatabaseUrl() });
    await db.connect();
    await reset();
    const folder = mkdtempSync(join(tmpdir(), "cover-backfill-"));
    cpSync(migrationsFolder, folder, { recursive: true });
    const file = join(folder, "meta/_journal.json");
    const journal = JSON.parse(readFileSync(file, "utf8")) as { entries: { idx: number }[] };
    writeFileSync(file, JSON.stringify({ ...journal, entries: journal.entries.filter((entry) => entry.idx <= 27) }));
    await migrate(drizzle(db), { migrationsFolder: folder });
    await db.query("INSERT INTO licenses (code, name, requires_attribution) VALUES ('fixture-license', 'Fixture', false)");
    await db.query("INSERT INTO content_sources (id, kind, title, publisher, url) VALUES ('fixture-source', 'institution-site', 'Fixture', 'Fixture', 'https://example.org')");
    await db.query("INSERT INTO authors (id, slug, name, monogram, kind) VALUES ('lecturer-1', 'lecturer-1', 'Lecturer', 'L', 'person')");
    await db.query("INSERT INTO authors (id, slug, name, monogram, kind) VALUES ('institution-1', 'institution-1', 'Institution', 'I', 'institution')");
    await covers("subarea", "classical-mechanics", KINDS);
    await covers("subarea", "optics", ["poster_9x16"]);
    await covers("area", "astronomy", KINDS);
    await covers("area", "physics", KINDS);
    await covers("course", "published-own", KINDS);
    await covers("institution", "institution-1", KINDS);
    await course("published-subarea", { provisional: true, area: "physics", subarea: "classical-mechanics", status: "published" });
    await course("published-thin", { provisional: true, area: "physics", subarea: "optics", status: "published" });
    await course("published-area", { provisional: true, area: "astronomy", subarea: null, status: "published" });
    await course("published-own", { provisional: false, area: "physics", subarea: null, status: "published" });
    await course("draft-bare", { provisional: false, area: "physics", subarea: null, status: "draft" });
    await course("published-institution", { provisional: false, area: "physics", subarea: null, status: "published" });
  });

  afterEach(async () => {
    await reset();
    await db.end();
    await runMigrations(testDatabaseUrl(), false);
  });

  async function covers(owner: string, id: string, kinds: readonly string[]) {
    for (const [index, kind] of kinds.entries()) {
      await db.query(`INSERT INTO catalog_media (id, owner_kind, owner_id, kind, url, pathname, width, height, sha256, alt, design_status, version)
        VALUES ($1, $2, $3, $4, $5, $6, 540, 960, $7, $3, 'approved', 1)`,
      [`${owner}-${id}-${kind}`, owner, id, kind, `https://media.example/${id}/${kind}.webp`, `${id}/${kind}.webp`, String(index + 1).padStart(64, "a")]);
    }
  }

  async function course(id: string, row: { provisional: boolean; area: string; subarea: string | null; status: string }) {
    await db.query(`INSERT INTO courses (id, slug, author_id, title, status, source_id, license_code, canonical_url, rights_status, area_id, subarea_id, cover_provisional, published_at)
      VALUES ($1, $1, 'lecturer-1', $1, $2, 'fixture-source', 'fixture-license', 'https://example.org/' || $1, 'cleared', $3, $4, $5, CASE WHEN $2 = 'published' THEN now() ELSE NULL END)`,
    [id, row.status, row.area, row.subarea, row.provisional]);
  }

  it("D-031: backfill declares coverFrom and holds a published course whose owner has no cover", async () => {
    expect((await runMigrations(testDatabaseUrl(), false)).pending).toBe(0);
    expect((await runMigrations(testDatabaseUrl(), false)).pending).toBe(0);
    const rows = (await db.query<{ id: string; cover_from: string; status: string; published_at: Date | null }>(
      "SELECT id, cover_from, status, published_at FROM courses ORDER BY id")).rows;
    expect(rows.map((row) => ({ id: row.id, cover_from: row.cover_from, status: row.status }))).toEqual([
      { id: "draft-bare", cover_from: "own", status: "draft" },
      { id: "published-area", cover_from: "area:astronomy", status: "published" },
      { id: "published-institution", cover_from: "own", status: "draft" },
      { id: "published-own", cover_from: "own", status: "published" },
      { id: "published-subarea", cover_from: "subarea:classical-mechanics", status: "published" },
      { id: "published-thin", cover_from: "subarea:optics", status: "draft" },
    ]);
    expect(rows.filter((row) => row.published_at instanceof Date).map((row) => row.id)).toEqual(["published-area", "published-own", "published-subarea"]);
    const audit = (await db.query<{ entity_id: string; reason: string }>(
      "SELECT entity_id, after->>'reason' AS reason FROM catalog_audit WHERE action = 'cover.backfill' ORDER BY entity_id")).rows;
    expect(audit).toEqual([
      { entity_id: "draft-bare", reason: "missing poster_9x16,hero_desktop_16x9,hero_present,hero_mobile_9x16" },
      { entity_id: "published-institution", reason: "missing poster_9x16,hero_desktop_16x9,hero_present,hero_mobile_9x16" },
      { entity_id: "published-thin", reason: "missing hero_desktop_16x9,hero_present,hero_mobile_9x16" },
    ]);
    expect((await db.query("SELECT 1 FROM information_schema.columns WHERE table_name = 'courses' AND column_name = 'cover_provisional'")).rowCount).toBe(0);
    await expect(db.query("UPDATE courses SET cover_from = 'area:physics' WHERE id = 'published-subarea'")).rejects.toMatchObject({ code: "23514" });
    await db.query("UPDATE courses SET cover_from = 'own' WHERE id = 'published-subarea'");
    await expect(db.query(`INSERT INTO courses (id, slug, author_id, title, area_id, subarea_id, cover_from, shared_with)
      VALUES ('bad-area', 'bad-area', 'lecturer-1', 'Bad', 'physics', 'optics', 'area:physics', '{}')`)).rejects.toMatchObject({ code: "23514" });
  });
});
