import { afterAll, beforeAll, beforeEach, expect, it, vi } from "vitest";
vi.mock("server-only", () => ({}));
import { call, coverInput, createHarness, revisionOf, seedCatalog, seedDraftCourse, type Harness, type Seed } from "../fixtures/admin-catalog.ts";
import { readActiveMedia, rollbackMedia, swapMedia } from "../../src/media/server/repository.ts";
import { coverGraph, inheritedSources, pruneInherited } from "../../src/media/server/inheritance.ts";
import { resolveCover } from "../../src/catalog/domain/cover-resolve.ts";
import { activeCoverKinds } from "../../src/catalog/server/cover-kinds.ts";
import { REQUIRED_COVERS } from "../../src/catalog/domain/rules/status.ts";
import { createAdminRateLimiter, handleAdminMediaList, handleAdminMediaPruneInherited, handleAdminMediaRollback, handleAdminMediaUpload, type AdminMediaDeps } from "../../src/media/server/admin.ts";
import { catalogCourseOf, catalogOwners } from "../../src/catalog/server/media-owners.ts";
import sharp from "sharp";

function required<T>(value: T | undefined): T {
  if (value === undefined) throw new Error("Missing inheritance test fixture");
  return value;
}
let h: Harness; let seed: Seed;
beforeAll(() => { h = createHarness(); });
afterAll(async () => { await h.close(); });
beforeEach(async () => { seed = await seedCatalog(h); });
function mediaDeps() {
  const invalidate = vi.fn<AdminMediaDeps["invalidate"]>();
  return { secret: "inheritance-test-secret", limiter: createAdminRateLimiter(), db: () => h.pool, store: () => h.store, courseOf: catalogCourseOf(() => h.pool), owners: catalogOwners, invalidate };
}
const mediaRequest = (path: string, body: unknown, method = "POST") => new Request(`https://test.invalid/api/admin/media${path}`, {
  method, headers: { authorization: "Bearer inheritance-test-secret", "content-type": "application/json" }, body: JSON.stringify(body),
});
async function sharedCourse() {
  const draft = await seedDraftCourse(h, seed, "inherited");
  const subarea = required((await h.pool.query<{ id: string; area_id: string }>("SELECT id, area_id FROM subject_subareas ORDER BY id LIMIT 1")).rows[0]);
  await h.pool.query("DELETE FROM catalog_media WHERE owner_kind='course' AND owner_id=$1", [draft.id]);
  const patched = await call(h, "PATCH", `/courses/${draft.id}`, { body: { expectedRevision: await revisionOf(h, "courses", draft.id), areaId: subarea.area_id, subareaId: subarea.id, coverFrom: `subarea:${subarea.id}` } });
  expect(patched.status).toBe(200);
  for (const kind of [...REQUIRED_COVERS, "og", "lesson_default"] as const) await swapMedia(h.pool, "subarea", coverInput("subarea", subarea.id, kind));
  return { ...draft, subarea };
}

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


