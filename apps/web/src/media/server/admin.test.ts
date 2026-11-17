import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import sharp from "sharp";
import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
vi.mock("node:crypto", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:crypto")>();
  return { ...actual, timingSafeEqual: vi.fn(actual.timingSafeEqual) };
});
import { ADMIN_MEDIA_MAX_BYTES, createAdminRateLimiter, handleAdminMediaDelete, handleAdminMediaList, handleAdminMediaRollback, handleAdminMediaUpload, type AdminMediaDeps } from "./admin.ts";
import type { MediaDatabase, MediaPool } from "./repository.ts";
import { createFsMediaStore } from "./fs-store.ts";
import { type MediaObjectStore } from "./storage.ts";
import { StorageError } from "./storage-error.ts";
import { MEDIA_PUBLIC_HOST } from "../domain/types.ts";

const secret = "test-admin-secret";
const camel: Record<string, string> = { owner_id: "ownerId", course_id: "ownerId", lesson_id: "ownerId", owner_kind: "ownerKind", design_status: "designStatus", is_active: "isActive", created_at: "createdAt", media_sha256: "mediaSha256", updated_at: "updatedAt" };
const insertColumns = ["id", "owner_kind", "owner_id", "kind", "variant", "url", "pathname", "width", "height", "sha256", "alt", "transform", "design_status", "version", "media_sha256"];

/** Minimal in-memory stand-in for the repository's SQL (PostgreSQL behaviour is covered by test/int/media.int.test.ts). */
function memoryDatabase(): MediaPool & { rows: Record<string, unknown>[] } {
  const rows: Record<string, unknown>[] = [];
  const objects = new Map<string, Record<string, unknown>>();
  let snapshot: Record<string, unknown>[] = [];
  const project = (row: Record<string, unknown>) => Object.fromEntries(Object.entries(row).filter(([key]) => key !== "table").map(([key, value]) => [camel[key] ?? key, key === "transform" ? JSON.parse(value as string) as unknown : value]));
  const matching = (sql: string, values: unknown[]) => {
    const names = [...sql.matchAll(/(?:FROM|UPDATE|INTO) (\w+)/g)].map((match) => match[1] ?? "");
    const table = names.find((name) => name === "catalog_media") ?? names.at(-1);
    const where = sql.slice(sql.lastIndexOf("WHERE") + 5).split(/ORDER BY|RETURNING/)[0] ?? "";
    const conditions = where.split("AND").map((part) => part.trim().replace(/\ba\./g, ""));
    return rows.filter((row) => row.table === table && conditions.every((condition) => {
      if (condition === "is_active") return row.is_active === true;
      const literal = /^(\w+)='([^']*)'$/.exec(condition);
      if (literal) return row[literal[1] ?? ""] === literal[2];
      const list = /^(\w+)(=ANY|<>ALL)\(\$(\d)\)$/.exec(condition);
      if (list) { const found = (values[Number(list[3]) - 1] as unknown[]).includes(row[list[1] ?? ""]); return list[2] === "=ANY" ? found : !found; }
      const [column, index] = condition.split("=$");
      return row[column ?? ""] === values[Number(index) - 1];
    }));
  };
  const query: MediaDatabase["query"] = async (sql, values = []) => {
    await Promise.resolve();
    if (sql.startsWith("INSERT INTO media_objects")) {
      const [sha256, ext, contentType, bytes, width, height] = values;
      if (!objects.has(String(sha256))) objects.set(String(sha256), { sha256, ext, contentType, bytes, width, height });
      return { rows: [] };
    }
    if (sql.includes("FROM media_objects WHERE sha256=ANY")) return { rows: (values[0] as string[]).flatMap((hash) => objects.has(hash) ? [objects.get(hash) as Record<string, unknown>] : []) };
    // BEGIN snapshots and ROLLBACK restores, so failed transactions leave the rows as they were.
    if (sql === "BEGIN") snapshot = rows.map((row) => ({ ...row }));
    if (sql === "ROLLBACK") rows.splice(0, rows.length, ...snapshot);
    if (/^(BEGIN|COMMIT|ROLLBACK|SELECT pg_advisory)/.test(sql)) return { rows: [] };
    if (sql.startsWith("INSERT INTO")) {
      const row: Record<string, unknown> = { table: /INSERT INTO (\w+)/.exec(sql)?.[1], is_active: true, created_at: new Date(), updated_at: new Date() };
      insertColumns.forEach((column, i) => { row[column] = values[i]; });
      rows.push(row);
      return { rows: [project(row)] };
    }
    if (sql.includes("MAX(version)")) return { rows: [{ version: Math.max(0, ...matching(sql, values).map((row) => row.version as number)) + 1 }] };
    if (sql.startsWith("DELETE")) { const gone = new Set(matching(sql, values)); rows.splice(0, rows.length, ...rows.filter((row) => !gone.has(row))); return { rows: [] }; }
    if (sql.startsWith("UPDATE")) { const active = sql.includes("is_active=true"); matching(sql, values).forEach((row) => { row.is_active = active; }); return { rows: [] }; }
    return { rows: matching(sql, values).map((row) => project(row)) };
  };
  // One "connection": the transaction helpers check it out and release it.
  return { rows, query, connect: () => Promise.resolve({ query, release() { /* nothing pooled */ } }) };
}

