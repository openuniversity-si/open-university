import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { factsOf, readCourseState, readState } from "../../src/catalog/server/common.ts";
import { courseDetail } from "../../src/catalog/server/courses.ts";
import { createHarness, seedCatalog, seedDraftCourse, type Harness, type Seed } from "../fixtures/admin-catalog.ts";

// GET /courses/:id, a status move and a publish read one course's rows, not the whole catalog: same answer, O(course).
describe("course-scoped catalog state", () => {
  let h: Harness;
  let seed: Seed;
  let draft: string;
  beforeAll(async () => {
    h = createHarness();
    seed = await seedCatalog(h);
    draft = (await seedDraftCourse(h, seed, "gamma", { lessons: 2, ready: true })).id;
  }, 60_000);
  afterAll(async () => { await h.close(); });

  it("gives every course the same detail, facts and cover kinds as the whole-catalog state", async () => {
    const whole = await readState(h.pool);
    for (const id of [seed.courses.alpha, seed.courses.beta, draft]) {
      const scoped = await readCourseState(h.pool, [id]);
      expect(await courseDetail(h.pool, scoped, id), id).toEqual(await courseDetail(h.pool, whole, id));
      expect(factsOf(scoped, id), id).toEqual(factsOf(whole, id));
      expect(scoped.covers.get(id), id).toEqual(whole.covers.get(id));
      expect(scoped.revisions.get(id), id).toBe(whole.revisions.get(id));
    }
  });

  it("reads only the asked courses' rows", async () => {
    const scoped = await readCourseState(h.pool, [seed.courses.alpha]);
    expect(scoped.tables.courses.map((row) => row.id)).toEqual([seed.courses.alpha]);
    expect(new Set(scoped.tables.lessons.map((row) => row.course_id))).toEqual(new Set([seed.courses.alpha]));
    expect(scoped.tables.home_row_items.every((row) => row.course_id === seed.courses.alpha)).toBe(true);
    expect(scoped.tables.slug_redirects).toEqual([]);
    expect([...scoped.covers.keys()]).toEqual([seed.courses.alpha]);
    const both = await readCourseState(h.pool, [seed.courses.alpha, seed.courses.beta]);
    expect(both.tables.courses.map((row) => row.id).sort()).toEqual([seed.courses.alpha, seed.courses.beta].sort());
  });
});