it("versions shared covers, rolls back and enforces one active version in PostgreSQL", async () => {
  const course = await sharedCourse();
  const original = required((await readActiveMedia(h.pool, "subarea", course.subarea.id)).find((asset) => asset.kind === "lesson_default"));
  const second = await swapMedia(h.pool, "subarea", { ...coverInput("subarea", course.subarea.id, "lesson_default", "second"), alt: "Second" });
  expect(second.version).toBe(2);
  await expect(h.pool.query("UPDATE catalog_media SET is_active=true WHERE id=$1", [original.id])).rejects.toMatchObject({ code: "23505" });
  expect((await rollbackMedia(h.pool, "subarea", course.subarea.id, "lesson_default", "default", 1)).id).toBe(original.id);
});
it("approves and publishes a provisional course with zero own cover rows, refusing inheritance when unmarked", async () => {
  const course = await sharedCourse();
  const detail = await call(h, "GET", `/courses/${course.id}`);
  expect(detail.data.preconditions).toMatchObject({ review: [] });
  const review = await call(h, "POST", `/courses/${course.id}/status`, { body: { expectedRevision: await revisionOf(h, "courses", course.id), to: "review" } });
  expect(review.status).toBe(200);
  const published = await call(h, "POST", `/courses/${course.id}/publish`, { key: "inherit-publish", body: { expectedRevision: await revisionOf(h, "courses", course.id), allowOrphan: true, note: "inheritance acceptance" } });
  expect(published.status).toBe(200);
  expect(await readActiveMedia(h.pool, "course", course.id)).toEqual([]);
  expect(await readActiveMedia(h.pool, "lesson", required(course.lessons[0]))).toEqual([]);
  const graph = await coverGraph(h.pool, await catalogOwners(h.pool).graph());
  const row = required(graph.courses.find((row) => row.id === course.id));
  expect(resolveCover(inheritedSources(graph, row), { target: "lesson" })?.ownerId).toBe(course.subarea.id);
  const refused = await call(h, "PATCH", `/courses/${course.id}`, { body: { expectedRevision: await revisionOf(h, "courses", course.id), coverFrom: "own" } });
  expect(refused.status).toBe(412);
});
it("prunes only equal default 16:9 versions, reports complete rows and actual course ids, and is idempotent", async () => {
  const course = await sharedCourse();
  const inherited = required((await readActiveMedia(h.pool, "subarea", course.subarea.id)).find((asset) => asset.kind === "lesson_default"));
  const duplicate = { ...coverInput("lesson", required(course.lessons[0]), "cover_16x9"), sha256: inherited.sha256 };
  await swapMedia(h.pool, "lesson", duplicate);
  await swapMedia(h.pool, "lesson", { ...duplicate, alt: "New version" });
  await swapMedia(h.pool, "lesson", { ...duplicate, variant: "alternate" });
  await swapMedia(h.pool, "lesson", coverInput("lesson", required(course.lessons[1]), "cover_16x9"));
  const plan = await pruneInherited(h.pool, false, catalogOwners);
  expect(plan).toMatchObject({ apply: false, count: 2, bytesDeleted: 0, courseIds: [course.id] });
  expect(plan.candidates[0]?.asset).toMatchObject({ pathname: duplicate.pathname, sha256: inherited.sha256, version: 2 });
  expect((await readActiveMedia(h.pool, "lesson", required(course.lessons[0])))).toHaveLength(2);
  expect((await pruneInherited(h.pool, true, catalogOwners)).count).toBe(plan.count);
  expect((await readActiveMedia(h.pool, "lesson", required(course.lessons[0]))).map((asset) => asset.variant)).toEqual(["alternate"]);
  expect((await readActiveMedia(h.pool, "lesson", required(course.lessons[1])))).toHaveLength(1);
  expect((await pruneInherited(h.pool, true, catalogOwners)).count).toBe(0);
  const doctor = await call(h, "GET", "/doctor");
  expect(doctor.status).toBe(200);
  expect((doctor.data.findings as { code: string }[]).some((finding) => finding.code === "media.lesson.redundant")).toBe(false);
});

it("uploads, lists and rolls back shared covers through the API with directed invalidation", async () => {
  const course = await sharedCourse();
  await h.pool.query("UPDATE courses SET area_id=$2, subarea_id=$3 WHERE id=$1", [seed.courses.alpha, course.subarea.area_id, course.subarea.id]);
  const deps = mediaDeps();
  const form = new FormData();
  for (const [key, value] of Object.entries({ owner: "subarea", ownerId: course.subarea.id, kind: "lesson_default", alt: "New shared cover" })) form.set(key, value);
  const bytes = await sharp({ create: { width: 32, height: 18, channels: 3, background: "#abcdef" } }).png().toBuffer();
  form.set("file", new Blob([new Uint8Array(bytes)]), "shared.png");
  const uploaded = await handleAdminMediaUpload(new Request("https://test.invalid/api/admin/media", { method: "POST", headers: { authorization: "Bearer inheritance-test-secret" }, body: form }), deps);
  expect(uploaded.status).toBe(200);
  expect(deps.invalidate).toHaveBeenLastCalledWith({ tags: [`media:subarea:${course.subarea.id}`, `media:course:${seed.courses.alpha}`], paths: [] });
  const listed = await handleAdminMediaList(new Request(`https://test.invalid/api/admin/media?owner=subarea&ownerId=${course.subarea.id}`, { headers: { authorization: "Bearer inheritance-test-secret" } }), deps);
  expect(listed.status).toBe(200);
  expect((await mediaBody(listed) as { versions: unknown[] }).versions).toHaveLength(7);
  const rolled = await handleAdminMediaRollback(mediaRequest("/rollback", { owner: "subarea", ownerId: course.subarea.id, kind: "lesson_default", version: 1 }), deps);
  expect(rolled.status).toBe(200);
  expect((await readActiveMedia(h.pool, "subarea", course.subarea.id)).find((asset) => asset.kind === "lesson_default")?.version).toBe(1);
});

