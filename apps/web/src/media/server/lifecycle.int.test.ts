import { randomUUID } from "node:crypto";
import pg from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { validateDatabaseUrl } from "../../../scripts/lib/database-target.ts";
import { clearOrphaned, markOrphaned, retentionEligible } from "./lifecycle.ts";
import { RETENTION_MS } from "../domain/figure-exit.ts";

describe("lifecycle retention on isolated PG18", () => {
  let db: pg.Pool;
  const schema = `life_${randomUUID().replaceAll("-", "")}`;
  const sha = "d".repeat(64);
  beforeAll(async () => {
    const connectionString = process.env.TEST_DATABASE_URL;
    if (!connectionString) throw new Error("TEST_DATABASE_URL is required.");
    validateDatabaseUrl(connectionString, "container");
    const setup = new pg.Client({ connectionString });
    await setup.connect();
    try {
      await setup.query(`CREATE SCHEMA ${schema}`);
      await setup.query(`SET search_path TO ${schema}`);
      await setup.query("CREATE TABLE media_objects (sha256 text PRIMARY KEY, ext text, content_type text, bytes bigint, width int, height int, created_at timestamptz DEFAULT now(), orphaned_at timestamptz)");
      await setup.query("CREATE TABLE catalog_media (media_sha256 text)");
      await setup.query("INSERT INTO media_objects (sha256, ext, content_type, bytes, width, height) VALUES ($1, 'jpg', 'image/jpeg', 10, 1, 1)", [sha]);
    } finally { await setup.end(); }
    db = new pg.Pool({ connectionString, max: 2, options: `-c search_path=${schema}` });
  });
  afterAll(async () => { await db.query(`DROP SCHEMA ${schema} CASCADE`); await db.end(); });

  it("does not move the marker, clears it on a new link, and blocks a peer that cannot be locked", async () => {
    expect(await markOrphaned(db, sha)).toBe("marked");
    const first = (await db.query<{ orphaned_at: Date | null }>("SELECT orphaned_at FROM media_objects WHERE sha256 = $1", [sha])).rows[0]?.orphaned_at;
    expect(await markOrphaned(db, sha)).toBe("already");
    const second = (await db.query<{ orphaned_at: Date | null }>("SELECT orphaned_at FROM media_objects WHERE sha256 = $1", [sha])).rows[0]?.orphaned_at;
    expect(first).toBeInstanceOf(Date);
    expect(second).toBeInstanceOf(Date);
    expect(second?.toISOString()).toBe(first?.toISOString());
    await db.query("INSERT INTO catalog_media (media_sha256) VALUES ($1)", [sha]);
    await clearOrphaned(db, sha);
    expect((await db.query<{ orphaned_at: Date | null }>("SELECT orphaned_at FROM media_objects WHERE sha256 = $1", [sha])).rows[0]?.orphaned_at).toBeNull();
    expect(await markOrphaned(db, sha)).toBe("referenced");
    await db.query("DELETE FROM catalog_media");
    await db.query("UPDATE media_objects SET orphaned_at = now() - interval '30 days' WHERE sha256 = $1", [sha]);
    const now = new Date();
    expect(await retentionEligible(db, `m/${sha}.jpg`, new Date(now.getTime() + RETENTION_MS))).toBe(true);
    const peer = new pg.Pool({ connectionString: process.env.TEST_DATABASE_URL, max: 1, options: `-c search_path=${schema}` });
    const locked = await peer.query<{ ok: boolean }>("SELECT pg_try_advisory_lock(742021, 4) AS ok");
    expect(locked.rows[0]?.ok).toBe(true);
    const blocked = await db.query<{ ok: boolean }>("SELECT pg_try_advisory_lock(742021, 4) AS ok");
    expect(blocked.rows[0]?.ok).toBe(false);
    await peer.query("SELECT pg_advisory_unlock(742021, 4)");
    await peer.end();
  });
});