let directory: string;
beforeAll(async () => { directory = await mkdtemp(path.join(tmpdir(), "tower-admin-media-")); });
afterAll(async () => { await rm(directory, { recursive: true, force: true }); });
function deps(overrides: Partial<AdminMediaDeps> = {}): AdminMediaDeps & { tags: string[] } {
  const db = memoryDatabase(); const store = createFsMediaStore(directory, MEDIA_PUBLIC_HOST); const tags: string[] = [];
  // course-1 (lesson-1) is published; course-2 (lesson-2) is a draft.
  const owners: Record<string, { courseId: string; published: boolean }> = { "course:course-1": { courseId: "course-1", published: true }, "lesson:lesson-1": { courseId: "course-1", published: true },
    "course:course-2": { courseId: "course-2", published: false }, "lesson:lesson-2": { courseId: "course-2", published: false } };
  return { secret, limiter: createAdminRateLimiter(), db: () => db, store: () => store, invalidate: (plan) => { tags.push(...plan.tags, ...plan.paths.map((page) => `path:${page}`)); }, tags,
    courseOf: (owner, ownerId) => Promise.resolve(owners[`${owner}:${ownerId}`]),
    owners: () => ({ courseOf: () => Promise.resolve(undefined), graph: () => Promise.resolve({ courses: [], lessons: [] }), lockGraph: () => Promise.resolve(), inventory: () => Promise.resolve([]) }),
    ...overrides };
}
const png = (color: string) => sharp({ create: { width: 32, height: 18, channels: 3, background: color } }).png().toBuffer();
function upload(fields: Record<string, string>, bytes?: Uint8Array, auth = `Bearer ${secret}`, ip = "203.0.113.1") {
  const form = new FormData();
  if (bytes) form.set("file", new Blob([Buffer.from(bytes)]), "cover.png");
  for (const [key, value] of Object.entries(fields)) form.set(key, value);
  return new Request("https://tower.test/api/admin/media", { method: "POST", body: form, headers: { authorization: auth, "x-forwarded-for": ip } });
}
const cover = { owner: "course", ownerId: "course-1", kind: "poster_9x16", alt: "Genesis poster" };


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


describe("admin media auth", () => {
  it("returns 503 without a configured secret and 401 for a wrong token", async () => {
    expect((await handleAdminMediaUpload(upload(cover), deps({ secret: undefined }))).status).toBe(503);
    const response = await handleAdminMediaList(new Request("https://tower.test/api/admin/media", { headers: { authorization: "Bearer wrong" } }), deps());
    expect(response.status).toBe(401);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(await response.text()).not.toContain(secret);
  });
  it("compares tokens with the timing-safe helper", async () => {
    vi.mocked(timingSafeEqual).mockClear();
    expect((await handleAdminMediaList(new Request("https://tower.test/api/admin/media", { headers: { authorization: `Bearer ${secret}x` } }), deps())).status).toBe(401);
    expect(timingSafeEqual).toHaveBeenCalledOnce();
  });
  it("keeps failed-authentication IP limits separate from the authenticated quota", async () => {
    const shared = { ...deps(), limiter: createAdminRateLimiter({ requests: 30, failures: 10, authenticated: 2 }) };
    const call = (auth: string, ip: string) => handleAdminMediaList(new Request("https://tower.test/api/admin/media?owner=course&ownerId=course-9", { headers: { authorization: auth, "x-forwarded-for": ip } }), shared);
    for (let i = 0; i < 10; i += 1) expect((await call("Bearer wrong", "198.51.100.1")).status).toBe(401);
    expect((await call("Bearer wrong", "198.51.100.1")).status).toBe(429);
    expect((await call(`Bearer ${secret}`, "198.51.100.1")).status).toBe(404);
    expect((await call(`Bearer ${secret}`, "198.51.100.2")).status).toBe(404);
    const limited = await call(`Bearer ${secret}`, "198.51.100.2");
    expect(limited.status).toBe(429);
    expect(Number(limited.headers.get("Retry-After"))).toBeGreaterThan(0);
  });
});

