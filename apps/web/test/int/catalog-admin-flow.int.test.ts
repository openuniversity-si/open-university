import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
vi.mock("server-only", () => ({}));
// /api/health reads getCatalogState; after an activation expires the "catalog" tag, that is an uncached read of the active
// release, which is what this stand-in does over the test database.
const state = vi.hoisted(() => ({ pool: null as null | { query(sql: string): Promise<{ rows: Record<string, unknown>[] }> } }));
vi.mock("@tower/catalog", async () => {
  const read = await import("../../src/catalog/server/read.ts");
  return { getCatalogState: () => read.resolveCatalog(() => read.readActiveRelease(state.pool as NonNullable<typeof state.pool>), {}) };
});
import { GET as health } from "../../src/app/api/health/route.ts";
import { REQUIRED_COVERS } from "../../src/catalog/domain/rules/status.ts";
import { TEXT_FIELDS } from "../../src/catalog/domain/fields.ts";
import { swapMedia } from "../../src/media/server/repository.ts";
import { auditRows, call, coverInput, createHarness, newVideoId, seedCatalog, seedProgress, type AuthorView, type CourseDetail, type CourseView, type DoctorData, type Harness, type HomeData, type LessonData, type PublicationData } from "../fixtures/admin-catalog.ts";

describe("admin catalog: one course from nothing to purge, through the API only", () => {
  let h: Harness;
  beforeAll(async () => { h = createHarness(); state.pool = h.pool; await seedCatalog(h); });
  afterAll(async () => { await h.close(); });

  it("creates, edits, approves, reviews, publishes, unpublishes, archives and purges, leaving the doctor clean", async () => {
    let n = 0;
    const key = () => { n += 1; return `flow-${String(n)}`; };
    const healthRelease = async () => ((await (await health(new Request("https://tower.test/api/health"))).json()) as { catalog: { release: number; sha: string; source: string } }).catalog;
    expect((await healthRelease()).release).toBe(1);

    const author = await call<{ author: AuthorView }>(h, "POST", "/authors", { key: key(), body: { slug: "flow-author", name: "Flow Author", monogram: "FA", kind: "person" } });
    const authorId = author.data.author.id;
    // D-024: the lecturer above teaches the course; this institution offers it on its University row.
    const institutionId = (await call<{ author: AuthorView }>(h, "POST", "/authors", { key: key(), body: { slug: "flow-university", name: "Flow University", monogram: "FU", kind: "institution" } })).data.author.id;
    const created = await call<{ course: CourseView }>(h, "POST", "/courses", { key: key(), body: { slug: "flow", authorId, title: "Flow", sourceId: "src-test", licenseCode: "youtube-standard", canonicalUrl: "https://example.org/flow", coverFrom: "own" } });
    const courseId = created.data.course.id;
    const edition = await call<{ edition: { id: string; position: number } }>(h, "POST", `/courses/${courseId}/editions`, { key: key(), body: { slug: "fall-2025", label: "Fall 2025", term: "fall", year: 2025 } });
    expect(edition.data.edition.position).toBe(1);
    const videos = [newVideoId(), newVideoId(), newVideoId()];
    const lessons: string[] = [];
    for (const youtubeId of videos) lessons.push((await call<LessonData>(h, "POST", `/courses/${courseId}/lessons`, { key: key(), body: { editionId: edition.data.edition.id, youtubeId, durationSeconds: 1500 } })).data.lesson.id);
    let revision = (await call<CourseDetail>(h, "GET", `/courses/${courseId}`)).data.course.revision;
    const reordered = await call<{ revision: number }>(h, "PUT", `/courses/${courseId}/lessons/order`, { body: { lessonIds: [lessons[2], lessons[0], lessons[1]], expectedRevision: revision } });
    revision = reordered.data.revision;

    const texts = [
      ...Object.keys(TEXT_FIELDS.course).map((field) => ({ entityKind: "course", entityId: courseId, field, text: `${field.slice(0, 8)} flow`.slice(0, 16), source: "manual", sourceRef: "flow", confidence: "high" })),
      ...lessons.map((lesson, index) => ({ entityKind: "lesson", entityId: lesson, field: "displayTitle", text: `Flow lesson ${String(index + 1)}`, source: "manual", sourceRef: "flow", confidence: "high" })),
    ];
    expect((await call(h, "PUT", "/texts", { body: texts })).status).toBe(200);
    const review = await call(h, "POST", `/courses/${courseId}/status`, { body: { to: "review", expectedRevision: revision } });
    expect((review.body.error?.details as { failed: { rule: string }[] }).failed.map((failure) => failure.rule)).toEqual(["covers.active", "covers.active", "covers.active", "covers.active"]);

    for (const kind of REQUIRED_COVERS) await swapMedia(h.pool, "course", coverInput("course", courseId, kind));
    revision = (await call<{ course: CourseView }>(h, "POST", `/courses/${courseId}/status`, { body: { to: "review", expectedRevision: revision } })).data.course.revision;

    const blocked = await call(h, "POST", `/courses/${courseId}/publish`, { key: key(), body: { expectedRevision: revision, note: "first try" } });
    expect(new Set((blocked.body.error?.details as { failed: { rule: string }[] }).failed.map((failure) => failure.rule))).toEqual(new Set(["area.required", "texts.approved", "rights.status", "home.row"]));

    const detail = await call<CourseDetail>(h, "GET", `/courses/${courseId}`);
    // The reviewer approves exactly the hashes GET /courses/:id showed.
    const toApprove = [
      ...Object.entries(detail.data.texts).map(([field, entry]) => ({ entityKind: "course", entityId: courseId, field, sha256: entry.sha256 })),
      ...detail.data.lessons.map((lesson) => ({ entityKind: "lesson", entityId: lesson.id, field: "displayTitle", sha256: lesson.texts.displayTitle?.sha256 })),
    ];
    expect((await call(h, "POST", "/texts/approve", { key: key(), body: { approvedBy: "Daniel", items: toApprove } })).status).toBe(200);
    revision = (await call<{ course: CourseView }>(h, "PATCH", `/courses/${courseId}`, { body: { expectedRevision: revision, rightsStatus: "cleared", rightsNotes: "Official channel", areaId: "computer-science", subareaId: "programming" } })).data.course.revision;
    const home = await call<HomeData>(h, "GET", "/home");
    const cover = home.data.rows.find((row) => row.id === "picks")?.cover;
    if (!cover) throw new Error("Seed row cover");
    const rows = [...home.data.rows.map((row) => ({ id: row.id, kind: row.kind, ...(row.title ? { title: row.title } : {}), courseIds: row.courseIds })), { id: "flow-row", kind: "curated", institutionId, title: "Flow", cover, courseIds: [courseId] }];
    // The course waits in its Home row while in review: the release records its new institutional row; only published courses appear in it.
    const homeRelease = await call<{ release: { created: boolean } }>(h, "PUT", "/home", { body: { featuredCourseId: home.data.featuredCourseId, rows, expectedRevision: home.data.revision } });
    expect(homeRelease.data.release.created).toBe(true);

    const published = await call<PublicationData>(h, "POST", `/courses/${courseId}/publish`, { key: key(), body: { expectedRevision: revision, note: "Publish flow" } });
    expect(published.data.release).toMatchObject({ number: 3, created: true });
    expect(published.data.diff.lessons.added).toEqual([lessons[2], lessons[0], lessons[1]]);
    expect(published.data.diff.home.changed).toBe(true);
    expect(await healthRelease()).toMatchObject({ release: 3, sha: published.data.release.sha, source: "database" });
    const live = await call<CourseDetail>(h, "GET", `/courses/${courseId}`);
    expect(live.data.course).toMatchObject({ status: "published", publishedAt: expect.any(String) as string });
    expect(live.data.preconditions?.published).toEqual([]);
    expect(live.data.homeRows).toEqual(["flow-row"]);
    await seedProgress(h, lessons[0] ?? "", courseId);

    revision = live.data.course.revision;
    const down = await call<PublicationData>(h, "POST", `/courses/${courseId}/unpublish`, { key: key(), body: { expectedRevision: revision, note: "Unpublish flow" } });
    expect(down.data.release.number).toBe(4);
    expect((await healthRelease()).release).toBe(4);
    revision = (await call<CourseDetail>(h, "GET", `/courses/${courseId}`)).data.course.revision;
    expect((await call<{ course: CourseView }>(h, "DELETE", `/courses/${courseId}?mode=archive&confirm=true&expectedRevision=${String(revision)}`)).data.course.status).toBe("archived");
    revision = (await call<CourseDetail>(h, "GET", `/courses/${courseId}`)).data.course.revision;
    const dry = await call(h, "DELETE", `/courses/${courseId}?mode=purge`);
    expect(dry.data.report).toMatchObject({ lessons: 3, videos: 3, texts: 13, coverAssets: 4, lessonProgressRows: 1, blockedBy: [] });
    const purged = await call<{ bytes: { deleted: string[] } }>(h, "DELETE", `/courses/${courseId}?mode=purge&confirm=true&expectedRevision=${String(revision)}`);
    expect(purged.data.bytes.deleted).toHaveLength(0);
    expect((await call(h, "GET", `/courses/${courseId}`)).status).toBe(404);
    expect((await h.pool.query<Record<string, unknown>>("SELECT count(*)::int AS n FROM lesson_progress WHERE course_id = $1", [courseId])).rows[0]?.n).toBe(1);

    const doctor = await call<DoctorData>(h, "GET", "/doctor");
    expect(doctor.data.ok, JSON.stringify(doctor.data.findings)).toBe(true);
    const retained = Number((await h.pool.query<{ n: string }>("SELECT count(*)::int AS n FROM catalog_releases WHERE NOT is_active")).rows[0]?.n ?? 0);
    expect(doctor.data.operational).toMatchObject({ scope: "process", projectionDriftCount: 0 });
    // Progress of the purged lesson stays, and inactive releases stay restorable.
    expect(doctor.data.findings.map((finding) => [finding.code, finding.severity, finding.count])).toEqual([
      ["progress.orphan", "info", 1],
      ["release.retained", "info", retained],
    ]);
    const actions = (await auditRows(h)).map((row) => row.action);
    for (const action of ["author.create", "course.create", "lesson.create", "lesson.reorder", "text.put", "course.status", "text.approve", "course.update", "course.publish", "release.create", "course.unpublish", "course.delete.archive", "course.delete.purge"]) {
      expect(actions, action).toContain(action);
    }
    expect((await call(h, "POST", "/releases?dryRun=true")).data).toMatchObject({ valid: true, unchanged: true });
  });
});
