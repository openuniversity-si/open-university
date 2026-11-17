import { randomUUID } from "node:crypto";
import pg from "pg";
import { afterAll, beforeAll, expect, it } from "vitest";
import { consumeAuthenticated } from "../../src/platform/security/rate-limit.ts";
import { validateDatabaseUrl } from "../../scripts/lib/database-target.ts";

const schema = `limiter_${randomUUID().replaceAll("-", "")}`;
let db: pg.Pool;
let peer: pg.Pool;
beforeAll(async () => {
  const connectionString = process.env.TEST_DATABASE_URL;
  if (!connectionString) throw new Error("TEST_DATABASE_URL is required");
  validateDatabaseUrl(connectionString, "container");
  db = new pg.Pool({ connectionString, max: 3, options: `-c search_path=${schema}` });
  await db.query(`CREATE SCHEMA ${schema}`);
  await db.query("CREATE TABLE admin_rate_limits (secret_hash text PRIMARY KEY, minute bigint NOT NULL, requests integer NOT NULL)");
  peer = new pg.Pool({ connectionString, max: 3, options: `-c search_path=${schema}` });
});
afterAll(async () => { await peer.end(); await db.query(`DROP SCHEMA ${schema} CASCADE`); await db.end(); });

it("atomically shares an exact allowance across pools/instances and resets by database minute", async () => {
  // Stay away from rollover, so the test asserts one full window even when launched on a minute boundary.
  const { rows } = await db.query<{ remaining: number }>("SELECT 60 - mod(extract(epoch FROM now()), 60) AS remaining");
  if (Number(rows[0]?.remaining) < 2) await new Promise((resolve) => setTimeout(resolve, 2100));
  const key = "a".repeat(64);
  const results = await Promise.all(Array.from({ length: 616 }, (_, i) => consumeAuthenticated(i % 2 ? db : peer, key)));
  expect(results.filter((seconds) => seconds === 0)).toHaveLength(600);
  expect(results.filter((seconds) => seconds > 0)).toHaveLength(16);
  expect(results.every((seconds) => seconds >= 0 && seconds <= 60)).toBe(true);
  expect(await consumeAuthenticated(peer, "b".repeat(64))).toBe(0);
  await db.query("UPDATE admin_rate_limits SET minute = minute - 1 WHERE secret_hash = $1", [key]);
  expect(await consumeAuthenticated(db, key)).toBe(0);
  expect((await db.query("SELECT requests FROM admin_rate_limits WHERE secret_hash = $1", [key])).rows).toEqual([{ requests: 1 }]);
  expect(db.waitingCount + peer.waitingCount).toBe(0);
});