describe("admin media validation", () => {
  it("rejects kinds that don't belong to the owner and unknown owners", async () => {
    const bytes = await png("#203040");
    expect((await handleAdminMediaUpload(upload({ ...cover, kind: "cover_16x9" }, bytes), deps())).status).toBe(400);
    expect((await handleAdminMediaUpload(upload({ ...cover, ownerId: "course-9" }, bytes), deps())).status).toBe(404);
    expect((await handleAdminMediaUpload(upload({ ...cover, owner: "lesson", ownerId: "lesson-9", kind: "cover_9x16" }, bytes), deps())).status).toBe(404);
    expect((await handleAdminMediaUpload(upload(cover, new TextEncoder().encode("not an image")), deps())).status).toBe(415);
  });
  it("rejects files above 4 MB with 413", async () => {
    const response = await handleAdminMediaUpload(upload(cover, new Uint8Array(ADMIN_MEDIA_MAX_BYTES + 1)), deps());
    expect(response.status).toBe(413);
    expect(((await mediaBody(response)) as { error: string }).error).toMatch(/4 MB/);
  });
  it("refuses assets over their kind's byte budget with 413 unless forceOversize=1", async () => {
    // Random noise does not compress: a ~270 KB PNG against the 120 KiB poster budget.
    const noise = await sharp(randomBytes(300 * 300 * 3), { raw: { width: 300, height: 300, channels: 3 } }).png().toBuffer();
    const env = deps();
    const refused = await handleAdminMediaUpload(upload(cover, noise), env);
    expect(refused.status).toBe(413);
    expect(((await mediaBody(refused)) as { error: string }).error).toMatch(/^poster_9x16 is \d+ KiB, over its 120 KiB budget\..*--force-oversize/);
    expect(env.tags).toEqual([]);
    const forced = await handleAdminMediaUpload(upload({ ...cover, forceOversize: "1" }, noise), env);
    expect(forced.status).toBe(200);
  });
  it("stores a bare, pre-optimized WebP byte for byte", async () => {
    const webp = await sharp({ create: { width: 54, height: 96, channels: 3, background: "#808890" } }).webp({ quality: 78 }).toBuffer();
    const response = await handleAdminMediaUpload(upload(cover, webp), deps());
    const saved = (await mediaBody(response)) as { url: string; sha256: string };
    expect(saved.url).toMatch(/\.webp$/);
    expect(saved.sha256).toBe(createHash("sha256").update(webp).digest("hex"));
  });
});

describe("admin media invalidation (src/media/domain/tags.ts)", () => {
  it("expires nothing for a draft course, whatever the kind or the operation", async () => {
    const env = deps();
    for (const fields of [{ owner: "course", ownerId: "course-2", kind: "poster_9x16" }, { owner: "lesson", ownerId: "lesson-2", kind: "cover_16x9" }]) {
      expect((await handleAdminMediaUpload(upload({ ...fields, alt: "Draft cover" }, await png("#102030")), env)).status).toBe(200);
      expect((await handleAdminMediaUpload(upload({ ...fields, alt: "Draft cover" }, await png("#203040")), env)).status).toBe(200);
      const rollback = new Request("https://example.invalid/api/admin/media/rollback", { method: "POST", headers: { authorization: `Bearer ${secret}`, "x-forwarded-for": "203.0.113.1" }, body: JSON.stringify({ ...fields, version: 1 }) });
      expect((await handleAdminMediaRollback(rollback, env)).status).toBe(200);
      const remove = new Request("https://example.invalid/api/admin/media", { method: "DELETE", headers: { authorization: `Bearer ${secret}`, "x-forwarded-for": "203.0.113.1" }, body: JSON.stringify({ ...fields, version: 2, apply: true }) });
      expect((await handleAdminMediaDelete(remove, env)).status).toBe(200);
    }
    expect(env.tags).toEqual([]);
  });
  it("expires a published course's tag, the course-list read for a course asset", async () => {
    const env = deps();
    expect((await handleAdminMediaUpload(upload({ owner: "course", ownerId: "course-1", kind: "poster_9x16", alt: "Poster" }, await png("#304050")), env)).status).toBe(200);
    expect(env.tags).toEqual(["media:course:course-1", "media:courses"]);
    expect(env.tags).not.toContain("media");
  });
});

