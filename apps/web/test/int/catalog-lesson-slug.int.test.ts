import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
vi.mock("server-only", () => ({}));
// The layout guard reads the active release from this database and answers 308 through next/navigation.
const active = vi.hoisted(() => ({ read: null as null | (() => Promise<unknown>) }));
vi.mock("@tower/catalog", () => ({ getCatalog: () => active.read?.() }));
vi.mock("next/navigation", () => ({
  permanentRedirect: (to: string) => { throw new Error(`308 ${to}`); },
  notFound: () => { throw new Error("404"); },
}));
import { readActiveRelease } from "../../src/catalog/server/read.ts";
import type { PublicCatalog } from "../../src/catalog/domain/release.ts";
import { resetCatalogTables } from "../fixtures/catalog-reset.ts";
import { publicRouteSnapshot } from "../../src/catalog/server/public-routes.ts";
import { guardCatalogPath } from "../../src/site/server/guard.ts";
import { auditRows, call, catalogFingerprint, createHarness, revisionOf, seedCatalog, testDatabaseUrl, type Harness, type LessonData, type PublicationData, type ReleaseData, type Seed } from "../fixtures/admin-catalog.ts";

interface Plan { created: { from: string; to: string }; flattened: { from: string; before: string; after: string }[]; removed: { from: string; to: string }[] }
type SlugData = LessonData & { redirects: Plan };
interface DryData { dryRun: true; lesson: LessonData["lesson"]; changes: Record<string, { before: unknown; after: unknown }>; redirects: Plan | null; noop: boolean }

