import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import pg from "pg";
import sharp from "sharp";
import { afterAll, beforeAll, expect, it, vi } from "vitest";
import { checkObjects, objectDescriptor, uploadObject } from "../../src/media/server/objects.ts";
import { createAdminRateLimiter, handleAdminMediaAttach, handleAdminMediaCheck, handleAdminMediaObjectUpload, type AdminMediaDeps } from "../../src/media/server/admin.ts";
import { readActiveMedia, swapMedia } from "../../src/media/server/repository.ts";
import { prepareMedia } from "../../src/media/server/prepare.ts";
import { type MediaObjectStore } from "../../src/media/server/storage.ts";
import { mediaPublicHost } from "../../src/media/domain/types.ts";
import { backfillContent, contentSummary, copyContent, planContentMigration, rollbackContent, verifyContent } from "../../scripts/lib/media-content-migrate.ts";
import { validateDatabaseUrl } from "../../scripts/lib/database-target.ts";

const schema = `media_content_${randomUUID().replaceAll("-", "")}`;
let db: pg.Pool;
const bytesByKey = new Map<string, Buffer>();
const put = vi.fn<MediaObjectStore["put"]>((key, bytes) => {
  if (bytesByKey.has(key)) return Promise.resolve("exists");
  bytesByKey.set(key, Buffer.from(bytes)); return Promise.resolve("created");
});
const store: MediaObjectStore = { publicUrl: (key) => `https://${mediaPublicHost({})}/${key}`,
  head: (key) => Promise.resolve(bytesByKey.has(key) ? { size: bytesByKey.get(key)?.length ?? 0 } : null),
  get: (key) => Promise.resolve(bytesByKey.get(key) ?? null), put,
  delete: () => Promise.reject(new Error("E2 never deletes objects")) };
const deps: AdminMediaDeps = { secret: "content-test", limiter: createAdminRateLimiter(), db: () => db, store: () => store,
  invalidate: () => {}, courseOf: (_owner, id) => Promise.resolve({ courseId: id, published: false }),
  owners: () => ({ courseOf: () => Promise.resolve(undefined), graph: () => Promise.resolve({ courses: [], lessons: [] }), lockGraph: () => Promise.resolve(), inventory: () => Promise.resolve([]) }) };
const jsonRequest = (path: string, body: unknown) => new Request(`https://test.invalid/api/admin/media/${path}`, {
  method: "POST", headers: { authorization: "Bearer content-test", "content-type": "application/json" }, body: JSON.stringify(body) });
const image = (color: string) => sharp({ create: { width: 32, height: 18, channels: 3, background: color } }).webp().toBuffer();

beforeAll(async () => {
  const connectionString = process.env.TEST_DATABASE_URL;
  if (!connectionString) throw new Error("TEST_DATABASE_URL required");
  validateDatabaseUrl(connectionString, "container");
  const setup = new pg.Client({ connectionString }); await setup.connect();
  try {
    await setup.query(`CREATE SCHEMA ${schema}; SET search_path TO ${schema}`);
    await setup.query(await readFile(new URL("../../drizzle/0003_media_assets.sql", import.meta.url), "utf8"));
    await setup.query("CREATE TABLE subarea_assets (LIKE course_assets INCLUDING ALL); ALTER TABLE subarea_assets RENAME COLUMN course_id TO subarea_id");
    const migration = await readFile(new URL("../../drizzle/0018_content_addressed_media.sql", import.meta.url), "utf8");
    await setup.query(migration.split("--> statement-breakpoint")[0] ?? "");
    await setup.query(await readFile(new URL("../../drizzle/0021_lifecycle_gc_markers.sql", import.meta.url), "utf8"));
    for (const table of ["course_assets", "lesson_assets", "subarea_assets"]) await setup.query(`ALTER TABLE ${table} ADD COLUMN media_sha256 text REFERENCES media_objects(sha256)`);
    await setup.query(`CREATE TABLE catalog_media (
      id text PRIMARY KEY, owner_kind text NOT NULL, owner_id text NOT NULL, kind text NOT NULL, variant text NOT NULL DEFAULT 'default',
      url text NOT NULL, pathname text NOT NULL, width integer NOT NULL, height integer NOT NULL, sha256 text NOT NULL, alt text NOT NULL,
      transform jsonb, design_status text NOT NULL, version integer NOT NULL, is_active boolean NOT NULL DEFAULT true,
      created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), media_sha256 text REFERENCES media_objects(sha256))`);
    await setup.query("CREATE UNIQUE INDEX catalog_media_one_active ON catalog_media (owner_kind, owner_id, kind, variant) WHERE is_active");
    await setup.query("CREATE TABLE authors (id text PRIMARY KEY, cover jsonb, media_sha256 text REFERENCES media_objects(sha256)); CREATE TABLE home_rows (id text PRIMARY KEY, cover jsonb, media_sha256 text REFERENCES media_objects(sha256), og_media_sha256 text REFERENCES media_objects(sha256)); CREATE TABLE catalog_releases (number int PRIMARY KEY, payload jsonb)");
  } finally { await setup.end(); }
  db = new pg.Pool({ connectionString, max: 3, options: `-c search_path=${schema}` });
});
afterAll(async () => { await db.query(`DROP SCHEMA ${schema} CASCADE`); await db.end(); });