it("protects the prune endpoint, keeps bytes and invalidates actual affected course ids after commit", async () => {
  const course = await sharedCourse(); const deps = mediaDeps();
  const inherited = required((await readActiveMedia(h.pool, "subarea", course.subarea.id)).find((asset) => asset.kind === "lesson_default"));
  await swapMedia(h.pool, "lesson", { ...coverInput("lesson", required(course.lessons[0]), "cover_16x9"), sha256: inherited.sha256 });
  expect((await handleAdminMediaPruneInherited(new Request("https://test.invalid", { method: "POST", body: "{}" }), deps)).status).toBe(401);
  expect((await handleAdminMediaPruneInherited(mediaRequest("/prune-inherited", { apply: "yes" }), deps)).status).toBe(400);
  const dry = await handleAdminMediaPruneInherited(mediaRequest("/prune-inherited", {}), deps);
  expect(await mediaBody(dry)).toMatchObject({ apply: false, count: 1, bytesDeleted: 0 });
  expect(deps.invalidate).not.toHaveBeenCalled();
  const applied = await handleAdminMediaPruneInherited(mediaRequest("/prune-inherited", { apply: true }), deps);
  expect(await mediaBody(applied)).toMatchObject({ apply: true, count: 1, courseIds: [course.id], bytesDeleted: 0 });
  expect(deps.invalidate).toHaveBeenCalledWith({ tags: [`media:course:${course.id}`], paths: [] });
  expect(h.store.deleted).toEqual([]);
});

it("D-015/INV-M5: readiness and doctor inherit area covers without a subarea", async () => {
  const draft = await seedDraftCourse(h, seed, "area-inherited");
  const area = required((await h.pool.query<{ id: string }>("SELECT id FROM subject_areas ORDER BY id LIMIT 1")).rows[0]);
  await h.pool.query("DELETE FROM catalog_media WHERE owner_kind='course' AND owner_id=$1", [draft.id]);
  for (const kind of [...REQUIRED_COVERS, "lesson_default"] as const) await swapMedia(h.pool, "area", coverInput("area", area.id, kind));
  const patched = await call(h, "PATCH", `/courses/${draft.id}`, { body: { expectedRevision: await revisionOf(h, "courses", draft.id), areaId: area.id, subareaId: null, coverFrom: `area:${area.id}` } });
  expect(patched.status).toBe(200);
  expect([...(await activeCoverKinds(h.pool, [draft.id])).get(draft.id) ?? []]).toEqual([...REQUIRED_COVERS]);
  const graph = await coverGraph(h.pool, await catalogOwners(h.pool).graph());
  const row = required(graph.courses.find((entry) => entry.id === draft.id));
  expect(resolveCover(inheritedSources(graph, row), { target: "lesson" })?.ownerId).toBe(area.id);
  expect((await call(h, "POST", `/courses/${draft.id}/status`, { body: { expectedRevision: await revisionOf(h, "courses", draft.id), to: "review" } })).status).toBe(200);
  expect((await call(h, "POST", `/courses/${draft.id}/publish`, { key: "area-inherit-publish", body: { expectedRevision: await revisionOf(h, "courses", draft.id), allowOrphan: true, note: "area inheritance acceptance" } })).status).toBe(200);
  const refused = await call(h, "PATCH", `/courses/${draft.id}`, { body: { expectedRevision: await revisionOf(h, "courses", draft.id), coverFrom: "own" } });
  expect(refused.status).toBe(412);
});