describe("PATCH /lessons/:id slug with permanent redirects on PG18", () => {
  let h: Harness;
  let seed: Seed;
  let lesson: string;
  beforeAll(() => {
    h = createHarness();
    active.read = async () => (await readActiveRelease(h.pool)).release;
  });
  afterAll(async () => { await resetCatalogTables(testDatabaseUrl()); await h.close(); });
  beforeEach(async () => {
    seed = await seedCatalog(h);
    lesson = seed.lessons.alpha[0] ?? "";
  });
  const key = () => `k-${Math.random().toString(36).slice(2)}`;
  const rename = async (slug: string, query = "") => call<SlugData>(h, "PATCH", `/lessons/${lesson}${query}`, { body: { expectedRevision: await revisionOf(h, "lessons", lesson), slug } });
  const redirects = async () => (await h.pool.query<{ from_path: string; to_path: string }>("SELECT from_path, to_path FROM slug_redirects ORDER BY from_path")).rows.map((row) => [row.from_path, row.to_path]);
  const guard = (path: string) => (async () => {
    const release = await active.read?.();
    if (!release) throw new Error("no release");
    guardCatalogPath(path, publicRouteSnapshot(release as PublicCatalog));
  })().then(() => "200", (error: unknown) => (error instanceof Error ? error.message : "?"));

  it("renames, redirects the old path, bumps both revisions and audits lesson.slug in the same transaction", async () => {
    const lessonRevision = await revisionOf(h, "lessons", lesson);
    const courseRevision = await revisionOf(h, "courses", seed.courses.alpha);
    h.recorder.statements.length = 0;
    const renamed = await rename("the-start");
    expect(renamed.status).toBe(200);
    expect(renamed.data.lesson).toMatchObject({ slug: "the-start", revision: lessonRevision + 1 });
    expect(renamed.data.courseRevision).toBe(courseRevision + 1);
    expect(renamed.data.redirects).toEqual({ created: { from: "/c/alpha/lesson-1", to: "/c/alpha/the-start" }, flattened: [], removed: [] });
    expect(await redirects()).toEqual([["/c/alpha/lesson-1", "/c/alpha/the-start"]]);
    const audit = await auditRows(h, { entity: `lesson:${lesson}` });
    expect(audit.map((row) => row.action)).toEqual(["lesson.slug"]);
    expect(audit[0]?.before).toEqual({ slug: "lesson-1", path: "/c/alpha/lesson-1" });
    expect(audit[0]?.after).toMatchObject({ slug: "the-start", path: "/c/alpha/the-start", redirects: renamed.data.redirects, courseRevision: courseRevision + 1 });
    const statements = h.recorder.statements;
    const begin = statements.indexOf("BEGIN");
    const commit = statements.indexOf("COMMIT");
    const inside = statements.slice(begin, commit);
    expect(begin).toBeGreaterThanOrEqual(0);
    expect(inside.some((sql) => sql.startsWith("INSERT INTO slug_redirects"))).toBe(true);
    expect(inside.some((sql) => sql.includes("INSERT INTO catalog_audit"))).toBe(true);
    expect(statements.slice(commit).some((sql) => /slug_redirects|catalog_audit|UPDATE lessons/.test(sql))).toBe(false);
  });

  it("rolls the slug and its redirects back together when the audit fails", async () => {
    const before = await catalogFingerprint(h);
    await h.pool.query(`CREATE OR REPLACE FUNCTION fail_slug_audit() RETURNS trigger AS $$ BEGIN IF NEW.action = 'lesson.slug' THEN RAISE EXCEPTION 'audit down'; END IF; RETURN NEW; END $$ LANGUAGE plpgsql`);
    await h.pool.query("CREATE TRIGGER fail_slug_audit BEFORE INSERT ON catalog_audit FOR EACH ROW EXECUTE FUNCTION fail_slug_audit()");
    try {
      const failed = await rename("the-start");
      expect(failed.status).toBeGreaterThanOrEqual(500);
    } finally {
      await h.pool.query("DROP TRIGGER fail_slug_audit ON catalog_audit");
      await h.pool.query("DROP FUNCTION fail_slug_audit()");
    }
    expect(await catalogFingerprint(h)).toBe(before);
  });

  it("flattens chains (A→B→C leaves A→C, B→C) and going back drops the obsolete redirect", async () => {
    await rename("b");
    const chained = await rename("c");
    expect(chained.data.redirects.flattened).toEqual([{ from: "/c/alpha/lesson-1", before: "/c/alpha/b", after: "/c/alpha/c" }]);
    expect(await redirects()).toEqual([["/c/alpha/b", "/c/alpha/c"], ["/c/alpha/lesson-1", "/c/alpha/c"]]);
    const back = await rename("lesson-1");
    expect(back.status).toBe(200);
    expect(back.data.redirects.removed).toEqual([{ from: "/c/alpha/lesson-1", to: "/c/alpha/c" }]);
    expect(await redirects()).toEqual([["/c/alpha/b", "/c/alpha/lesson-1"], ["/c/alpha/c", "/c/alpha/lesson-1"]]);
    // Every redirect ends at a lesson that exists (never a dangling target, never a self-redirect).
    const paths = new Set((await h.pool.query<{ path: string }>("SELECT '/c/' || c.slug || '/' || l.slug AS path FROM lessons l JOIN courses c ON c.id = l.course_id")).rows.map((row) => row.path));
    for (const [from, to] of await redirects()) expect([paths.has(to ?? ""), paths.has(from ?? "")]).toEqual([true, false]);
  });

  it("refuses a slug taken in the course or another page's old URL (409 slug_taken), a bad slug (400) and a stale revision (409)", async () => {
    await h.pool.query("INSERT INTO slug_redirects (from_path, to_path) VALUES ('/c/alpha/gone', '/c/beta')");
    const before = await catalogFingerprint(h);
    for (const slug of ["lesson-2", "gone"]) {
      const taken = await rename(slug);
      expect([taken.status, taken.body.error?.code], slug).toEqual([409, "slug_taken"]);
    }
    for (const slug of ["Bad_Slug", "a".repeat(161)]) expect((await rename(slug)).status, slug).toBe(400);
    const stale = await call(h, "PATCH", `/lessons/${lesson}`, { body: { expectedRevision: (await revisionOf(h, "lessons", lesson)) + 5, slug: "the-start" } });
    expect([stale.status, stale.body.error?.code]).toEqual([409, "revision_conflict"]);
    expect(await catalogFingerprint(h)).toBe(before);
    expect((await rename("a".repeat(160))).status).toBe(200);
  });

  it("?dryRun=true answers the report and writes nothing (no transaction)", async () => {
    await rename("b");
    const before = await catalogFingerprint(h);
    h.recorder.statements.length = 0;
    const dry = await call<DryData>(h, "PATCH", `/lessons/${lesson}?dryRun=true`, { body: { expectedRevision: await revisionOf(h, "lessons", lesson), slug: "c", kind: "background" } });
    expect(dry.status).toBe(200);
    expect(dry.data).toMatchObject({ dryRun: true, noop: false, lesson: { slug: "b" }, changes: { slug: { before: "b", after: "c" }, kind: { before: "lecture", after: "background" } } });
    expect(dry.data.redirects).toEqual({ created: { from: "/c/alpha/b", to: "/c/alpha/c" }, flattened: [{ from: "/c/alpha/lesson-1", before: "/c/alpha/b", after: "/c/alpha/c" }], removed: [] });
    expect(h.recorder.statements.filter((sql) => /^\s*(INSERT|UPDATE|DELETE|BEGIN)/i.test(sql))).toEqual([]);
    expect(await catalogFingerprint(h)).toBe(before);
    const taken = await call(h, "PATCH", `/lessons/${lesson}?dryRun=true`, { body: { expectedRevision: await revisionOf(h, "lessons", lesson), slug: "lesson-2" } });
    expect([taken.status, taken.body.error?.code]).toEqual([409, "slug_taken"]);
  });

  it("goes live with the next release (308 from the old URL); activating the old release restores the old slug without a redirect", async () => {
    await rename("the-start");
    expect(await guard("/c/alpha/lesson-1")).toBe("200");
    expect(await guard("/c/alpha/the-start")).toBe("404");
    const published = await call<PublicationData>(h, "POST", "/releases", { key: key(), body: { note: "slug" } });
    expect(published.data.release.number).toBe(2);
    expect((await call<PublicationData>(h, "POST", "/releases/2/activate", { key: key(), body: { note: "slug" } })).status).toBe(200);
    const release = (await call<ReleaseData>(h, "GET", "/releases/2")).data.release.payload;
    expect(release.redirects).toContainEqual({ from: "/c/alpha/lesson-1", to: "/c/alpha/the-start" });
    expect(await guard("/c/alpha/lesson-1")).toBe("308 /c/alpha/the-start");
    expect(await guard("/c/alpha/the-start")).toBe("200");

    expect((await call(h, "POST", "/releases/1/activate", { key: key(), body: { note: "rollback" } })).status).toBe(200);
    expect(await guard("/c/alpha/lesson-1")).toBe("200");
    expect(await guard("/c/alpha/the-start")).toBe("404");
    expect((await readActiveRelease(h.pool)).release.redirects).toEqual([]);
  });

  it("a dry-run preserves current catalog rows and a rename changes only the lesson and redirect", async () => {
    const before = await catalogFingerprint(h);
    const rev = await revisionOf(h, "lessons", lesson);
    const dry = await call<DryData>(h, "PATCH", `/lessons/${lesson}?dryRun=true`, { body: { expectedRevision: rev, slug: "renamed-current" } });
    expect(dry.data.dryRun).toBe(true);
    expect(await catalogFingerprint(h)).toEqual(before);
    expect((await rename("renamed-current")).status).toBe(200);
    expect(await catalogFingerprint(h)).not.toEqual(before);
  });
});
