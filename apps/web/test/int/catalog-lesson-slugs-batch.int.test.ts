import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
vi.mock("server-only", () => ({}));
// The layout guard reads the active release from this database and answers 308 through next/navigation.
const active = vi.hoisted(() => ({ read: null as null | (() => Promise<unknown>) }));
vi.mock("@tower/catalog", () => ({ getCatalog: () => active.read?.() }));
vi.mock("next/navigation", () => ({
  permanentRedirect: (to: string) => { throw new Error(`308 ${to}`); },
  notFound: () => { throw new Error("404"); },
}));
import type { SlugBatchPlan } from "../../src/catalog/domain/lesson-slug.ts";
import { readActiveRelease } from "../../src/catalog/server/read.ts";
import type { PublicCatalog } from "../../src/catalog/domain/release.ts";
import { publicRouteSnapshot } from "../../src/catalog/server/public-routes.ts";
import { guardCatalogPath } from "../../src/site/server/guard.ts";
import { auditRows, call, catalogFingerprint, createHarness, revisionOf, seedCatalog, seedLesson, testDatabaseUrl, type DoctorData, type Harness, type PublicationData, type Seed } from "../fixtures/admin-catalog.ts";
import { resetCatalogTables } from "../fixtures/catalog-reset.ts";

interface BatchData { courseId: string; courseRevision: number; plan: SlugBatchPlan; lessons: { id: string; slug: string; revision: number }[]; noop?: true }
interface DryData { dryRun: true; courseId: string; plan: SlugBatchPlan; noop: boolean }

