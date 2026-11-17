import { cpSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { drizzle } from "drizzle-orm/node-postgres";
import { migrate } from "drizzle-orm/node-postgres/migrator";
import pg from "pg";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { migrationsFolder, runMigrations } from "../../scripts/lib/migrations.ts";
import { testDatabaseUrl } from "../fixtures/admin-catalog.ts";

/** The pr-256 production clone in miniature: University rows grouping courses of person lecturers, three lecturers shared across rows. */
const ROWS = Array.from({ length: 20 }, (_, index) => ({ id: `university-${String(index + 1)}`, title: `University ${String(index + 1)}`, fullName: `Fixture University Number ${String(index + 1)}` }));
const SHARED = ["shared-a", "shared-b", "shared-c"];

describe("0025 (D-024): University rows become institutions; lecturers stay", () => {
  let db: pg.Client;
  const reset = () => db.query("DROP SCHEMA public CASCADE; CREATE SCHEMA public; DROP SCHEMA IF EXISTS drizzle CASCADE");

  beforeEach(async () => {
    db = new pg.Client({ connectionString: testDatabaseUrl() });
    await db.connect();
    await reset();
    const folder = mkdtempSync(join(tmpdir(), "hierarchy-migration-"));
    cpSync(migrationsFolder, folder, { recursive: true });
    const file = join(folder, "meta/_journal.json");
    const journal = JSON.parse(readFileSync(file, "utf8")) as { entries: { idx: number }[] };
    writeFileSync(file, JSON.stringify({ ...journal, entries: journal.entries.filter((entry) => entry.idx <= 24) }));
    await migrate(drizzle(db), { migrationsFolder: folder });
    await db.query("INSERT INTO licenses (code, name, requires_attribution) VALUES ('fixture-license', 'Fixture', false)");
    await db.query("INSERT INTO content_sources (id, kind, title, publisher, url) VALUES ('fixture-source', 'institution-site', 'Fixture', 'Fixture', 'https://example.org')");
    // Lecturers (default kind before 0025 is person), plus one institution already holding a row's slug, as Stanford does in production.
    await db.query("INSERT INTO authors (id, slug, name, monogram) SELECT id, id, id, 'L' FROM unnest($1::text[]) AS id", [[...SHARED, ...ROWS.map((row) => `lecturer-${row.id}`), "channel-lecturer"]]);
    await db.query("INSERT INTO authors (id, slug, name, monogram, kind) VALUES ('author-existing', 'university-1', 'University One', 'U', 'institution')");
    for (const [index, row] of ROWS.entries()) {
      await db.query("INSERT INTO home_rows (id, kind, title, full_name, position) VALUES ($1, 'curated', $2, $3, $4)", [row.id, row.title, row.fullName, index + 1]);
      await db.query(`INSERT INTO catalog_media (id, owner_kind, owner_id, kind, url, pathname, width, height, sha256, alt, design_status, version)
        VALUES ($1, 'institution', $2, 'university_cover_9x16', $3, $4, 540, 960, $5, $2, 'approved', 1)`,
      [`cover-${row.id}`, row.id, `https://media.openuniversity.si/${row.id}.jpg`, `${row.id}.jpg`, String(index).padStart(64, "a")]);
      for (const [position, lecturer] of [`lecturer-${row.id}`, SHARED[index % SHARED.length] ?? ""].entries()) {
        await course(`${row.id}-${String(position)}`, lecturer);
        await db.query("INSERT INTO home_row_items (row_id, course_id, position) VALUES ($1, $2, $3)", [row.id, `${row.id}-${String(position)}`, position + 1]);
      }
    }
    await course("outside-any-row", "channel-lecturer");
  });
  afterEach(async () => {
    await reset();
    await db.end();
    await runMigrations(testDatabaseUrl(), false);
  });

  async function course(id: string, lecturer: string) {
    await db.query(`INSERT INTO courses (id, slug, author_id, title, status, source_id, license_code, canonical_url, rights_status, area_id)
      SELECT $1, $1, $2, $1, 'published', 'fixture-source', 'fixture-license', 'https://example.org/' || $1, 'cleared', id FROM subject_areas ORDER BY position LIMIT 1`, [id, lecturer]);
  }

  it("creates one institution per row from the row, links its courses and copies the row's cover bytes", async () => {
    expect((await runMigrations(testDatabaseUrl(), false)).pending).toBe(0);
    expect((await runMigrations(testDatabaseUrl(), false)).pending).toBe(0);
    const rows = (await db.query<{ id: string; institution_id: string; kind: string; name: string; monogram: string }>(
      "SELECT r.id, r.institution_id, a.kind, a.name, a.monogram FROM home_rows r JOIN authors a ON a.id = r.institution_id ORDER BY r.position")).rows;
    expect(rows).toHaveLength(20);
    expect(rows[0]).toEqual({ id: "university-1", institution_id: "author-existing", kind: "institution", name: "University One", monogram: "U" });
    expect(rows[1]).toEqual({ id: "university-2", institution_id: "university-2", kind: "institution", name: "University 2", monogram: "FUN" });
    expect(rows.every((row) => row.kind === "institution")).toBe(true);
    // Every placed course takes its row's institution; its lecturer is unchanged, so shared lecturers teach at several institutions.
    const courses = (await db.query<{ id: string; author_id: string; institution_id: string | null }>("SELECT id, author_id, institution_id FROM courses ORDER BY id")).rows;
    expect(courses.find((row) => row.id === "university-2-1")).toEqual({ id: "university-2-1", author_id: "shared-b", institution_id: "university-2" });
    expect(courses.find((row) => row.id === "outside-any-row")).toEqual({ id: "outside-any-row", author_id: "channel-lecturer", institution_id: null });
    const shared = (await db.query<{ author_id: string; n: number }>("SELECT author_id, count(DISTINCT institution_id)::int AS n FROM courses WHERE author_id = ANY($1) GROUP BY 1 ORDER BY 1", [SHARED])).rows;
    expect(shared).toEqual([{ author_id: "shared-a", n: 7 }, { author_id: "shared-b", n: 7 }, { author_id: "shared-c", n: 6 }]);
    expect((await db.query("SELECT kind, count(*)::int AS n FROM authors GROUP BY 1 ORDER BY 1")).rows).toEqual([{ kind: "institution", n: 20 }, { kind: "person", n: 24 }]);
    const covers = (await db.query<{ owner_id: string; sha256: string }>("SELECT owner_id, sha256 FROM catalog_media WHERE owner_kind = 'institution' AND kind = 'poster_9x16' AND is_active ORDER BY owner_id")).rows;
    expect(covers).toHaveLength(20);
    expect(covers.find((row) => row.owner_id === "author-existing")?.sha256).toBe("0".padStart(64, "a"));
  });

  it("stops instead of guessing when a course sits in two University rows", async () => {
    await db.query("INSERT INTO home_row_items (row_id, course_id, position) VALUES ('university-2', 'university-1-0', 9)");
    await expect(runMigrations(testDatabaseUrl(), false)).rejects.toMatchObject({ cause: { code: "23514", constraint: "home_rows_institution_courses" } });
  });

  it("stops when a lecturer already holds a row's slug", async () => {
    await db.query("UPDATE authors SET slug = 'university-3' WHERE id = 'lecturer-university-3'");
    await expect(runMigrations(testDatabaseUrl(), false)).rejects.toMatchObject({ cause: { code: "23514", constraint: "home_rows_institution" } });
  });
});
