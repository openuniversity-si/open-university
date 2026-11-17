import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import pg from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { readActiveMedia, swapMedia } from "../../src/media/server/repository.ts";
import "../../src/media/server/public-hosts.ts";
import { MEDIA_PUBLIC_HOST, type AssetInput } from "../../src/media/domain/types.ts";
import { validateDatabaseUrl } from "../../scripts/lib/database-target.ts";
import { applyUrlMap, listAllMediaRows, planMigration } from "../../scripts/lib/media-migrate.ts";

const host = MEDIA_PUBLIC_HOST;
const legacyHost = "legacy-media.example";
const input: AssetInput = { ownerId: "course-1", kind: "poster_9x16", variant: "default", url: `https://${MEDIA_PUBLIC_HOST}/covers/course-1/poster_9x16/${"1".repeat(40)}.jpg`, pathname: `covers/course-1/poster_9x16/${"1".repeat(40)}.jpg`, width: 540, height: 960, sha256: "1".repeat(64), alt: "Genesis poster", transform: null, designStatus: "legacy" };
describe("R2 host rewrite on isolated Postgres", () => {
  let db: pg.Pool;
  const schema = `media_r2_${randomUUID().replaceAll("-", "")}`;
  beforeAll(async () => {
    process.env.TOWER_MEDIA_PUBLIC_HOST = host;
    const connectionString = process.env.TEST_DATABASE_URL;
    if (!connectionString) throw new Error("TEST_DATABASE_URL is required.");
    validateDatabaseUrl(connectionString, "container");
    const setup = new pg.Client({ connectionString }); await setup.connect();
    try {
      await setup.query(`CREATE SCHEMA ${schema}`); await setup.query(`SET search_path TO ${schema}`);
      await setup.query(await readFile(new URL("../../drizzle/0003_media_assets.sql", import.meta.url), "utf8"));
      await setup.query("CREATE TABLE media_objects (sha256 text PRIMARY KEY, ext text, content_type text, bytes bigint, width int, height int, created_at timestamptz DEFAULT now(), orphaned_at timestamptz)");
      for (const table of ["course_assets", "lesson_assets"]) await setup.query(`ALTER TABLE ${table} ADD COLUMN media_sha256 text REFERENCES media_objects(sha256)`);
      await setup.query(`CREATE TABLE catalog_media (
        id text PRIMARY KEY, owner_kind text NOT NULL, owner_id text NOT NULL, kind text NOT NULL, variant text NOT NULL DEFAULT 'default',
        url text NOT NULL, pathname text NOT NULL, width integer NOT NULL, height integer NOT NULL, sha256 text NOT NULL, alt text NOT NULL,
        transform jsonb, design_status text NOT NULL, version integer NOT NULL, is_active boolean NOT NULL DEFAULT true,
        created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), media_sha256 text REFERENCES media_objects(sha256))`);
      await setup.query("CREATE UNIQUE INDEX catalog_media_one_active ON catalog_media (owner_kind, owner_id, kind, variant) WHERE is_active");
    } finally { await setup.end(); }
    db = new pg.Pool({ connectionString, max: 2, options: `-c search_path=${schema}` });
  });
  afterAll(async () => { await db.query(`DROP SCHEMA ${schema} CASCADE`); await db.end(); delete process.env.TOWER_MEDIA_PUBLIC_HOST; });
  it("rewrites every version's host in one transaction and reverts exactly", async () => {
    // Two versions on a retired host, written as the old store left them (the app no longer accepts that host on write).
    await swapMedia(db, "course", input);
    const second = input.pathname.replace("1".repeat(40), "2".repeat(40));
    await db.query("UPDATE catalog_media SET is_active = false");
    await db.query(`INSERT INTO catalog_media (id, owner_kind, owner_id, kind, variant, url, pathname, width, height, sha256, alt, design_status, version)
      VALUES ('legacy-2', 'course', 'course-1', 'poster_9x16', 'default', $1, $2, 540, 960, $3, 'Genesis', 'approved', 2)`, [`https://${legacyHost}/${second}`, second, "2".repeat(64)]);
    await db.query("UPDATE catalog_media SET url = $1 WHERE id <> 'legacy-2'", [`https://${legacyHost}/${input.pathname}`]);
    const rows = await listAllMediaRows(db);
    const plan = planMigration(rows, new Map(rows.map((row) => [row.sha256, "/local"])), host);
    expect(await applyUrlMap(db, plan.rewrites, "forward")).toBe(2);
    expect((await readActiveMedia(db, "course", "course-1"))[0]?.url).toBe(`https://${host}/${input.pathname.replace("1".repeat(40), "2".repeat(40))}`);
    expect((await listAllMediaRows(db)).map((row) => row.pathname).sort()).toEqual(rows.map((row) => row.pathname).sort());
    // A row that changed meanwhile aborts the whole transaction.
    await expect(applyUrlMap(db, plan.rewrites, "forward")).rejects.toThrow(/expected URL/);
    expect(await applyUrlMap(db, plan.rewrites, "revert")).toBe(2);
    expect((await listAllMediaRows(db)).map((row) => row.url).sort()).toEqual(rows.map((row) => row.url).sort());
  });
});
