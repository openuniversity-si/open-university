import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { swapMedia } from "../../src/media/server/repository.ts";
import { activeRelease, auditRows, call, coverInput, createHarness, revisionOf, seedCatalog, type Harness, type Seed } from "../fixtures/admin-catalog.ts";

// ADR-26: a course's subarea always belongs to its area (API first, the composite key underneath); classify is idempotent.
interface ClassifyData { changed: { id: string; after: { areaId: string | null; subareaId: string | null } }[]; unchanged: number; noop?: boolean }
interface SubareaRow { id: string; areaId: string; position: number; uses: number; published: number }

describe("admin catalog: subareas", () => {
  let h: Harness;
  let seed: Seed;
  let n = 0;
  const key = () => { n += 1; return `subarea-${String(n)}`; };
  beforeAll(() => { h = createHarness(); });
  afterAll(async () => { await h.close(); });
  beforeEach(async () => { seed = await seedCatalog(h); }, 60_000);
  const classify = (items: unknown[]) => call<ClassifyData>(h, "POST", "/courses/classify", { key: key(), body: { items } });
  const stored = async (id: string) => (await h.pool.query<{ area_id: string | null; subarea_id: string | null }>("SELECT area_id, subarea_id FROM courses WHERE id = $1", [id])).rows[0];

  it("lists the 81 seeded subareas in area order, with uses", async () => {
    await classify([{ id: seed.courses.alpha, areaId: "engineering", subareaId: "robotics" }]);
    const list = await call<{ subareas: SubareaRow[] }>(h, "GET", "/subareas");
    expect(list.data.subareas).toHaveLength(81);
    expect(list.data.subareas[0]).toMatchObject({ id: "programming", areaId: "computer-science", position: 1 });
    expect(list.data.subareas.find((row) => row.id === "robotics")).toMatchObject({ areaId: "engineering", uses: 1 });
    expect(list.data.subareas.every((row) => !("covers" in row))).toBe(true);
  });

  it("returns every subarea's active covers in one call", async () => {
    const poster = await swapMedia(h.pool, "subarea", coverInput("subarea", "programming", "poster_9x16"));
    const og = await swapMedia(h.pool, "subarea", coverInput("subarea", "algorithms", "og"));
    h.recorder.statements.length = 0;
    const list = await call<{ subareas: (SubareaRow & { covers: { kind: string; variant: string; sha256: string }[] })[] }>(h, "GET", "/subareas?covers=1");
    expect(list.status).toBe(200);
    expect(list.data.subareas).toHaveLength(81);
    expect(list.data.subareas.every((row) => Array.isArray(row.covers))).toBe(true);
    expect(list.data.subareas.find((row) => row.id === "programming")?.covers).toEqual([{ kind: "poster_9x16", variant: "default", sha256: poster.sha256 }]);
    expect(list.data.subareas.find((row) => row.id === "algorithms")?.covers).toEqual([{ kind: "og", variant: "default", sha256: og.sha256 }]);
    expect(list.data.subareas.find((row) => row.id === "calculus")?.covers).toEqual([]);
    expect(h.recorder.statements.filter((statement) => statement.includes("FROM subject_subareas"))).toHaveLength(1);
  });

  it("classifies in bulk, writes only what changes, and a second run is a noop", async () => {
    const revision = await revisionOf(h, "courses", seed.courses.alpha);
    const items = [{ id: seed.courses.alpha, areaId: "engineering", subareaId: "robotics" }, { id: seed.courses.beta, areaId: "psychology" }];
    const first = await classify(items);
    expect(first.status).toBe(200);
    expect(first.data.changed.map((change) => [change.id, change.after])).toEqual([
      [seed.courses.alpha, { areaId: "engineering", subareaId: "robotics" }], [seed.courses.beta, { areaId: "psychology", subareaId: null }],
    ]);
    expect(await revisionOf(h, "courses", seed.courses.alpha)).toBe(revision + 1);
    const audits = (await auditRows(h)).length;
    const second = await classify(items);
    expect(second.data).toMatchObject({ changed: [], unchanged: 2, noop: true });
    expect((await auditRows(h)).length).toBe(audits);
    expect(await revisionOf(h, "courses", seed.courses.alpha)).toBe(revision + 1);
  });

  it("refuses a subarea of another area, an unknown one, or moving area under a subarea; nothing is written", async () => {
    await classify([{ id: seed.courses.alpha, areaId: "engineering", subareaId: "robotics" }]);
    const bad = await classify([{ id: seed.courses.beta, areaId: "psychology", subareaId: "robotics" }, { id: seed.courses.alpha, areaId: "physics" }]);
    expect(bad.status).toBe(412);
    expect(JSON.stringify(bad.body.error?.details)).toContain("course.classification");
    expect(await stored(seed.courses.alpha)).toEqual({ area_id: "engineering", subarea_id: "robotics" });
    expect((await stored(seed.courses.beta))?.subarea_id).toBeNull();
    const unknown = await classify([{ id: seed.courses.beta, areaId: "engineering", subareaId: "nope" }]);
    expect(unknown.status).toBe(412);
    // Moving the area together with a subarea of the new area is fine; clearing the subarea also is.
    expect((await classify([{ id: seed.courses.alpha, areaId: "physics", subareaId: "classical-mechanics" }])).status).toBe(200);
    expect((await classify([{ id: seed.courses.alpha, subareaId: null }])).status).toBe(200);
    expect(await stored(seed.courses.alpha)).toEqual({ area_id: "physics", subarea_id: null });
  });

  it("refuses the same through PATCH, and the database refuses it even without the API", async () => {
    const patch = await call(h, "PATCH", `/courses/${seed.courses.alpha}`, { body: { expectedRevision: await revisionOf(h, "courses", seed.courses.alpha), subareaId: "robotics" } });
    expect(patch.status).toBe(422);
    await expect(h.pool.query("UPDATE courses SET area_id = 'psychology', subarea_id = 'robotics' WHERE id = $1", [seed.courses.alpha])).rejects.toThrow(/courses_subarea_area_fk/);
    await expect(h.pool.query("UPDATE courses SET status = 'draft', area_id = NULL, subarea_id = 'robotics' WHERE id = $1", [seed.courses.alpha])).rejects.toThrow(/courses_subarea_area/);
  });

  it("creates a subarea at the end of its area, never with an area's id", async () => {
    const created = await call<{ subarea: SubareaRow }>(h, "POST", "/subareas", { key: key(), body: { id: "naval-engineering", areaId: "engineering", title: "Naval Engineering" } });
    expect(created.status).toBe(201);
    expect(created.data.subarea).toMatchObject({ id: "naval-engineering", areaId: "engineering", position: 18 });
    const clash = await call(h, "POST", "/subareas", { key: key(), body: { id: "physics", areaId: "engineering", title: "Physics Engineering" } });
    expect(clash.status).toBeGreaterThanOrEqual(400);
  });

  it("puts subareas in the release once a published course has one", async () => {
    const payload = async () => (await h.pool.query<{ payload: { subareas?: { id: string }[]; courses: { id: string; subareaId?: string }[] } }>("SELECT payload FROM catalog_releases WHERE number = $1", [(await activeRelease(h)).number])).rows[0]?.payload;
    expect((await payload())?.subareas).toBeUndefined();
    await classify([{ id: seed.courses.alpha, areaId: "engineering", subareaId: "robotics" }]);
    const release = await call<{ release: { number: number } }>(h, "POST", "/releases", { key: key(), body: { note: "subareas" } });
    expect(release.status).toBe(201);
    const after = await payload();
    expect(after?.subareas?.map((subarea) => subarea.id)).toContain("robotics");
    expect(after?.courses.find((course) => course.id === seed.courses.alpha)?.subareaId).toBe("robotics");
  });
});
