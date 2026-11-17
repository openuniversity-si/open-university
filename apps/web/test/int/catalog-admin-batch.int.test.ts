import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { activeRelease, auditRows, call, createHarness, revisionOf, seedCatalog, seedDraftCourse, type Harness, type Seed } from "../fixtures/admin-catalog.ts";

// POST /courses/publish-batch (docs/catalog/admin-api.md): many courses, ONE release, all or nothing, one-step rollback.
interface BatchData { release: { number: number; created: boolean }; previous: number | null; courses: { id: string; from: string }[]; diff: { courses: { added: string[] } } }

describe("admin catalog: batch publish", () => {
  let h: Harness;
  let seed: Seed;
  let n = 0;
  const key = () => { n += 1; return `batch-${String(n)}`; };
  beforeAll(() => { h = createHarness(); });
  afterAll(async () => { await h.close(); });
  beforeEach(async () => { seed = await seedCatalog(h); }, 60_000);

  async function reviewCourses(count: number, prefix: string): Promise<string[]> {
    const ids: string[] = [];
    for (let index = 0; index < count; index += 1) ids.push((await seedDraftCourse(h, seed, `${prefix}-${String(index)}`)).id);
    await h.pool.query("UPDATE courses SET status = 'review' WHERE id = ANY($1::text[])", [ids]);
    return ids;
  }
  const entries = async (ids: string[]) => Promise.all(ids.map(async (id) => ({ id, expectedRevision: await revisionOf(h, "courses", id) })));
  const releaseCount = async () => Number((await h.pool.query<{ n: number }>("SELECT count(*)::int AS n FROM catalog_releases")).rows[0]?.n);
  const statuses = async (ids: string[]) => (await h.pool.query<{ status: string }>("SELECT status FROM courses WHERE id = ANY($1::text[]) ORDER BY id", [ids])).rows.map((row) => row.status);

  it("publishes every course in exactly one new release, audited per course, and rolls back in one activation", async () => {
    const before = await activeRelease(h);
    const releases = await releaseCount();
    const ids = await reviewCourses(5, "lote");
    const result = await call<BatchData>(h, "POST", "/courses/publish-batch", { key: key(), body: { courses: await entries(ids), note: "Lote", allowOrphan: true } });
    expect(result.status).toBe(200);
    expect(result.data.release.created).toBe(true);
    expect(result.data.previous).toBe(before.number);
    expect(result.data.diff.courses.added.sort()).toEqual([...ids].sort());
    expect(await releaseCount()).toBe(releases + 1);
    expect(await statuses(ids)).toEqual(ids.map(() => "published"));
    expect((await auditRows(h, { action: "course.publish" })).filter((row) => ids.includes(row.entity_id)).map((row) => row.release_number)).toEqual(ids.map(() => result.data.release.number));

    const rollback = await call(h, "POST", `/releases/${String(before.number)}/activate`, { key: key(), body: { note: "undo lote" } });
    expect(rollback.status).toBe(200);
    expect((await activeRelease(h)).number).toBe(before.number);
  });

  it("changes nothing when any course fails: one stale revision, one unready course, a draft or an unknown id", async () => {
    const before = await activeRelease(h);
    const releases = await releaseCount();
    const ids = await reviewCourses(3, "atom");
    const unready = (await seedDraftCourse(h, seed, "atom-unready", { ready: false })).id;
    await h.pool.query("UPDATE courses SET status = 'review' WHERE id = $1", [unready]);
    const draft = (await seedDraftCourse(h, seed, "atom-draft")).id;
    const good = await entries(ids);

    const stale = await call(h, "POST", "/courses/publish-batch", { key: key(), body: { courses: [...good.slice(0, 2), { id: ids[2] ?? "", expectedRevision: (good[2]?.expectedRevision ?? 1) + 5 }], note: "x", allowOrphan: true } });
    expect([stale.status, stale.body.error?.code]).toEqual([409, "revision_conflict"]);
    const failing = await call(h, "POST", "/courses/publish-batch", { key: key(), body: { courses: [...good, ...await entries([unready])], note: "x", allowOrphan: true } });
    expect(failing.status).toBe(412);
    expect((failing.body.error?.details as { failed: { entity: string }[] }).failed.every((failure) => failure.entity.includes(unready))).toBe(true);
    const drafted = await call(h, "POST", "/courses/publish-batch", { key: key(), body: { courses: [...good, ...await entries([draft])], note: "x", allowOrphan: true } });
    expect(drafted.status).toBe(409);
    const unknown = await call(h, "POST", "/courses/publish-batch", { key: key(), body: { courses: [...good, { id: "course-nope", expectedRevision: 1 }], note: "x" } });
    expect(unknown.status).toBe(404);
    const twice = await call(h, "POST", "/courses/publish-batch", { key: key(), body: { courses: [good[0], good[0]], note: "x" } });
    expect(twice.status).toBe(400);

    expect(await releaseCount()).toBe(releases);
    expect((await activeRelease(h)).number).toBe(before.number);
    expect(await statuses(ids)).toEqual(ids.map(() => "review"));
  });

  it("takes a whole university in one call: 80 courses, one release", async () => {
    const releases = await releaseCount();
    const ids = await reviewCourses(80, "uni");
    const result = await call<BatchData>(h, "POST", "/courses/publish-batch", { key: key(), body: { courses: await entries(ids), note: "MIT", allowOrphan: true } });
    expect(result.status).toBe(200);
    expect(await releaseCount()).toBe(releases + 1);
    expect(result.data.diff.courses.added).toHaveLength(80);
  }, 120_000);

  it("republishing already-published courses with no table change is a noop (no new release)", async () => {
    const ids = await reviewCourses(2, "again");
    const first = await call<BatchData>(h, "POST", "/courses/publish-batch", { key: key(), body: { courses: await entries(ids), note: "first", allowOrphan: true } });
    expect(first.data.release.created).toBe(true);
    const releases = await releaseCount();
    const second = await call<BatchData & { noop?: true }>(h, "POST", "/courses/publish-batch", { key: key(), body: { courses: await entries(ids), note: "again", allowOrphan: true } });
    expect(second.status).toBe(200);
    expect(second.data.release.created).toBe(false);
    expect(await releaseCount()).toBe(releases);
  });
});
