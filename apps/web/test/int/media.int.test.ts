import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import pg from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { deleteMedia, listMediaVersions, MediaConflictError, readActiveMedia, swapMedia, rollbackMedia } from "../../src/media/server/repository.ts";
import { MEDIA_PUBLIC_HOST, type AssetInput } from "../../src/media/domain/types.ts";
import { validateDatabaseUrl } from "../../scripts/lib/database-target.ts";

const input: AssetInput = { ownerId: "course-1", kind: "poster_9x16", variant: "default", url: `https://${MEDIA_PUBLIC_HOST}/covers/course-1/poster_9x16/${"1".repeat(40)}.jpg`, pathname: `covers/course-1/poster_9x16/${"1".repeat(40)}.jpg`, width: 540, height: 960, sha256: "1".repeat(64), alt: "Genesis poster", transform: null, designStatus: "legacy" };
describe("media transactions on isolated PG18", () => {
  // Real pools, as in production (src/db/pool.ts): every write must check out one connection for its transaction.
  let db: pg.Pool; let peer: pg.Pool;
  const schema = `media_${randomUUID().replaceAll("-", "")}`;
  beforeAll(async () => {
    const connectionString = process.env.TEST_DATABASE_URL;
    if (!connectionString) throw new Error("TEST_DATABASE_URL is required.");
    validateDatabaseUrl(connectionString, "container");
    const setup = new pg.Client({ connectionString });
    await setup.connect();
    try {
      await setup.query(`CREATE SCHEMA ${schema}`);
      await setup.query(`SET search_path TO ${schema}`);
      await setup.query(await readFile(new URL("../../drizzle/0003_media_assets.sql", import.meta.url), "utf8"));
      await setup.query("CREATE TABLE subarea_assets (LIKE course_assets INCLUDING ALL); ALTER TABLE subarea_assets RENAME COLUMN course_id TO subarea_id");
      await setup.query("CREATE TABLE media_objects (sha256 text PRIMARY KEY, ext text, content_type text, bytes bigint, width int, height int, created_at timestamptz DEFAULT now(), orphaned_at timestamptz)");
      for (const table of ["course_assets", "lesson_assets", "subarea_assets"]) await setup.query(`ALTER TABLE ${table} ADD COLUMN media_sha256 text REFERENCES media_objects(sha256)`);
      await setup.query(`CREATE TABLE catalog_media (
        id text PRIMARY KEY, owner_kind text NOT NULL, owner_id text NOT NULL, kind text NOT NULL, variant text NOT NULL DEFAULT 'default',
        url text NOT NULL, pathname text NOT NULL, width integer NOT NULL, height integer NOT NULL, sha256 text NOT NULL, alt text NOT NULL,
        transform jsonb, design_status text NOT NULL, version integer NOT NULL, is_active boolean NOT NULL DEFAULT true,
        created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), media_sha256 text REFERENCES media_objects(sha256))`);
      await setup.query("CREATE UNIQUE INDEX catalog_media_one_active ON catalog_media (owner_kind, owner_id, kind, variant) WHERE is_active");
      await setup.query("CREATE UNIQUE INDEX catalog_media_version ON catalog_media (owner_kind, owner_id, kind, variant, version)");
    } finally { await setup.end(); }
    db = new pg.Pool({ connectionString, max: 3, options: `-c search_path=${schema}` });
    peer = new pg.Pool({ connectionString, max: 3, options: `-c search_path=${schema}` });
  });
  afterAll(async () => { await db.query(`DROP SCHEMA ${schema} CASCADE`); await db.end(); await peer.end(); });
  it("swaps, preserves versions, and re-runs idempotently", async () => {
    expect((await swapMedia(db, "course", input)).version).toBe(1);
    expect((await swapMedia(db, "course", input)).version).toBe(1);
    expect((await swapMedia(db, "course", { ...input, alt: "Revised Genesis poster" })).version).toBe(2);
    const active = await readActiveMedia(db, "course", "course-1");
    expect(active).toHaveLength(1); expect(active[0]?.alt).toBe("Revised Genesis poster");
  });
  it("enforces one active row directly in PostgreSQL", async () => {
    await expect(db.query("INSERT INTO catalog_media (id, owner_kind, owner_id, kind, variant, url, pathname, width, height, sha256, alt, transform, design_status, version, is_active) SELECT 'duplicate', owner_kind, owner_id, kind, variant, url, pathname, width, height, sha256, alt, transform, design_status, 99, true FROM catalog_media WHERE is_active")).rejects.toMatchObject({ code: "23505" });
  });
  it("keeps the prior active row after a failed insert", async () => {
    await db.query("ALTER TABLE catalog_media ADD CONSTRAINT test_failure CHECK (alt <> 'reject')");
    try {
      await expect(swapMedia(db, "course", { ...input, alt: "reject" })).rejects.toMatchObject({ code: "23514" });
      expect((await readActiveMedia(db, "course", "course-1"))[0]?.version).toBe(2);
    } finally { await db.query("ALTER TABLE catalog_media DROP CONSTRAINT test_failure"); }
  });
  it("serializes simultaneous swaps and retains just one active version", async () => {
    const saved = await Promise.all([swapMedia(db, "course", { ...input, alt: "Concurrent A" }), swapMedia(peer, "course", { ...input, alt: "Concurrent B" })]);
    expect(saved.map((asset) => asset.version).sort()).toEqual([3,4]);
    expect(await readActiveMedia(db, "course", "course-1")).toHaveLength(1);
  });
  it("rolls back without deleting history, then increments from the maximum", async () => {
    expect((await rollbackMedia(db, "course", "course-1", "poster_9x16", "default", 1)).version).toBe(1);
    await expect(rollbackMedia(db, "course", "course-1", "poster_9x16", "default", 999)).rejects.toThrow();
    expect((await readActiveMedia(db, "course", "course-1"))[0]?.version).toBe(1);
    expect((await swapMedia(db, "course", { ...input, alt: "After rollback" })).version).toBe(5);
  });
  it("supports lessons and independent variants", async () => {
    const lesson = { ...input, ownerId: "lesson-1", kind: "cover_16x9" as const };
    await swapMedia(db, "lesson", lesson);
    await swapMedia(db, "lesson", { ...lesson, variant: "alternate" });
    expect(await readActiveMedia(db, "lesson", "lesson-1")).toHaveLength(2);
    await expect(swapMedia(db, "lesson", input)).rejects.toThrow();
  });
  it("runs 16 concurrent uploads of one owner/kind on a pool of 3: one active version, every version distinct, no lock left", async () => {
    const owner = { ...input, ownerId: "course-16" };
    const saved = await Promise.all(Array.from({ length: 16 }, (_, index) => swapMedia(index % 2 ? peer : db, "course", { ...owner, alt: `Concurrent ${String(index)}` })));
    expect(saved.map((asset) => asset.version).sort((a, b) => a - b)).toEqual(Array.from({ length: 16 }, (_, index) => index + 1));
    const active = await readActiveMedia(db, "course", "course-16");
    expect(active).toHaveLength(1);
    expect(active[0]?.version).toBe(16);
    // Every connection is back in its pool and no advisory lock survived its transaction.
    expect([db.totalCount - db.idleCount, peer.totalCount - peer.idleCount]).toEqual([0, 0]);
    expect((await db.query<{ n: number }>("SELECT count(*)::int AS n FROM pg_locks WHERE locktype = 'advisory' AND database = (SELECT oid FROM pg_database WHERE datname = current_database())")).rows[0]?.n).toBe(0);
    expect((await swapMedia(db, "course", { ...owner, alt: "After the burst" })).version).toBe(17);
  });
  it("releases the connection and the lock when a write fails", async () => {
    await expect(rollbackMedia(db, "course", "course-16", "poster_9x16", "default", 999)).rejects.toThrow();
    expect(db.totalCount - db.idleCount).toBe(0);
    expect((await db.query<{ n: number }>("SELECT count(*)::int AS n FROM pg_locks WHERE locktype = 'advisory' AND database = (SELECT oid FROM pg_database WHERE datname = current_database())")).rows[0]?.n).toBe(0);
  });
  it("deletes inactive versions and non-default variants in one transaction, sharing keys across tables", async () => {
    const versions = () => listMediaVersions(db, "lesson", "lesson-1", "cover_16x9");
    await expect(deleteMedia(db, "lesson", "lesson-1", "cover_16x9", "default", 1, { apply: true })).rejects.toBeInstanceOf(MediaConflictError);
    await expect(deleteMedia(db, "lesson", "lesson-1", "cover_16x9", "default", undefined, { apply: true })).rejects.toBeInstanceOf(MediaConflictError);
    const dryRun = await deleteMedia(db, "lesson", "lesson-1", "cover_16x9", "alternate", undefined, { apply: false });
    // Every fixture row (both tables) points at the same immutable key.
    expect([dryRun.targets.length, dryRun.shared.has(input.pathname)]).toEqual([1, true]);
    await expect(deleteMedia(db, "lesson", "lesson-1", "cover_16x9", "alternate", undefined, { apply: true, beforeCommit: () => Promise.reject(new Error("R2 down")) })).rejects.toThrow("R2 down");
    expect(await versions()).toHaveLength(2);
    expect((await deleteMedia(db, "lesson", "lesson-1", "cover_16x9", "alternate", undefined, { apply: true })).activeAfter).toBeNull();
    expect((await versions()).map((asset) => asset.variant)).toEqual(["default"]);
    expect((await deleteMedia(db, "course", "course-1", "poster_9x16", "default", 2, { apply: true })).activeAfter?.version).toBe(5);
    expect((await deleteMedia(db, "course", "course-1", "poster_9x16", "default", 2, { apply: true })).targets).toHaveLength(0);
  });
});
