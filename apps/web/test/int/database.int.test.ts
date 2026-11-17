import { randomUUID } from "node:crypto";
import { spawnSync } from "node:child_process";
import { eq } from "drizzle-orm";
import { drizzle } from "drizzle-orm/node-postgres";
import pg from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { account, lessonProgress, session, user } from "../../src/platform/db/schema.ts";
import { migrationStatus, runMigrations } from "../../scripts/lib/migrations.ts";
import { seedDatabase } from "../../scripts/lib/database-seed.ts";
import { validateDatabaseUrl } from "../../scripts/lib/database-target.ts";
import { compareLegacySnapshots, snapshotLegacyDatabase } from "../../scripts/lib/legacy-snapshot.ts";
import { MIGRATION_COUNT } from "../fixtures/migrations.ts";

describe("versioned database migrations and constraints", () => {
  let client: pg.Client;
  let connectionString: string;

  beforeAll(async () => {
    const configured = process.env.TEST_DATABASE_URL;
    if (!configured) throw new Error("TEST_DATABASE_URL is required; no database mocks.");
    validateDatabaseUrl(configured, "container");
    connectionString = configured;
    client = new pg.Client({ connectionString });
    await client.connect();
    // Destructive setup is confined to the explicitly validated local test DB.
    await client.query('DROP SCHEMA public CASCADE; CREATE SCHEMA public; DROP SCHEMA IF EXISTS drizzle CASCADE');
  });

  afterAll(async () => { await client.end(); });

  it("reports every pending migration on an empty database without creating a schema or ledger", async () => {
    expect(await runMigrations(connectionString, true)).toEqual({ applied: 0, pending: MIGRATION_COUNT });
    const result = await client.query<{ present: boolean }>("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname='drizzle') AS present");
    expect(result.rows[0]?.present).toBe(false);
  });

  it("applies every migration on an empty database and re-runs idempotently", async () => {
    expect(await runMigrations(connectionString, false)).toEqual({ applied: MIGRATION_COUNT, pending: 0 });
    expect(await runMigrations(connectionString, false)).toEqual({ applied: MIGRATION_COUNT, pending: 0 });
    const result = await client.query<{ table_name: string }>("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name");
    expect(result.rows.map((row) => row.table_name)).toEqual([
      "account", "admin_idempotency", "admin_rate_limits", "authors", "catalog_audit", "catalog_course_projections", "catalog_home", "catalog_imports", "catalog_jobs", "catalog_media", "catalog_redirects", "catalog_release_index", "catalog_releases", "catalog_ship_batches", "catalog_ship_chunks", "catalog_texts", "config_document_revisions", "config_documents", "content_sources",
      "course_editions", "courses", "home_row_items", "home_rows", "lesson_progress", "lesson_videos", "lessons", "licenses", "media_objects",
      "r2_pending_deletions", "rate_limit", "session", "slug_redirects", "subject_areas", "subject_subareas", "user", "verification",
    ]);
  });

  it("refuses a modified migration ledger instead of silently accepting drift", async () => {
    await client.query("BEGIN");
    try {
      await client.query("UPDATE drizzle.__drizzle_migrations SET hash='modified'");
      await expect(migrationStatus(client)).rejects.toThrow("Migration history differs");
    } finally { await client.query("ROLLBACK"); }
  });

  it("round-trips progress with nullable duration and completion using Drizzle", async () => {
    const db = drizzle(client);
    const id = randomUUID();
    await db.insert(user).values({ id, name: "Test Viewer", email: `${id}@example.invalid` });
    try {
      await db.insert(lessonProgress).values({ userId: id, lessonId: "test-lesson", courseId: "test-course", positionSeconds: 0 });
      const rows = await db.select().from(lessonProgress).where(eq(lessonProgress.userId, id));
      expect(rows).toHaveLength(1);
      expect(rows[0]).toMatchObject({ userId: id, lessonId: "test-lesson", courseId: "test-course", positionSeconds: 0, durationSeconds: null, completedAt: null });
      expect(rows[0]?.updatedAt).toBeInstanceOf(Date);
    } finally { await db.delete(user).where(eq(user.id, id)); }
  });

  it.each([
    ["negative position", -1, 10, "23514"],
    ["zero duration", 0, 0, "23514"],
    ["negative duration", 0, -1, "23514"],
    ["missing required position", null, 10, "23502"],
    ["fractional position", "1.5", 10, "22P02"],
  ])("rejects %s", async (_label, position, duration, code) => {
    const id = randomUUID();
    await client.query('INSERT INTO "user" (id, name, email) VALUES ($1, $2, $3)', [id, "Constraint Viewer", `${id}@example.invalid`]);
    try {
      await expect(client.query("INSERT INTO lesson_progress (user_id, lesson_id, course_id, position_seconds, duration_seconds) VALUES ($1, 'test-lesson', 'test-course', $2, $3)", [id, position, duration])).rejects.toMatchObject({ code });
    } finally { await client.query('DELETE FROM "user" WHERE id=$1', [id]); }
  });

  it("rejects progress for a nonexistent user", async () => {
    await expect(client.query("INSERT INTO lesson_progress (user_id, lesson_id, course_id, position_seconds) VALUES ('missing-user', 'test-lesson', 'test-course', 1)")).rejects.toMatchObject({ code: "23503" });
  });

  it("enforces the composite primary key while allowing the same lesson for different users", async () => {
    const db = drizzle(client);
    const ids = [randomUUID(), randomUUID()];
    for (const id of ids) await db.insert(user).values({ id, name: "Test Viewer", email: `${id}@example.invalid` });
    try {
      for (const id of ids) await db.insert(lessonProgress).values({ userId: id, lessonId: "same-lesson", courseId: "test-course", positionSeconds: 1 });
      await expect(client.query("INSERT INTO lesson_progress (user_id, lesson_id, course_id, position_seconds) VALUES ($1, 'same-lesson', 'test-course', 2)", [ids[0]])).rejects.toMatchObject({ code: "23505" });
    } finally { for (const id of ids) await db.delete(user).where(eq(user.id, id)); }
  });

  it("cascades user deletion through progress, sessions, and accounts", async () => {
    const db = drizzle(client);
    const id = randomUUID();
    await db.insert(user).values({ id, name: "Cascade Viewer", email: `${id}@example.invalid` });
    await db.insert(lessonProgress).values({ userId: id, lessonId: "test-lesson", courseId: "test-course", positionSeconds: 10, durationSeconds: 20, completedAt: new Date() });
    await db.insert(session).values({ id: randomUUID(), userId: id, token: randomUUID(), expiresAt: new Date("2030-01-01T00:00:00Z") });
    await db.insert(account).values({ id: randomUUID(), userId: id, accountId: randomUUID(), providerId: "google" });
    await db.delete(user).where(eq(user.id, id));
    expect(await db.select().from(lessonProgress).where(eq(lessonProgress.userId, id))).toEqual([]);
    expect(await db.select().from(session).where(eq(session.userId, id))).toEqual([]);
    expect(await db.select().from(account).where(eq(account.userId, id))).toEqual([]);
  });

  it("creates the recent-progress index with descending update time", async () => {
    const result = await client.query<{ indexdef: string }>("SELECT indexdef FROM pg_indexes WHERE schemaname='public' AND indexname='lesson_progress_user_recent'");
    expect(result.rows[0]?.indexdef).toContain("(user_id, updated_at DESC)");
  });

  it("seeds only synthetic records and is idempotent", async () => {
    await seedDatabase(client);
    await seedDatabase(client);
    const rows = await drizzle(client).select().from(user);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ email: "viewer@example.invalid", image: null });
    expect(await drizzle(client).select().from(lessonProgress)).toHaveLength(2);
  });

  it("captures exact table counts in read-only transactions and detects changes", async () => {
    const before = await snapshotLegacyDatabase(client);
    expect(compareLegacySnapshots(before, await snapshotLegacyDatabase(client))).toBe(true);
    await client.query("CREATE TABLE snapshot_probe (id int)");
    try {
      expect(compareLegacySnapshots(before, await snapshotLegacyDatabase(client))).toBe(false);
      const empty = await snapshotLegacyDatabase(client);
      await client.query("INSERT INTO snapshot_probe VALUES (1)");
      expect(compareLegacySnapshots(empty, await snapshotLegacyDatabase(client))).toBe(false);
    } finally { await client.query("DROP TABLE snapshot_probe"); }
  });

  it("dry-run exits successfully with no pending SQL and rejects unknown targets and production seed", () => {
    const env = { ...process.env, TEST_DATABASE_URL: connectionString };
    const clean = spawnSync(process.execPath, ["scripts/db-migrate.ts", "--target", "container", "--dry-run"], { env, encoding: "utf8" });
    expect(clean.status, clean.stderr).toBe(0);
    expect(clean.stdout).toContain('"pending":0');
    const ledger = spawnSync(process.execPath, ["scripts/db-migrate.ts", "--target", "container", "--ledger"], { env, encoding: "utf8" });
    expect(ledger.status, ledger.stderr).toBe(0);
    const listed = JSON.parse(ledger.stdout) as { applied: { id: string; checksum: string }[]; files: { id: string; checksum: string }[] };
    expect(listed.files.length).toBeGreaterThan(0);
    expect(listed.applied).toEqual(listed.files);
    expect(ledger.stdout).not.toContain("postgresql://");
    const unknown = spawnSync(process.execPath, ["scripts/db-migrate.ts", "--target", "legacy"], { env, encoding: "utf8" });
    expect(unknown.status).toBe(1);
    const prod = spawnSync(process.execPath, ["scripts/db-seed.ts", "--target", "prod"], { env, encoding: "utf8" });
    expect(prod.status).toBe(1);
    expect(prod.stderr).toContain("restricted");
  }, 30_000); // spawns three db-migrate processes: seconds each on a loaded box
});
