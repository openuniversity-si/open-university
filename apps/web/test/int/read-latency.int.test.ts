import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createAdminRateLimiter } from "../../src/admin/auth.ts";
import { performMediaList } from "../../src/media/server/actions.ts";
import { listMediaByOwners, swapMedia } from "../../src/media/server/repository.ts";
import { call, coverInput, createHarness, testDatabaseUrl, type CallResult, type Harness } from "../fixtures/admin-catalog.ts";
import { resetCatalogTables } from "../fixtures/catalog-reset.ts";

interface CoursePage { readonly courses: { readonly id: string }[]; readonly nextCursor: string | null }
interface RedirectPage { readonly redirects: { readonly from: string }[]; readonly nextCursor: string | null }
interface SubareaPage { readonly subareas: { readonly id: string; readonly covers: { readonly kind: string; readonly variant: string; readonly sha256: string }[] }[] }

// S10: a 10,000-course fixture stays under a second per list, and one subarea call carries every cover.
describe("admin fast reads", () => {
  let h: Harness;
  beforeAll(async () => {
    h = createHarness();
    await resetCatalogTables(testDatabaseUrl());
    await h.pool.query("INSERT INTO authors (id, slug, name, monogram, kind) VALUES ('author-fast', 'author-fast', 'Fast Author', 'FA', 'person')");
    await h.pool.query(`INSERT INTO courses (id, slug, author_id, title, cover_from, shared_with)
      SELECT 'c' || lpad(i::text, 5, '0'), 'c' || lpad(i::text, 5, '0'), 'author-fast', 'Course ' || i, 'own', '{}'
      FROM generate_series(1, 10000) AS i`);
    await h.pool.query(`INSERT INTO slug_redirects (from_path, to_path)
      SELECT '/c/old-' || lpad(i::text, 5, '0'), '/c/c' || lpad(i::text, 5, '0')
      FROM generate_series(1, 10000) AS i`);
  }, 120_000);
  afterAll(async () => { await h.close(); });

  async function walk(path: string, count: (body: CallResult<CoursePage | RedirectPage>["data"]) => number): Promise<{ readonly rows: number; readonly ms: number }> {
    const start = performance.now();
    let cursor = "";
    let rows = 0;
    for (let page = 0; page < 200; page += 1) {
      const target: string = cursor === "" ? path : `${path}?cursor=${encodeURIComponent(cursor)}`;
      const response: CallResult<CoursePage | RedirectPage> = await call<CoursePage | RedirectPage>(h, "GET", target);
      expect(response.status, JSON.stringify(response.body.error)).toBe(200);
      rows += count(response.data);
      const next = response.data.nextCursor;
      if (next === null) return { rows, ms: performance.now() - start };
      cursor = next;
    }
    return { rows, ms: performance.now() - start };
  }

  it("lists 10,000 courses in under a second", async () => {
    const listed = await walk("/courses", (page) => ("courses" in page ? page.courses.length : 0));
    expect(listed.rows).toBe(10000);
    expect(listed.ms).toBeLessThan(1000);
  });

  it("lists 10,000 redirects in under a second", async () => {
    const listed = await walk("/redirects", (page) => ("redirects" in page ? page.redirects.length : 0));
    expect(listed.rows).toBe(10000);
    expect(listed.ms).toBeLessThan(1000);
  });

  it("returns every subarea cover, and every named media owner, in one call each", async () => {
    await h.pool.query("INSERT INTO subject_areas (id, title, position) VALUES ('latency-area', 'Latency Area', (SELECT coalesce(max(position), 0) + 1 FROM subject_areas))");
    await h.pool.query(`INSERT INTO subject_subareas (id, area_id, title, position) VALUES
      ('latency-one', 'latency-area', 'Latency One', 1),
      ('latency-two', 'latency-area', 'Latency Two', 2),
      ('latency-three', 'latency-area', 'Latency Three', 3)`);
    const poster = await swapMedia(h.pool, "subarea", coverInput("subarea", "latency-one", "poster_9x16"));
    const og = await swapMedia(h.pool, "subarea", coverInput("subarea", "latency-two", "og"));
    h.recorder.statements.length = 0;
    const list = await call<SubareaPage>(h, "GET", "/subareas?covers=1");
    const stored = (await h.pool.query<{ id: string }>("SELECT id FROM subject_subareas")).rows.map((subarea) => subarea.id).sort();
    expect(list.status).toBe(200);
    expect(list.data.subareas.map((subarea) => subarea.id).sort()).toEqual(stored);
    expect(list.data.subareas.find((subarea) => subarea.id === "latency-one")?.covers).toEqual([{ kind: "poster_9x16", variant: "default", sha256: poster.sha256 }]);
    expect(list.data.subareas.find((subarea) => subarea.id === "latency-two")?.covers).toEqual([{ kind: "og", variant: "default", sha256: og.sha256 }]);
    expect(list.data.subareas.filter((subarea) => subarea.covers.length === 0).length).toBe(stored.length - 2);
    expect(h.recorder.statements.filter((statement) => statement.includes("FROM subject_subareas"))).toHaveLength(1);

    const statements: string[] = [];
    const db = { query: (sql: string, values?: unknown[]) => { statements.push(sql); return h.pool.query(sql, values); } };
    const owners = await listMediaByOwners(db, [
      { owner: "subarea", ownerId: "latency-one" },
      { owner: "subarea", ownerId: "latency-two" },
      { owner: "subarea", ownerId: "latency-three" },
    ], { activeOnly: true });
    expect(statements).toHaveLength(1);
    expect(owners.map((owner) => [owner.ownerId, owner.assets.length])).toEqual([["latency-one", 1], ["latency-two", 1], ["latency-three", 0]]);

    let lookedUp = false;
    const listed = await performMediaList({
      secret: "latency",
      limiter: createAdminRateLimiter({ requests: 1000, failures: 1000 }),
      db: () => h.pool,
      store: () => { throw new Error("unused"); },
      invalidate: () => {},
      courseOf: () => { lookedUp = true; return Promise.resolve(undefined); },
      owners: () => ({
        courseOf: () => Promise.resolve(undefined),
        graph: () => Promise.resolve({ courses: [], lessons: [] }),
        lockGraph: () => Promise.resolve(),
        inventory: () => Promise.resolve([]),
      }),
    }, { owners: "subarea:latency-one,subarea:latency-two,subarea:latency-three" });
    expect(lookedUp).toBe(false);
    if (!("owners" in listed)) throw new Error("media list --owners did not return owners");
    expect(listed.owners.map((owner) => [owner.ownerId, owner.versions.length])).toEqual([["latency-one", 1], ["latency-two", 1], ["latency-three", 0]]);
  });
});