describe("admin media swap and rollback", () => {
  it("uploads idempotently, versions changes, lists and rolls back without deleting", async () => {
    const env = deps();
    const first = await png("#112233");
    const lesson = { owner: "lesson", ownerId: "lesson-1", kind: "cover_9x16", alt: "Vertical lesson cover" };
    const one = await handleAdminMediaUpload(upload(lesson, first), env);
    expect(one.status).toBe(200);
    const saved = (await mediaBody(one)) as { version: number; url: string; width: number; sha256: string; kind: string };
    expect(saved).toMatchObject({ version: 1, kind: "cover_9x16", width: 32 });
    expect(saved.url).toMatch(new RegExp(`^https://${MEDIA_PUBLIC_HOST}/m/[a-f0-9]{64}\\.png$`));
    // A lesson cover of a published course expires that course's lesson covers only: no global tag, no page path.
    expect(env.tags).toEqual(["media:course:course-1"]);
    expect(((await mediaBody(await handleAdminMediaUpload(upload(lesson, first), env))) as { version: number }).version).toBe(1);
    expect(((await mediaBody(await handleAdminMediaUpload(upload(lesson, await png("#445566")), env))) as { version: number }).version).toBe(2);

    const auth = { authorization: `Bearer ${secret}` };
    const list = (await mediaBody(await handleAdminMediaList(new Request("https://tower.test/api/admin/media?owner=lesson&ownerId=lesson-1&kind=cover_9x16", { headers: auth }), env))) as { versions: { version: number; active: boolean }[] };
    expect(list.versions.map(({ version, active }) => [version, active]).sort()).toEqual([[1, false], [2, true]]);

    const rollback = (body: unknown) => handleAdminMediaRollback(new Request("https://tower.test/api/admin/media/rollback", { method: "POST", headers: auth, body: JSON.stringify(body) }), env);
    expect((await rollback({ owner: "lesson", ownerId: "lesson-1", kind: "cover_9x16", version: 7 })).status).toBe(404);
    const restored = await rollback({ owner: "lesson", ownerId: "lesson-1", kind: "cover_9x16", version: 1 });
    expect(((await mediaBody(restored)) as { version: number; sha256: string }).sha256).toBe(saved.sha256);
    const inventory = (await mediaBody(await handleAdminMediaList(new Request("https://tower.test/api/admin/media", { headers: auth }), env))) as { assets: { version: number }[] };
    expect(inventory.assets.map((asset) => asset.version)).toEqual([1]);
    expect((env.db() as ReturnType<typeof memoryDatabase>).rows).toHaveLength(2);
  });
});