describe("PUT /lessons/slugs: atomic lesson slug batch on PG18", () => {
  let h: Harness;
  let seed: Seed;
  let lessons: string[];
  beforeAll(() => {
    h = createHarness();
    active.read = async () => (await readActiveRelease(h.pool)).release;
  });
  afterAll(async () => { await resetCatalogTables(testDatabaseUrl()); await h.close(); });
  beforeEach(async () => {
    seed = await seedCatalog(h);
    lessons = seed.lessons.alpha;
  });
  const key = () => `k-${Math.random().toString(36).slice(2)}`;
  const id = (index: number) => lessons[index] ?? "";
  const batch = async <T = BatchData>(changes: [number, string][], options: { dryRun?: boolean; key?: string } = {}) => call<T>(h, "PUT", "/lessons/slugs", {
    key: options.key ?? key(),
    body: { courseId: seed.courses.alpha, expectedRevision: await revisionOf(h, "courses", seed.courses.alpha), changes: changes.map(([index, slug]) => ({ lessonId: id(index), slug })), ...(options.dryRun ? { dryRun: true } : {}) },
  });
  const slugs = async () => (await h.pool.query<{ slug: string }>("SELECT slug FROM lessons WHERE course_id = $1 ORDER BY position", [seed.courses.alpha])).rows.map((row) => row.slug);
  const redirects = async () => (await h.pool.query<{ from_path: string; to_path: string }>("SELECT from_path, to_path FROM slug_redirects ORDER BY from_path")).rows.map((row) => [row.from_path, row.to_path]);
  const guard = (path: string) => (async () => {
    const release = await active.read?.();
    if (!release) throw new Error("no release");
    guardCatalogPath(path, publicRouteSnapshot(release as PublicCatalog));
  })().then(() => "200", (error: unknown) => (error instanceof Error ? error.message : "?"));

  it("renames several lessons in one transaction: one redirect and one lesson.slug audit row per lesson, the course revision once", async () => {
    const courseRevision = await revisionOf(h, "courses", seed.courses.alpha);
    const lessonRevision = await revisionOf(h, "lessons", id(0));
    h.recorder.statements.length = 0;
    const renamed = await batch([[0, "lecture-01-intro"], [1, "lecture-02-next"], [2, "lesson-3"]]);
    expect(renamed.status).toBe(200);
    expect(renamed.data.courseRevision).toBe(courseRevision + 1);
    expect(renamed.data.lessons).toEqual([{ id: id(0), slug: "lecture-01-intro", revision: lessonRevision + 1 }, { id: id(1), slug: "lecture-02-next", revision: lessonRevision + 1 }]);
    expect(await slugs()).toEqual(["lecture-01-intro", "lecture-02-next", "lesson-3"]);
    expect(await redirects()).toEqual([["/c/alpha/lesson-1", "/c/alpha/lecture-01-intro"], ["/c/alpha/lesson-2", "/c/alpha/lecture-02-next"]]);
    for (const [index, slug] of [[0, "lecture-01-intro"], [1, "lecture-02-next"]] as const) {
      const audit = await auditRows(h, { entity: `lesson:${id(index)}` });
      expect(audit.map((row) => row.action)).toEqual(["lesson.slug"]);
      expect(audit[0]?.after).toMatchObject({ slug, batch: true, courseRevision: courseRevision + 1, redirects: { created: { from: `/c/alpha/lesson-${String(index + 1)}`, to: `/c/alpha/${slug}` } } });
    }
    expect(await auditRows(h, { entity: `lesson:${id(2)}` })).toEqual([]);
    const statements = h.recorder.statements;
    const inside = statements.slice(statements.indexOf("BEGIN"), statements.indexOf("COMMIT"));
    expect(inside.filter((sql) => sql.startsWith("UPDATE lessons"))).toHaveLength(2);
    expect(statements.slice(statements.indexOf("COMMIT")).some((sql) => /slug_redirects|catalog_audit|UPDATE lessons/.test(sql))).toBe(false);
  });

  it("swaps A↔B and rotates three lessons through the internal temporary slug, without a redirect from a path still in use", async () => {
    await h.pool.query("INSERT INTO slug_redirects (from_path, to_path) VALUES ('/c/alpha/very-old', '/c/alpha/lesson-1')");
    const swapped = await batch([[0, "lesson-2"], [1, "lesson-1"]]);
    expect(swapped.status, JSON.stringify(swapped.body.error)).toBe(200);
    expect(swapped.data.plan).toMatchObject({ created: [], reused: ["/c/alpha/lesson-1", "/c/alpha/lesson-2"], flattened: [{ from: "/c/alpha/very-old", before: "/c/alpha/lesson-1", after: "/c/alpha/lesson-2" }] });
    expect(await slugs()).toEqual(["lesson-2", "lesson-1", "lesson-3"]);
    expect(await redirects()).toEqual([["/c/alpha/very-old", "/c/alpha/lesson-2"]]);
    const rotated = await batch([[0, "lesson-3"], [1, "lesson-2"], [2, "lesson-1"]]);
    expect(rotated.status, JSON.stringify(rotated.body.error)).toBe(200);
    expect(await slugs()).toEqual(["lesson-3", "lesson-2", "lesson-1"]);
    expect(await redirects()).toEqual([["/c/alpha/very-old", "/c/alpha/lesson-3"]]);
  });

  it("is all or nothing: a collision between the changes, another page's old URL, a stale revision or a failure midway change nothing", async () => {
    await h.pool.query("INSERT INTO slug_redirects (from_path, to_path) VALUES ('/c/alpha/gone', '/c/beta')");
    const before = await catalogFingerprint(h);
    const twice = await batch([[0, "same"], [1, "same"]]);
    expect([twice.status, twice.body.error?.code]).toEqual([409, "slug_taken"]);
    const unchanged = await batch([[0, "fresh"], [1, "lesson-3"]]);
    expect([unchanged.status, unchanged.body.error?.code]).toEqual([409, "slug_taken"]);
    const oldUrl = await batch([[0, "fresh"], [1, "gone"]]);
    expect([oldUrl.status, oldUrl.body.error?.code]).toEqual([409, "slug_taken"]);
    const foreign = await call(h, "PUT", "/lessons/slugs", { key: key(), body: { courseId: seed.courses.alpha, expectedRevision: await revisionOf(h, "courses", seed.courses.alpha), changes: [{ lessonId: seed.lessons.beta[0], slug: "x" }] } });
    expect([foreign.status, foreign.body.error?.code]).toEqual([422, "unprocessable"]);
    const stale = await call(h, "PUT", "/lessons/slugs", { key: key(), body: { courseId: seed.courses.alpha, expectedRevision: 999, changes: [{ lessonId: id(0), slug: "x" }] } });
    expect([stale.status, stale.body.error?.code]).toEqual([409, "revision_conflict"]);
    expect(await catalogFingerprint(h)).toBe(before);

    // The second lesson's audit row fails after the first lesson, every slug and every redirect were written.
    await h.pool.query(`CREATE OR REPLACE FUNCTION fail_second_slug() RETURNS trigger AS $$ BEGIN IF NEW.action = 'lesson.slug' AND NEW.entity_id = '${id(1)}' THEN RAISE EXCEPTION 'audit down'; END IF; RETURN NEW; END $$ LANGUAGE plpgsql`);
    await h.pool.query("CREATE TRIGGER fail_second_slug BEFORE INSERT ON catalog_audit FOR EACH ROW EXECUTE FUNCTION fail_second_slug()");
    try {
      const failed = await batch([[0, "first"], [1, "second"], [2, "third"]]);
      expect(failed.status).toBeGreaterThanOrEqual(500);
    } finally {
      await h.pool.query("DROP TRIGGER fail_second_slug ON catalog_audit");
      await h.pool.query("DROP FUNCTION fail_second_slug()");
    }
    expect(await catalogFingerprint(h)).toBe(before);
    expect(await slugs()).toEqual(["lesson-1", "lesson-2", "lesson-3"]);
  });

  it("requires an Idempotency-Key and replays the stored answer for the same key without writing again", async () => {
    const body = { courseId: seed.courses.alpha, expectedRevision: await revisionOf(h, "courses", seed.courses.alpha), changes: [{ lessonId: id(0), slug: "replayed" }] };
    const keyless = await call(h, "PUT", "/lessons/slugs", { body });
    expect([keyless.status, keyless.body.error?.code]).toEqual([400, "invalid"]);
    const first = await call<BatchData>(h, "PUT", "/lessons/slugs", { key: "batch-once", body });
    expect(first.status).toBe(200);
    const fingerprint = await catalogFingerprint(h);
    const again = await call<BatchData>(h, "PUT", "/lessons/slugs", { key: "batch-once", body });
    expect(again.status).toBe(200);
    expect(again.headers.get("idempotent-replay")).toBe("true");
    expect(again.data).toEqual(first.data);
    expect(await catalogFingerprint(h)).toBe(fingerprint);
    const mismatch = await call(h, "PUT", "/lessons/slugs", { key: "batch-once", body: { ...body, changes: [{ lessonId: id(0), slug: "other" }] } });
    expect([mismatch.status, mismatch.body.error?.code]).toEqual([422, "idempotency_mismatch"]);
  });

  it("dryRun: true answers the plan and writes nothing (no transaction); a batch to the current slugs is a noop", async () => {
    const before = await catalogFingerprint(h);
    h.recorder.statements.length = 0;
    const dry = await batch<DryData>([[0, "lesson-2"], [1, "lesson-1"], [2, "lesson-3"]], { dryRun: true });
    expect(dry.status).toBe(200);
    expect(dry.data).toMatchObject({ dryRun: true, noop: false, plan: { changes: [{ lessonId: id(0), before: "lesson-1", after: "lesson-2" }, { lessonId: id(1), before: "lesson-2", after: "lesson-1" }] } });
    expect(h.recorder.statements.filter((sql) => /^\s*(INSERT|UPDATE|DELETE|BEGIN)/i.test(sql))).toEqual([]);
    expect(await catalogFingerprint(h)).toBe(before);
    const noop = await batch([[0, "lesson-1"]]);
    expect([noop.status, noop.data.noop]).toEqual([200, true]);
  });

  it("goes live with the next release (308 from each old URL, one hop); activating the previous release restores the old slugs", async () => {
    await batch([[0, "lecture-01-intro"], [1, "lecture-02-next"]]);
    expect(await guard("/c/alpha/lesson-1")).toBe("200");
    expect((await call<PublicationData>(h, "POST", "/releases", { key: key(), body: { note: "lesson slugs" } })).status).toBe(201);
    expect((await call(h, "POST", "/releases/2/activate", { key: key(), body: { note: "lesson slugs" } })).status).toBe(200);
    expect(await guard("/c/alpha/lesson-1")).toBe("308 /c/alpha/lecture-01-intro");
    expect(await guard("/c/alpha/lesson-2")).toBe("308 /c/alpha/lecture-02-next");
    expect(await guard("/c/alpha/lecture-01-intro")).toBe("200");
    expect(await guard("/c/alpha/lesson-3")).toBe("200");
    expect(await guard("/c/alpha/no-such-lesson")).toBe("404");
    expect((await call(h, "POST", "/releases/1/activate", { key: key(), body: { note: "rollback" } })).status).toBe(200);
    expect(await guard("/c/alpha/lesson-1")).toBe("200");
    expect(await guard("/c/alpha/lecture-01-intro")).toBe("404");
  });

  it("doctor warns lesson.slug.quality for imported slugs the rule would not give, never for the legacy lessons", async () => {
    const finding = async () => (await call<DoctorData>(h, "GET", "/doctor")).data.findings.find((entry) => entry.code === "lesson.slug.quality");
    // The seed's lessons are lesson-1…5: legacy ids, exempt whatever their slug.
    expect(await finding()).toBeUndefined();
    await h.pool.query("ALTER SEQUENCE lesson_seq RESTART WITH 500");
    const imported = await seedLesson(h.pool, seed.courses.alpha);
    expect(await finding()).toMatchObject({ severity: "warning", count: 1, sample: [`alpha/lesson-4 (${imported.id}): rule gives lecture-04`] });
    lessons = [imported.id];
    await batch([[0, "lecture-04-fall-2024"]]);
    expect((await finding())?.sample).toEqual([`alpha/lecture-04-fall-2024 (${imported.id}): edition tag, rule gives lecture-04`]);
    await batch([[0, "lecture-04"]]);
    expect(await finding()).toBeUndefined();
  });
});
