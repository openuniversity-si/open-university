import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { drainPendingObjects } from "../../src/catalog/server/deletion.ts";
import { REQUIRED_COVERS } from "../../src/catalog/domain/rules/status.ts";
import { swapMedia } from "../../src/media/server/repository.ts";
import {
  activeRelease, auditRows, call, catalogFingerprint, coverInput, createHarness, insideTransactions, revisionOf, seedCatalog, seedDraftCourse, seedProgress,
  type AuthorView, type DeleteReportData, type DoctorData, type Harness, type PublicationData, type ReleaseData, type Seed,
} from "../fixtures/admin-catalog.ts";

const byteQuery = (keys: readonly string[]) => `&deleteBytes=true&checkedKeys=${encodeURIComponent(JSON.stringify(keys))}`;

describe("admin catalog: course and author deletes on PG18", () => {
  let h: Harness;
  let seed: Seed;
  beforeAll(() => { h = createHarness(); });
  afterAll(async () => { await h.close(); });
  beforeEach(async () => { seed = await seedCatalog(h); });

  /** A draft course with a lesson cover, a progress row, a Home item, an import and a redirect into it. */
  async function loadedDraft(slug: string) {
    const draft = await seedDraftCourse(h, seed, slug, { lessons: 2 });
    await swapMedia(h.pool, "lesson", coverInput("lesson", draft.lessons[0] ?? "", "cover_16x9"));
    await seedProgress(h, draft.lessons[0] ?? "", draft.id);
    await h.pool.query("INSERT INTO home_row_items (row_id, course_id, position) VALUES ('picks', $1, 3)", [draft.id]);
    await h.pool.query(`INSERT INTO catalog_imports (id, playlist_id, source_url, tool, fetched_at, items, report, course_id, status)
      VALUES ('import-PLx-202610110000', 'PLx', 'https://www.youtube.com/playlist?list=PLx', 'test', now(), '[]', '{}', $1, 'drafted')`, [draft.id]);
    await h.pool.query("INSERT INTO slug_redirects (from_path, to_path) VALUES ($1, $2)", [`/c/old-${slug}`, `/c/${slug}`]);
    const keys = [
      ...REQUIRED_COVERS.map((kind) => coverInput("course", draft.id, kind).pathname),
      coverInput("lesson", draft.lessons[0] ?? "", "cover_16x9").pathname,
    ].sort();
    return { ...draft, keys };
  }
  const counts = async (courseId: string, lessons: readonly string[]) => (await h.pool.query<Record<string, unknown>>(`SELECT
    (SELECT count(*)::int FROM courses WHERE id = $1) AS courses, (SELECT count(*)::int FROM lessons WHERE course_id = $1) AS lessons,
    (SELECT count(*)::int FROM lesson_videos WHERE lesson_id = ANY($2)) AS videos,
    (SELECT count(*)::int FROM catalog_texts WHERE entity_id = $1 OR entity_id = ANY($2)) AS texts,
    (SELECT count(*)::int FROM home_row_items WHERE course_id = $1) AS items, (SELECT count(*)::int FROM catalog_media WHERE owner_kind = 'course' AND owner_id = $1) AS covers,
    (SELECT count(*)::int FROM catalog_media WHERE owner_kind = 'lesson' AND owner_id = ANY($2)) AS lesson_covers, (SELECT count(*)::int FROM lesson_progress WHERE lesson_id = ANY($2)) AS progress`,
  [courseId, lessons])).rows[0];

  describe("DELETE /courses/:id", () => {
    it("dry-runs a purge with the exact report and changes nothing", async () => {
      const draft = await loadedDraft("doomed");
      const before = await catalogFingerprint(h);
      const dry = await call<DeleteReportData>(h, "DELETE", `/courses/${draft.id}?mode=purge${byteQuery(draft.keys)}`);
      expect(dry.data).toEqual({
        dryRun: true,
        report: {
          mode: "purge", course: { id: draft.id, slug: "doomed", status: "draft", publishedAt: null, featured: false, revision: 1 },
          editions: 1, lessons: 2, videos: 2, texts: 12, homeRowItems: 1, coverAssets: 4, lessonAssets: 1, r2Candidates: draft.keys, r2Objects: draft.keys, keptBytes: [], lessonProgressRows: 1,
          redirects: [{ from: "/c/old-doomed", to: "/c/doomed" }], blockedBy: [],
        },
      });
      expect(await catalogFingerprint(h)).toBe(before);
      expect((await call(h, "DELETE", `/courses/${draft.id}?mode=purge${byteQuery(draft.keys)}`)).data).toEqual(dry.data);
    });

    it("purges in one transaction, keeps lesson_progress, nulls the import and removes bytes only after the commit", async () => {
      const draft = await loadedDraft("doomed");
      h.recorder.events.length = 0;
      const purged = await call(h, "DELETE", `/courses/${draft.id}?mode=purge&confirm=true&expectedRevision=1${byteQuery(draft.keys)}`);
      expect(purged.data).toMatchObject({ dryRun: false, purged: true, bytes: { deleted: [], pending: [...draft.keys].sort() }, report: { lessons: 2, lessonProgressRows: 1 } });
      expect(await counts(draft.id, draft.lessons)).toEqual({ courses: 0, lessons: 0, videos: 0, texts: 0, items: 0, covers: 0, lesson_covers: 0, progress: 1 });
      expect((await h.pool.query<Record<string, unknown>>("SELECT course_id FROM catalog_imports")).rows).toEqual([{ course_id: null }]);
      expect((await h.pool.query<Record<string, unknown>>("SELECT count(*)::int AS n FROM slug_redirects")).rows[0]?.n).toBe(0);
      const commitAt = h.recorder.events.findIndex((event) => event.startsWith("COMMIT#"));
      expect(commitAt).toBeGreaterThanOrEqual(0);
      expect(h.recorder.events.filter((event) => event.startsWith("r2:delete:"))).toEqual([]);
      expect(insideTransactions(h.recorder.events, (event) => event.startsWith("r2:"))).toEqual([]);
      // A purged course was never in the active release: no media tag expires (src/media/domain/tags.ts).
      expect(h.recorder.events.filter((event) => event.startsWith("media:"))).toEqual([]);
      expect((await auditRows(h, { action: "course.delete.purge" }))[0]).toMatchObject({ after: { purged: true, r2Pending: draft.keys } });
      // Re-running is idempotent: the course is gone.
      expect((await call(h, "DELETE", `/courses/${draft.id}?mode=purge&confirm=true&expectedRevision=1`)).data).toMatchObject({ alreadyPurged: true, purged: true });
      const doctor = await call<DoctorData>(h, "GET", "/doctor");
      expect(doctor.data.findings.find((finding: { code: string }) => finding.code === "progress.orphan")).toMatchObject({ count: 1, sample: [draft.lessons[0]] });
    });

    it("keeps every byte by default (the bucket is shared with the other environment)", async () => {
      const draft = await loadedDraft("default-keep");
      const dry = await call<DeleteReportData>(h, "DELETE", `/courses/${draft.id}?mode=purge`);
      expect([dry.data.report.r2Candidates, dry.data.report.r2Objects, dry.data.report.keptBytes]).toEqual([draft.keys, [], draft.keys]);
      const purged = await call(h, "DELETE", `/courses/${draft.id}?mode=purge&confirm=true&expectedRevision=1`);
      expect(purged.data).toMatchObject({ dryRun: false, purged: true, bytes: { deleted: [], pending: [] } });
      expect(h.recorder.events.filter((event) => event.startsWith("r2:delete:"))).toEqual([]);
      expect(h.store.deleted).toEqual([]);
    });

    it("never drains unchecked pending bytes or newly referenced keys", async () => {
      const draft = await loadedDraft("queued");
      const checked = "covers/unused/poster_9x16/checked.jpg";
      const unchecked = "covers/unused/poster_9x16/unchecked.jpg";
      const referenced = draft.keys[0] ?? "";
      for (const key of [checked, unchecked, referenced]) await h.pool.query("INSERT INTO r2_pending_deletions (key, owner_kind, owner_id, course_id, request_id) VALUES ($1, 'course', $2, $2, 'test')", [key, draft.id]);
      expect(await drainPendingObjects(h.pool, () => h.store, { courseId: draft.id })).toEqual({ deleted: [], pending: [] });
      expect(await drainPendingObjects(h.pool, () => h.store, { courseId: draft.id }, [checked, referenced])).toEqual({ deleted: [], pending: [checked] });
      expect(h.store.deleted).toEqual([]);
      expect((await h.pool.query<{ key: string }>("SELECT key FROM r2_pending_deletions ORDER BY key")).rows.map((row) => row.key)).toEqual([checked, referenced, unchecked].sort());
    });

    it("answers which keys this database still uses (POST /media/references)", async () => {
      const draft = await loadedDraft("referenced");
      const answer = await call<{ used: string[] }>(h, "POST", "/media/references", { body: { keys: [...draft.keys, "covers/nobody/poster_9x16/none.jpg"] } });
      expect(answer.data.used).toEqual([...draft.keys].sort());
    });

    it("keeps bytes another row still uses, and all bytes without deleteBytes", async () => {
      const draft = await loadedDraft("shared");
      const shared = coverInput("course", draft.id, "poster_9x16");
      await h.pool.query(`INSERT INTO catalog_media (id, owner_kind, owner_id, kind, variant, url, pathname, width, height, sha256, alt, design_status, version, is_active)
        SELECT gen_random_uuid()::text, 'course', $2, kind, 'alt', url, pathname, width, height, sha256, alt, design_status, 1, true FROM catalog_media WHERE pathname = $1`, [shared.pathname, seed.courses.beta]);
      const dry = await call<DeleteReportData>(h, "DELETE", `/courses/${draft.id}?mode=purge${byteQuery(draft.keys)}`);
      expect(dry.data.report.keptBytes).toEqual([shared.pathname]);
      expect(dry.data.report.r2Objects).not.toContain(shared.pathname);
      const kept = await call<DeleteReportData>(h, "DELETE", `/courses/${draft.id}?mode=purge`);
      expect([kept.data.report.r2Objects, kept.data.report.keptBytes.length]).toEqual([[], 5]);
    });

    it("refuses to purge a published course, or one published before, with 409 state_conflict", async () => {
      const published = await call(h, "DELETE", `/courses/${seed.courses.beta}?mode=purge&confirm=true&expectedRevision=${String(await revisionOf(h, "courses", seed.courses.beta))}`);
      expect([published.status, published.body.error?.code]).toEqual([409, "state_conflict"]);
      const draft = await seedDraftCourse(h, seed, "was-live");
      await h.pool.query("UPDATE courses SET published_at = now() WHERE id = $1", [draft.id]);
      expect((await call<DeleteReportData>(h, "DELETE", `/courses/${draft.id}?mode=purge`)).data.report.blockedBy).toHaveLength(1);
      const before = await catalogFingerprint(h);
      expect((await call(h, "DELETE", `/courses/${draft.id}?mode=purge&confirm=true&expectedRevision=1`)).body.error?.code).toBe("state_conflict");
      expect(await catalogFingerprint(h)).toBe(before);
    });

    it("archives a published course into a new release without it, then purges the archived course", async () => {
      const revision = await revisionOf(h, "courses", seed.courses.beta);
      h.recorder.events.length = 0;
      const archived = await call(h, "DELETE", `/courses/${seed.courses.beta}?mode=archive&confirm=true&expectedRevision=${String(revision)}`);
      expect(archived.data).toMatchObject({ archived: true, release: { number: 2, created: true }, diff: { courses: { removed: [seed.courses.beta] } } });
      expect(h.recorder.events.filter((event) => event === "invalidate")).toHaveLength(1);
      expect((await auditRows(h, { action: "course.delete.archive" }))[0]).toMatchObject({ release_number: 2, after: { status: "archived" } });
      expect(await activeRelease(h)).toMatchObject({ number: 2 });
      const again = await call(h, "DELETE", `/courses/${seed.courses.beta}?mode=archive&confirm=true&expectedRevision=${String(await revisionOf(h, "courses", seed.courses.beta))}`);
      expect(again.data).toMatchObject({ archived: true, noop: true });
      const purged = await call(h, "DELETE", `/courses/${seed.courses.beta}?mode=purge&confirm=true&expectedRevision=${String(await revisionOf(h, "courses", seed.courses.beta))}`);
      expect(purged.data.purged).toBe(true);
      expect((await h.pool.query<Record<string, unknown>>("SELECT count(*)::int AS n FROM lessons WHERE course_id = $1", [seed.courses.beta])).rows[0]?.n).toBe(0);
      // The release that held it is untouched.
      expect((await call<ReleaseData>(h, "GET", "/releases/1")).data.release.payload.courses.map((course: { id: string }) => course.id)).toContain(seed.courses.beta);
    });

    it("archives a draft without a release, and needs a replacement to archive the featured course", async () => {
      const draft = await seedDraftCourse(h, seed, "shelved");
      const archived = await call(h, "DELETE", `/courses/${draft.id}?mode=archive&confirm=true&expectedRevision=1`);
      expect(archived.data).toMatchObject({ archived: true, course: { status: "archived" } });
      expect(await activeRelease(h)).toMatchObject({ number: 1 });
      const revision = await revisionOf(h, "courses", seed.courses.alpha);
      expect((await call<DeleteReportData>(h, "DELETE", `/courses/${seed.courses.alpha}?mode=archive`)).data.report.blockedBy).toEqual([{ rule: "featured", message: "The course is featured: pass replacementFeaturedId." }]);
      const refused = await call(h, "DELETE", `/courses/${seed.courses.alpha}?mode=archive&confirm=true&expectedRevision=${String(revision)}`);
      expect([refused.status, refused.body.error?.code]).toEqual([409, "state_conflict"]);
      const done = await call<PublicationData>(h, "DELETE", `/courses/${seed.courses.alpha}?mode=archive&confirm=true&expectedRevision=${String(revision)}&replacementFeaturedId=${seed.courses.beta}`);
      expect(done.data.release.number).toBe(2);
      expect((await h.pool.query<Record<string, unknown>>("SELECT id FROM courses WHERE featured")).rows).toEqual([{ id: seed.courses.beta }]);
    });

    it("finishes a purge whose R2 delete failed: 502 with pending keys, doctor reports them, re-running completes", async () => {
      const draft = await loadedDraft("flaky");
      const failing = draft.keys[0] ?? "";
      h.store.failing.add(failing);
      const held = await call(h, "DELETE", `/courses/${draft.id}?mode=purge&confirm=true&expectedRevision=1${byteQuery(draft.keys)}`);
      expect(held.data).toMatchObject({ dryRun: false, purged: true, bytes: { deleted: [], pending: [...draft.keys].sort() } });
      expect((await counts(draft.id, draft.lessons))?.courses).toBe(0);
      expect((await auditRows(h, { entity: `course:${draft.id}` })).at(-1)?.after).toEqual({ r2Completed: [], r2Pending: [...draft.keys].sort() });
      const doctor = await call<DoctorData>(h, "GET", "/doctor");
      expect(doctor.data.findings.find((finding: { code: string }) => finding.code === "r2.pending")).toMatchObject({ count: draft.keys.length, severity: "warning" });
      expect((await h.pool.query<Record<string, unknown>>("SELECT attempts, last_error FROM r2_pending_deletions ORDER BY key")).rows).toEqual([...draft.keys].sort().map(() => ({ attempts: 1, last_error: "retention" })));
      h.store.failing.clear();
      expect((await call(h, "DELETE", `/courses/${draft.id}?mode=purge`)).data).toEqual({ dryRun: true, alreadyPurged: true, r2Pending: draft.keys.length, report: { r2Candidates: [...draft.keys].sort() } });
      const kept = await call(h, "DELETE", `/courses/${draft.id}?mode=purge&confirm=true`);
      expect(kept.data).toMatchObject({ bytes: { deleted: [], pending: [] } });
      expect(h.store.deleted).not.toContain(failing);
      const finished = await call(h, "DELETE", `/courses/${draft.id}?mode=purge&confirm=true${byteQuery(draft.keys)}`);
      expect(finished.data).toMatchObject({ purged: true, alreadyPurged: true, bytes: { deleted: [], pending: [...draft.keys].sort() } });
      expect((await call<DoctorData>(h, "GET", "/doctor")).data.findings.map((finding: { code: string }) => finding.code)).toContain("r2.pending");
      expect((await call(h, "DELETE", `/courses/${draft.id}?mode=purge&confirm=true`)).data).toMatchObject({ alreadyPurged: true });
      expect((await call(h, "DELETE", `/courses/${draft.id}?mode=archive&confirm=true&expectedRevision=1`)).status).toBe(404);
    });

    it("needs mode, and expectedRevision with confirm", async () => {
      expect((await call(h, "DELETE", `/courses/${seed.courses.beta}`)).status).toBe(400);
      expect((await call(h, "DELETE", `/courses/${seed.courses.beta}?mode=purge&confirm=true`)).status).toBe(400);
      expect((await call(h, "DELETE", "/courses/course-404?mode=purge")).status).toBe(404);
    });
  });

  describe("authors", () => {
    it("lists authors with their dependents and refuses to delete one in use (409 has_dependents with the list)", async () => {
      const list = await call<{ authors: (AuthorView & { courses: number })[] }>(h, "GET", "/authors");
      expect(list.data.authors.map((author) => [author.id, author.courses])).toEqual([[seed.authors[0], 2], [seed.authors[1], 0], [seed.institution, 2]]);
      await swapMedia(h.pool, "institution", coverInput("institution", seed.authors[0], "author_cover_9x16"));
      await h.pool.query("INSERT INTO home_rows (id, kind, author_id, position) VALUES ('by-ann', 'author', $1, 3)", [seed.authors[0]]);
      const dry = await call(h, "DELETE", `/authors/${seed.authors[0]}`);
      expect(dry.data.report).toMatchObject({ dependents: { courses: [seed.courses.alpha, seed.courses.beta], homeRows: ["by-ann"] }, blockedBy: [{ rule: "has_dependents" }] });
      const refused = await call(h, "DELETE", `/authors/${seed.authors[0]}?confirm=true&expectedRevision=1`);
      expect([refused.status, refused.body.error?.code, refused.body.error?.details]).toEqual([409, "has_dependents", { courses: [seed.courses.alpha, seed.courses.beta], homeRows: ["by-ann"] }]);
      const institution = await call(h, "DELETE", `/authors/${seed.institution}`);
      expect(institution.data.report).toMatchObject({ dependents: { courses: [seed.courses.alpha, seed.courses.beta], homeRows: ["picks"] }, blockedBy: [{ rule: "has_dependents" }] });
    });

    it("dry-runs and deletes a free author with its texts", async () => {
      await h.pool.query("INSERT INTO catalog_texts (entity_kind, entity_id, field, text, source, source_ref, confidence) VALUES ('author', $1, 'bio', 'Bio', 'manual', 'x', 'high')", [seed.authors[1]]);
      const before = await catalogFingerprint(h);
      expect((await call(h, "DELETE", `/authors/${seed.authors[1]}`)).data).toMatchObject({ dryRun: true, report: { texts: 1, blockedBy: [] } });
      expect(await catalogFingerprint(h)).toBe(before);
      expect((await call(h, "DELETE", `/authors/${seed.authors[1]}?confirm=true`)).status).toBe(400);
      expect((await call(h, "DELETE", `/authors/${seed.authors[1]}?confirm=true&expectedRevision=1`)).data).toMatchObject({ deleted: true });
      expect((await h.pool.query<Record<string, unknown>>("SELECT count(*)::int AS n FROM catalog_texts WHERE entity_kind = 'author'")).rows[0]?.n).toBe(0);
      expect((await call(h, "DELETE", `/authors/${seed.authors[1]}`)).status).toBe(404);
    });

    it("creates and renames authors; a taken slug is 409 slug_taken; an unchanged patch is a noop", async () => {
      const created = await call(h, "POST", "/authors", { key: "author-a", body: { slug: "cy-three", name: "Cy Three", monogram: "CT", kind: "institution" } });
      expect(created.data.author).toMatchObject({ slug: "cy-three", role: "Lecturer", kind: "institution", revision: 1 });
      expect((await call(h, "POST", "/authors", { key: "author-b", body: { slug: "ann-one", name: "Dup", monogram: "D", kind: "person" } })).body.error?.code).toBe("slug_taken");
      const taken = await call(h, "PATCH", `/authors/${seed.authors[1]}`, { body: { expectedRevision: 1, slug: "ann-one" } });
      expect([taken.status, taken.body.error?.code]).toEqual([409, "slug_taken"]);
      expect((await call(h, "PATCH", `/authors/${seed.authors[1]}`, { body: { expectedRevision: 1, name: "Bob Two" } })).data.noop).toBe(true);
    });
  });
});