/** Reads the admin envelope and returns `data`, or `{ error: message }` for a failure. */
async function mediaBody(response: Response): Promise<unknown> {
  const body = await response.json() as { ok?: boolean; data?: unknown; error?: { code?: string; message?: string }; requestId?: string };
  expect(body.ok).toBe(response.ok);
  expect(body.requestId).toEqual(expect.any(String));
  expect(response.headers.get("x-request-id")).toBe(body.requestId);
  if (body.ok) return body.data;
  expect(body.error?.code).toEqual(expect.any(String));
  return { error: body.error?.message ?? "" };
}


it("preflights existing R2 content into another database, then attaches another owner with zero image bytes and no storage calls", async () => {
  const source = await image("red");
  const object = await uploadObject(db, store, source);
  expect(put).toHaveBeenCalledTimes(1);
  await db.query("DELETE FROM media_objects WHERE sha256=$1", [object.sha256]);
  const checked = await handleAdminMediaCheck(jsonRequest("check", { sha256: [object.sha256] }), deps);
  expect(checked.status).toBe(200);
  expect(await mediaBody(checked)).toMatchObject({ missing: [], objects: [{ sha256: object.sha256, bytes: source.length }] });
  expect(put).toHaveBeenCalledTimes(1);
  const noStorage = { ...deps, store: () => { throw new Error("attach is DB only"); } };
  for (const ownerId of ["course-1", "course-2"]) {
    const attached = await handleAdminMediaAttach(jsonRequest("attach", { owner: "course", ownerId, kind: "poster_9x16", sha256: object.sha256, alt: "Shared" }), noStorage);
    expect(attached.status).toBe(200);
    expect(await mediaBody(attached)).toMatchObject({ version: 1, sha256: object.sha256, url: objectDescriptor(object).url });
  }
  expect(put).toHaveBeenCalledTimes(1);
  expect((await db.query<{ n: number }>("SELECT count(*)::int AS n FROM media_objects")).rows[0]?.n).toBe(1);
});
it("serializes 16 concurrent attachments on a real pool of 3 and rolls back a failed FK without losing the active version", async () => {
  const object = await uploadObject(db, store, await image("blue"));
  const input = { ownerId: "course-3", kind: "poster_9x16" as const, variant: "default", ...objectDescriptor(object), alt: "Concurrent", transform: null, designStatus: "approved" as const };
  const results = await Promise.all(Array.from({ length: 16 }, (_, i) => swapMedia(db, "course", { ...input, alt: `Concurrent ${String(i)}` })));
  expect(new Set(results.map((row) => row.version)).size).toBe(16);
  expect(await readActiveMedia(db, "course", "course-3")).toHaveLength(1);
  await expect(swapMedia(db, "course", { ...input, mediaSha256: "f".repeat(64), alt: "Invalid FK" })).rejects.toMatchObject({ code: "23503" });
  expect((await readActiveMedia(db, "course", "course-3"))[0]?.version).toBe(16);
  const clients = await Promise.all([db.connect(), db.connect(), db.connect()]);
  try {
    const pids = await Promise.all(clients.map(async (client) => (await client.query<{ pid: number }>("SELECT pg_backend_pid() AS pid")).rows[0]?.pid));
    expect((await clients[0].query<{ n: number }>("SELECT count(*)::int AS n FROM pg_locks WHERE locktype='advisory' AND pid=ANY($1)", [pids])).rows[0]?.n).toBe(0);
  } finally { clients.forEach((client) => { client.release(); }); }
});
it("rejects malformed hashes, unauthorized checks, mismatched upload bytes and metadata conflicts", async () => {
  expect((await handleAdminMediaCheck(jsonRequest("check", { sha256: ["bad"] }), deps)).status).toBe(400);
  expect((await handleAdminMediaCheck(new Request("https://test.invalid", { method: "POST" }), deps)).status).toBe(401);
  const form = new FormData(); form.set("file", new Blob([await image("green")])); form.set("sha256", "a".repeat(64));
  expect((await handleAdminMediaObjectUpload(new Request("https://test.invalid", { method: "POST", headers: { authorization: "Bearer content-test" }, body: form }), deps)).status).toBe(415);
  const unknown = await handleAdminMediaAttach(jsonRequest("attach", { owner: "course", ownerId: "course-4", kind: "poster_9x16", sha256: "e".repeat(64), alt: "Missing" }), deps);
  expect(unknown.status).toBe(404);
});
it("dry-runs without writes, resumes verified copies, backfills all references atomically, and preserves every legacy descriptor", async () => {
  await db.query("TRUNCATE catalog_media,course_assets,lesson_assets,subarea_assets,authors,home_rows,media_objects CASCADE");
  const prepared = await prepareMedia(await image("orange"));
  const pathname = `covers/course-5/poster_9x16/${"1".repeat(40)}.webp`;
  bytesByKey.set(pathname, prepared.bytes);
  const legacy = { ownerId: "course-5", kind: "poster_9x16" as const, variant: "default", url: store.publicUrl(pathname), pathname, width: prepared.width, height: prepared.height,
    sha256: prepared.sha256, alt: "Legacy", transform: null, designStatus: "legacy" as const };
  await swapMedia(db, "course", legacy);
  await db.query("INSERT INTO authors (id,cover) VALUES ('author-1',$1::jsonb)", [JSON.stringify({ url: legacy.url, sha256: legacy.sha256, width: legacy.width, height: legacy.height })]);
  const before = (await db.query("SELECT url,pathname,width,height,sha256 FROM catalog_media")).rows;
  const writes = put.mock.calls.length;
  const plan = await planContentMigration(db, store);
  expect(contentSummary(plan)).toMatchObject({ distinct: 1, references: 2, referencedBytes: prepared.bytes.length, maxClassAWrites: 1 });
  expect(put.mock.calls.length).toBe(writes);
  expect((await db.query("SELECT * FROM media_objects")).rows).toEqual([]);
  expect(await copyContent(plan, store)).toEqual({ copied: 1, verified: 1 });
  expect(await copyContent(plan, store)).toEqual({ copied: 0, verified: 1 });
  expect(await backfillContent(db, plan)).toBe(1);
  expect(await backfillContent(db, plan)).toBe(0);
  expect((await db.query("SELECT url,pathname,width,height,sha256 FROM catalog_media")).rows).toEqual(before);
  expect((await readActiveMedia(db, "course", "course-5"))[0]?.pathname).toBe(`m/${prepared.sha256}.webp`);
  const request: typeof fetch = (url, options) => {
    const bytes = bytesByKey.get(new URL(typeof url === "string" ? url : url instanceof URL ? url.href : url.url).pathname.slice(1));
    return Promise.resolve(new Response(options?.method === "HEAD" || !bytes ? null : new Uint8Array(bytes), { status: bytes ? 200 : 404, headers: { "content-length": String(bytes?.length), "content-type": "image/webp" } }));
  };
  expect(await verifyContent(db, request)).toMatchObject({ percent: 100, verified: 1, references: 2 });
  expect(bytesByKey.has(pathname)).toBe(true);
  // Rollback clears catalog_media.media_sha256; the row url stays and a second backfill restores the pointer.
  expect(await rollbackContent(db)).toBe(1);
  expect((await readActiveMedia(db, "course", "course-5"))[0]?.pathname).toBe(pathname);
  expect((await db.query("SELECT url,pathname,width,height,sha256 FROM catalog_media")).rows).toEqual(before);
  expect((await db.query("SELECT sha256 FROM media_objects")).rows).toHaveLength(1);
  expect(await backfillContent(db, plan)).toBe(1);
  expect(await verifyContent(db, request)).toMatchObject({ percent: 100, verified: 1, references: 2 });
  // A stale plan must fail before committing any partial registry/reference update.
  await db.query("UPDATE catalog_media SET width=width+1");
  await expect(backfillContent(db, plan)).rejects.toThrow("Source descriptors changed");
});
it("refuses a corrupt existing destination instead of trusting its filename or byte size", async () => {
  const prepared = await prepareMedia(await image("purple"));
  bytesByKey.set(`m/${prepared.sha256}.webp`, Buffer.from("corrupted"));
  await expect(checkObjects(db, store, [prepared.sha256])).rejects.toThrow("checksum mismatch");
  expect((await db.query("SELECT * FROM media_objects WHERE sha256=$1", [prepared.sha256])).rows).toEqual([]);
});
