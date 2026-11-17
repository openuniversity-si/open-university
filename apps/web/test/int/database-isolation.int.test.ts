import { randomBytes } from "node:crypto";
import pg from "pg";
import { afterAll, beforeAll, expect, inject, it } from "vitest";
import { createHarness, seedCatalog, type Harness } from "../fixtures/admin-catalog.ts";
import { resetCatalogTables } from "../fixtures/catalog-reset.ts";
import { MIGRATION_COUNT } from "../fixtures/migrations.ts";

let h: Harness;
beforeAll(() => { h = createHarness(); });
afterAll(async () => { await h.close(); });

it("uses a migrated file database distinct from the launcher and template", async () => {
  const { connectionString, template, prefix } = inject("integrationDatabase");
  const { rows: [row] } = await h.pool.query<{ name: string; migrations: number }>(
    "SELECT current_database() AS name, (SELECT count(*)::int FROM drizzle.__drizzle_migrations) AS migrations",
  );
  expect(row?.name).toMatch(new RegExp(`^${prefix}f[a-f0-9]{16}$`));
  expect(row?.name).not.toBe(new URL(connectionString).pathname.slice(1));
  expect(row?.name).not.toBe(template);
  expect(row?.migrations).toBe(MIGRATION_COUNT);
});

it("keeps file-local writes out of both the template and the launcher's database", async () => {
  await h.pool.query("CREATE TABLE isolation_probe (id int PRIMARY KEY); INSERT INTO isolation_probe VALUES (1)");
  const { connectionString, template, prefix } = inject("integrationDatabase");
  // Never open the live template: another worker may be cloning it at this exact moment.
  const probe = `${prefix}f${randomBytes(8).toString("hex")}`;
  await h.pool.query(`CREATE DATABASE "${probe}" TEMPLATE "${template}"`);
  for (const database of [new URL(connectionString).pathname.slice(1), probe]) {
    const url = new URL(connectionString); url.pathname = `/${database}`;
    const peer = new pg.Client({ connectionString: url.toString() });
    await peer.connect();
    try { expect((await peer.query("SELECT to_regclass('public.isolation_probe') AS probe")).rows).toEqual([{ probe: null }]); }
    finally { await peer.end(); }
  }
  expect((await h.pool.query("SELECT id FROM isolation_probe")).rows).toEqual([{ id: 1 }]);
});

it("resets every fixture row and sequence while retaining reference data, migrations and release protection", async () => {
  const first = await seedCatalog(h);
  const kept = (await h.pool.query<{ id: string; title: string }>("SELECT id, title FROM subject_areas ORDER BY position LIMIT 1")).rows[0];
  if (!kept) throw new Error("the migrated database has no subject area");
  await h.pool.query("UPDATE subject_areas SET title = 'Isolation rename' WHERE id = $1", [kept.id]);
  await h.pool.query("INSERT INTO subject_areas (id, title, position) VALUES ('isolation-area', 'Isolation Area', (SELECT max(position) + 1 FROM subject_areas))");
  await h.pool.query("INSERT INTO subject_subareas (id, area_id, title, position) VALUES ('isolation-subarea', 'isolation-area', 'Isolation Subarea', 1)");
  await resetCatalogTables(process.env.TEST_DATABASE_URL ?? "");
  const tables = ["catalog_media", "admin_idempotency", "r2_pending_deletions", "catalog_audit", "catalog_course_projections", "catalog_release_index", "catalog_redirects", "catalog_releases", "catalog_jobs", "catalog_imports", "home_row_items", "home_rows", "catalog_texts", "lesson_videos", "lessons", "course_editions", "courses", "authors", "content_sources", "licenses", "slug_redirects"];
  for (const table of tables) expect((await h.pool.query(`SELECT count(*)::int AS n FROM ${table}`)).rows).toEqual([{ n: 0 }]);
  const count = async (table: string) => (await h.pool.query<{ n: number }>(`SELECT count(*)::int AS n FROM ${table}`)).rows;
  expect(await count("subject_areas")).toEqual(await count("tower_test.subject_areas"));
  expect(await count("subject_subareas")).toEqual(await count("tower_test.subject_subareas"));
  expect((await h.pool.query("SELECT title FROM subject_areas WHERE id = $1", [kept.id])).rows).toEqual([{ title: kept.title }]);
  expect((await h.pool.query("SELECT id FROM subject_areas WHERE id = 'isolation-area'")).rows).toEqual([]);
  expect((await h.pool.query("SELECT id FROM subject_subareas WHERE id = 'isolation-subarea'")).rows).toEqual([]);
  const second = await seedCatalog(h);
  expect(second).toEqual(first);
  await expect(h.pool.query("DELETE FROM catalog_releases")).rejects.toMatchObject({ code: "55000" });
  expect((await h.pool.query("SELECT count(*)::int AS n FROM drizzle.__drizzle_migrations")).rows).toEqual([{ n: MIGRATION_COUNT }]);
});