describe("admin media delete", () => {
  const auth = { authorization: `Bearer ${secret}` };
  const lesson = { owner: "lesson", ownerId: "lesson-1", kind: "cover_16x9", alt: "Genesis lecture cover" };
  const target = { owner: "lesson", ownerId: "lesson-1", kind: "cover_16x9" };
  const remove = (env: AdminMediaDeps, body: unknown, authorization = auth.authorization) =>
    handleAdminMediaDelete(new Request("https://tower.test/api/admin/media", { method: "DELETE", headers: { authorization }, body: JSON.stringify(body) }), env);
  type Result = { dryRun: boolean; plan?: { version: number; active: boolean; key: string; willDeleteBytes: boolean }[]; deleted?: { version: number; variant: string }[];
    bytes?: { deleted: string[]; kept: { key: string; reason: string }[] }; activeAfter: { version: number } | null; alreadyAbsent?: boolean };
  /** default variant: v1 (red, inactive) and v2 (blue, active); returns the env and the stored keys. */
  async function seeded(overrides: Partial<AdminMediaDeps> = {}) {
    const env = deps(overrides);
    const keys: string[] = [];
    for (const color of ["#aa0000", "#0000aa"]) keys.push(((await mediaBody(await handleAdminMediaUpload(upload(lesson, await png(color)), env))) as { url: string }).url.split("/").slice(3).join("/"));
    const database = env.db() as ReturnType<typeof memoryDatabase>;
    for (const [i, row] of database.rows.entries()) {
      const legacy = `covers/lesson-1/cover_9x16/${String(row.sha256).slice(0, 40)}.png`;
      const bytes = await env.store().get(String(row.pathname));
      if (!bytes) throw new Error("Missing deletion fixture bytes");
      await env.store().put(legacy, bytes);
      row.pathname = legacy; row.url = `https://${MEDIA_PUBLIC_HOST}/${legacy}`; row.media_sha256 = null;
      keys[i] = legacy;
    }
    env.tags.length = 0;
    return { env, keys, rows: (env.db() as ReturnType<typeof memoryDatabase>).rows, store: env.store() };
  }

  it("needs the Bearer secret (503 unset, 401 missing or wrong) and never echoes it", async () => {
    expect((await remove(deps({ secret: undefined }), target)).status).toBe(503);
    expect((await remove(deps(), target, "")).status).toBe(401);
    const wrong = await remove(deps(), target, "Bearer wrong");
    expect(wrong.status).toBe(401);
    expect(wrong.headers.get("cache-control")).toBe("no-store");
    expect(await wrong.text()).not.toContain(secret);
    expect((await remove(deps(), { ...target, version: 1, unknown: true })).status).toBe(400);
  });
  it("lists inactive versions in the full inventory with all=1", async () => {
    const { env } = await seeded();
    const list = (all: string) => handleAdminMediaList(new Request(`https://tower.test/api/admin/media${all}`, { headers: auth }), env).then(async (response) => ((await mediaBody(response)) as { assets: { version: number; active?: boolean }[] }).assets);
    expect((await list("")).map((asset) => asset.version)).toEqual([2]);
    expect((await list("?all=1")).map(({ version, active }) => [version, active]).sort()).toEqual([[1, false], [2, true]]);
  });
  it("plans without changing anything by default", async () => {
    const { env, keys, rows, store } = await seeded();
    const response = await remove(env, { ...target, version: 1 });
    expect(response.status).toBe(200);
    expect(await mediaBody(response)).toMatchObject({ dryRun: true, plan: [{ version: 1, active: false, key: keys[0], willDeleteBytes: true }], activeAfter: { version: 2 } });
    expect(rows).toHaveLength(2);
    expect(await store.head(keys[0] ?? "")).not.toBeNull();
    expect(env.tags).toEqual([]);
  });
  it("refuses the active version and the whole default variant with 409", async () => {
    const { env, rows } = await seeded();
    expect((await remove(env, { ...target, version: 2, apply: true })).status).toBe(409);
    expect((await remove(env, { ...target, apply: true })).status).toBe(409);
    expect(rows).toHaveLength(2);
    expect(env.tags).toEqual([]);
  });
  it("deletes an inactive version and its bytes, then answers alreadyAbsent idempotently", async () => {
    const { env, keys, rows, store } = await seeded();
    const result = (await mediaBody(await remove(env, { ...target, version: 1, apply: true }))) as Result;
    expect(result).toMatchObject({ dryRun: false, deleted: [{ version: 1, variant: "default" }], bytes: { deleted: [keys[0]], kept: [] }, activeAfter: { version: 2 } });
    expect(rows.map((row) => row.version)).toEqual([2]);
    expect(await store.head(keys[0] ?? "")).toBeNull();
    expect(await store.head(keys[1] ?? "")).not.toBeNull();
    expect(env.tags).toEqual(["media:course:course-1"]);
    const again = await remove(env, { ...target, version: 1, apply: true });
    expect(again.status).toBe(200);
    expect(await mediaBody(again)).toMatchObject({ deleted: [], alreadyAbsent: true });
    expect(env.tags).toHaveLength(1);
  });
  it("keeps bytes another row uses or when keepBytes is set", async () => {
    const { env, keys, rows, store } = await seeded();
    // The same bytes as an active non-default variant: same immutable key.
    await handleAdminMediaUpload(upload({ ...lesson, variant: "rollback-test" }, await png("#aa0000")), env);
    const attached = (env.db() as ReturnType<typeof memoryDatabase>).rows.at(-1);
    if (!attached) throw new Error("Missing shared legacy fixture");
    attached.pathname = keys[0]; attached.url = `https://${MEDIA_PUBLIC_HOST}/${keys[0] ?? ""}`; attached.media_sha256 = null;
    const shared = (await mediaBody(await remove(env, { ...target, version: 1, apply: true }))) as Result;
    expect(shared.bytes).toEqual({ deleted: [], kept: [{ key: keys[0], reason: expect.stringMatching(/another row/) as string }] });
    expect(await store.head(keys[0] ?? "")).not.toBeNull();
    const kept = (await mediaBody(await remove(env, { ...target, variant: "rollback-test", apply: true, keepBytes: true }))) as Result;
    expect(kept).toMatchObject({ deleted: [{ version: 1, variant: "rollback-test" }], bytes: { deleted: [], kept: [{ key: keys[0], reason: "keepBytes requested" }] }, activeAfter: null });
    expect(await store.head(keys[0] ?? "")).not.toBeNull();
    expect(rows.map((row) => row.variant)).toEqual(["default"]);
  });
  it("deletes a whole non-default variant, active version included, only with apply", async () => {
    const { env, rows, store } = await seeded();
    const variant = { ...lesson, variant: "rollback-test" };
    await handleAdminMediaUpload(upload(variant, await png("#00aa00")), env);
    const latest = ((await mediaBody(await handleAdminMediaUpload(upload(variant, await png("#00aaaa")), env))) as { url: string }).url.split("/").slice(3).join("/");
    const plan = (await mediaBody(await remove(env, { ...target, variant: "rollback-test" }))) as Result;
    expect(plan.plan?.map(({ version, active }) => [version, active]).sort()).toEqual([[1, false], [2, true]]);
    expect(rows).toHaveLength(4);
    const done = (await mediaBody(await remove(env, { ...target, variant: "rollback-test", apply: true }))) as Result;
    expect(done.deleted?.map((row) => row.version).sort()).toEqual([1, 2]);
    expect(done.bytes?.deleted).toHaveLength(0);
    expect(done.bytes?.kept).toHaveLength(2);
    expect(done.activeAfter).toBeNull();
    expect(await store.head(latest)).not.toBeNull();
    expect(rows.every((row) => row.variant === "default")).toBe(true);
  });
  it("restores the rows when R2 fails (502) so re-running is safe", async () => {
    const { env, keys, rows } = await seeded();
    const store = env.store();
    const broken: MediaObjectStore = { ...store, delete: () => Promise.reject(new StorageError("R2 DELETE failed with HTTP 500.")) };
    const response = await remove({ ...env, store: () => broken }, { ...target, version: 1, apply: true });
    expect(response.status).toBe(502);
    expect(((await mediaBody(response)) as { error: string }).error).toMatch(/Re-run/);
    expect(rows).toHaveLength(2);
    expect(env.tags).toEqual([]);
    expect(((await mediaBody(await remove(env, { ...target, version: 1, apply: true }))) as Result).bytes?.deleted).toEqual([keys[0]]);
  });
});

// The concrete classes remain available to existing CLI and API instanceof branches.
it("classifies all four media errors with the shared root and preserved HTTP status", async () => {
  const { AppError } = await import("../../kernel/errors.ts");
  const { MediaInputError } = await import("./prepare.ts");
  const { MediaBudgetError } = await import("../domain/budget.ts");
  const { MediaConflictError } = await import("./repository.ts");
  for (const [error, status] of [[new MediaInputError("image"), 415], [new MediaBudgetError("size"), 413], [new MediaConflictError("active"), 409], [new StorageError("upstream"), 502]] as const) {
    expect(error).toBeInstanceOf(AppError);
    expect(error.status).toBe(status);
  }
});
