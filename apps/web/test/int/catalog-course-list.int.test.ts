import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { pendingFor, readState } from "../../src/catalog/server/common.ts";
import { call, createHarness, seedCatalog, seedDraftCourse, type Harness, type Seed } from "../fixtures/admin-catalog.ts";

interface Listed {
  readonly id: string;
  readonly counts: { editions: number; lessons: number; visibleLessons: number; texts: number; draftTexts: number };
  readonly pending: { target: string | null; failed: { rule: string }[] };
}
interface Page { readonly courses: Listed[]; readonly nextCursor: string | null }

// GET /courses is a cursor page of set-based reads. The page's counts and pending rules match a whole-catalog read,
// and the statements for one page do not grow a query per course.
describe("GET /courses pages", () => {
  let h: Harness;
  let seed: Seed;
  let draft: string;
  beforeAll(async () => {
    h = createHarness();
    seed = await seedCatalog(h);
    draft = (await seedDraftCourse(h, seed, "gamma", { lessons: 1, ready: true })).id;
  }, 60_000);
  afterAll(async () => { await h.close(); });

  it("returns every course across cursors, with the same counts and pending rules as the full catalog", async () => {
    const whole = await readState(h.pool);
    const seen: string[] = [];
    let cursor = "";
    for (let page = 0; page < 10; page += 1) {
      const target = cursor === "" ? "/courses?limit=1" : `/courses?limit=1&cursor=${cursor}`;
      const response = await call<Page>(h, "GET", target);
      expect(response.status, JSON.stringify(response.body.error)).toBe(200);
      const course = response.data.courses[0];
      if (!course) {
        expect(response.data.nextCursor).toBeNull();
        break;
      }
      seen.push(course.id);
      const row = whole.tables.courses.find((entry) => entry.id === course.id);
      expect(row, course.id).toBeDefined();
      if (!row) return;
      const lessons = whole.tables.lessons.filter((lesson) => lesson.course_id === course.id);
      const lessonIds = new Set(lessons.map((lesson) => lesson.id));
      const texts = whole.tables.catalog_texts.filter((text) => (text.entity_kind === "course" && text.entity_id === course.id) || (text.entity_kind === "lesson" && lessonIds.has(text.entity_id)));
      expect(course.counts).toEqual({
        editions: whole.tables.course_editions.filter((edition) => edition.course_id === course.id).length,
        lessons: lessons.length,
        visibleLessons: lessons.filter((lesson) => lesson.visible).length,
        texts: texts.length,
        draftTexts: texts.filter((text) => text.status === "draft").length,
      });
      expect(course.pending).toEqual(pendingFor(whole, row));
      if (response.data.nextCursor === null) break;
      expect(response.data.nextCursor).toBe(course.id);
      cursor = response.data.nextCursor;
    }
    expect(new Set(seen)).toEqual(new Set(whole.tables.courses.map((course) => course.id)));
    expect(seen).toHaveLength(whole.tables.courses.length);
    expect(seen).toContain(draft);
  });

  it("reads the page as a set, not one round-trip per course", async () => {
    h.recorder.statements.length = 0;
    const response = await call<Page>(h, "GET", "/courses?limit=2");
    expect(response.data.courses.map((course) => course.id)).toHaveLength(2);
    const sql = h.recorder.statements;
    expect(sql.filter((statement) => statement.includes("WITH page AS"))).toHaveLength(1);
    expect(sql.some((statement) => /WHERE id = \$1\b/.test(statement))).toBe(false);
    expect(sql.some((statement) => statement.includes("id = ANY($1)"))).toBe(true);
    expect(sql.length).toBeLessThan(8);
  });
});
