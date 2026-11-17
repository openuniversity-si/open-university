import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
vi.mock("server-only", () => ({}));
import { readActiveRelease, resolveCatalog } from "../../src/catalog/server/read.ts";
import type { PublicCatalog } from "../../src/catalog/domain/release.ts";
import {
  activeRelease, auditRows, call, catalogFingerprint, createHarness, insideTransactions, NOW, type CourseDetail, type CourseView, type PublicationData, revisionOf, seedCatalog, seedDraftCourse, type Harness, type Seed,
} from "../fixtures/admin-catalog.ts";

/** The events once the last transaction committed: revalidation must come after it, once. */
const afterLastCommit = (events: readonly string[]) => events.slice(events.map((event) => event.startsWith("COMMIT#")).lastIndexOf(true) + 1);

describe("admin catalog: courses, status, publish and releases on PG18", () => {
  let h: Harness;
  let seed: Seed;
  beforeAll(() => { h = createHarness(); });
  afterAll(async () => { await h.close(); });
  beforeEach(async () => { seed = await seedCatalog(h); });
  const key = () => `k-${Math.random().toString(36).slice(2)}`;

  describe("courses", () => {
    it("creates a draft with a sequence id; a taken slug is 409 slug_taken and an unknown author 422", async () => {
      const created = await call<{ course: CourseView }>(h, "POST", "/courses", { key: key(), body: { slug: "gamma", authorId: seed.authors[0], title: "Gamma", lessonNoun: "Episode", licenseCode: "youtube-standard", coverFrom: "own" } });
      expect(created.status).toBe(201);
      expect(created.data.course).toMatchObject({ slug: "gamma", status: "draft", lessonNoun: "Episode", licenseCode: "youtube-standard", revision: 1 });
      expect(created.data.course.id).toMatch(/^course-\d+$/);
      const taken = await call(h, "POST", "/courses", { key: key(), body: { slug: "alpha", authorId: seed.authors[0], title: "Dup", coverFrom: "own" } });
      expect([taken.status, taken.body.error?.code]).toEqual([409, "slug_taken"]);
      const unknown = await call(h, "POST", "/courses", { key: key(), body: { slug: "delta", authorId: "author-999", title: "X", coverFrom: "own" } });
      expect([unknown.status, unknown.body.error?.code]).toEqual([422, "unprocessable"]);
      // A 4xx did not store the key: the client fixes the body and repeats it.
      const retryKey = key();
      expect((await call(h, "POST", "/courses", { key: retryKey, body: { slug: "alpha", authorId: seed.authors[0], title: "Dup", coverFrom: "own" } })).status).toBe(409);
      expect((await call(h, "POST", "/courses", { key: retryKey, body: { slug: "epsilon", authorId: seed.authors[0], title: "Fixed", coverFrom: "own" } })).status).toBe(201);
    });

    it("lists courses with status, revision, counts and pending rules", async () => {
      const draft = await seedDraftCourse(h, seed, "pending", { ready: false });
      const listed = await call(h, "GET", "/courses");
      const row = (listed.data.courses as { id: string; status: string; counts: { lessons: number }; pending: { target: string; failed: { rule: string }[] } }[]).find((course) => course.id === draft.id);
      expect(row).toMatchObject({ status: "draft", counts: { lessons: 2 }, pending: { target: "review" } });
      expect(new Set(row?.pending.failed.map((failure) => failure.rule))).toEqual(new Set(["texts.required", "covers.active"]));
      expect((await call(h, "GET", "/courses?status=draft")).data.courses).toHaveLength(1);
    });

    it("shows a course with lessons, videos, texts with hashes, active covers, rights and preconditions", async () => {
      const detail = await call<CourseDetail>(h, "GET", `/courses/${seed.courses.alpha}`);
      expect(detail.data.course).toMatchObject({ id: seed.courses.alpha, status: "published", featured: true });
      expect(detail.data.lessons).toHaveLength(3);
      expect(detail.data.lessons[0]?.videos[0]).toMatchObject({ provider: "youtube", status: "ok", checkedBy: "oembed" });
      expect(detail.data.texts.subtitle).toMatchObject({ status: "approved", sha256: expect.stringMatching(/^[a-f0-9]{64}$/) as string });
      expect(detail.data.texts.subtitle?.sha256).toBe(detail.data.texts.subtitle?.approvedSha256);
      expect((detail.data.covers as { kind: string }[]).map((cover) => cover.kind).sort()).toEqual(["hero_desktop_16x9", "hero_mobile_9x16", "hero_present", "poster_9x16"]);
      expect(detail.data.rights).toMatchObject({ licenseCode: "youtube-standard", rightsStatus: "accepted-risk", license: { name: "Standard YouTube License" } });
      expect(detail.data.preconditions).toEqual({ review: [], published: [] });
      expect((await call(h, "GET", "/courses/course-404")).status).toBe(404);
    });

    it("renames a published course with redirects for the course and its lessons; redirects into the old pages follow", async () => {
      await h.pool.query("INSERT INTO slug_redirects (from_path, to_path) VALUES ('/c/older-alpha', '/c/alpha')");
      const revision = await revisionOf(h, "courses", seed.courses.alpha);
      const renamed = await call(h, "PATCH", `/courses/${seed.courses.alpha}`, { body: { expectedRevision: revision, slug: "alpha-two" } });
      expect(renamed.data.course).toMatchObject({ slug: "alpha-two", revision: revision + 1 });
      const { rows } = await h.pool.query<{ from_path: string; to_path: string }>("SELECT from_path, to_path FROM slug_redirects ORDER BY from_path");
      expect(rows).toEqual([
        { from_path: "/c/alpha", to_path: "/c/alpha-two" }, { from_path: "/c/alpha/lesson-1", to_path: "/c/alpha-two/lesson-1" },
        { from_path: "/c/alpha/lesson-2", to_path: "/c/alpha-two/lesson-2" }, { from_path: "/c/alpha/lesson-3", to_path: "/c/alpha-two/lesson-3" },
        { from_path: "/c/older-alpha", to_path: "/c/alpha-two" },
      ]);
      const audit = await auditRows(h, { action: "course.update" });
      expect(audit[0]).toMatchObject({ before: { slug: "alpha" }, after: { slug: "alpha-two" } });
      // Renaming back to a redirect source is refused: delete the redirect first.
      const back = await call(h, "PATCH", `/courses/${seed.courses.beta}`, { body: { expectedRevision: await revisionOf(h, "courses", seed.courses.beta), slug: "older-alpha" } });
      expect([back.status, back.body.error?.code]).toEqual([409, "slug_taken"]);
    });

    it("keeps a published course publishable: dropping its license or rights is 412", async () => {
      const revision = await revisionOf(h, "courses", seed.courses.alpha);
      const response = await call(h, "PATCH", `/courses/${seed.courses.alpha}`, { body: { expectedRevision: revision, licenseCode: null, rightsStatus: "unverified" } });
      expect(response.status).toBe(412);
      expect((response.body.error?.details as { failed: { rule: string }[] }).failed.map((failure) => failure.rule)).toEqual(["rights.fields", "rights.status"]);
      const noop = await call(h, "PATCH", `/courses/${seed.courses.alpha}`, { body: { expectedRevision: revision, title: "alpha" } });
      expect(noop.data.noop).toBe(true);
      expect(await auditRows(h, { action: "course.update" })).toEqual([]);
    });
  });

  describe("status", () => {
    it("moves draft → review only with every precondition, listing all failures", async () => {
      const draft = await seedDraftCourse(h, seed, "unready", { ready: false });
      await h.pool.query("UPDATE courses SET license_code = NULL, rights_status = 'unverified' WHERE id = $1", [draft.id]);
      await h.pool.query("UPDATE lesson_videos SET status = 'unavailable' WHERE lesson_id = $1", [draft.lessons[0]]);
      const refused = await call(h, "POST", `/courses/${draft.id}/status`, { body: { to: "review", expectedRevision: 1 } });
      expect(refused.status).toBe(412);
      const failed = (refused.body.error?.details as { failed: { rule: string; entity: string }[] }).failed;
      expect(new Set(failed.map((failure) => failure.rule))).toEqual(new Set(["videos.ok", "texts.required", "covers.active", "rights.fields"]));
      expect(failed.filter((failure) => failure.rule === "texts.required")).toHaveLength(10);
      expect(failed.filter((failure) => failure.rule === "covers.active")).toHaveLength(4);

      const ready = await seedDraftCourse(h, seed, "ready");
      const moved = await call(h, "POST", `/courses/${ready.id}/status`, { body: { to: "review", expectedRevision: 1 } });
      expect(moved.data.course).toMatchObject({ status: "review", revision: 2 });
      expect(await auditRows(h, { action: "course.status" })).toMatchObject([{ before: { status: "draft" }, after: { status: "review" } }]);
    });

    it("refuses moves outside the matrix with 409 state_conflict, including leaving published", async () => {
      const draft = await seedDraftCourse(h, seed, "matrix");
      await h.pool.query("UPDATE courses SET status = 'archived' WHERE id = $1", [draft.id]);
      const toReview = await call(h, "POST", `/courses/${draft.id}/status`, { body: { to: "review", expectedRevision: 1 } });
      expect([toReview.status, toReview.body.error?.code]).toEqual([409, "state_conflict"]);
      expect(toReview.body.error?.details).toMatchObject({ from: "archived", to: "review", allowed: ["draft"] });
      const fromPublished = await call(h, "POST", `/courses/${seed.courses.alpha}/status`, { body: { to: "draft", expectedRevision: await revisionOf(h, "courses", seed.courses.alpha) } });
      expect([fromPublished.status, fromPublished.body.error?.code]).toEqual([409, "state_conflict"]);
      expect((await call<{ course: CourseView }>(h, "POST", `/courses/${draft.id}/status`, { body: { to: "draft", expectedRevision: 1 } })).data.course.status).toBe("draft");
    });
  });

  describe("publish and unpublish", () => {
    async function reviewCourse(slug: string) {
      const draft = await seedDraftCourse(h, seed, slug);
      await h.pool.query("UPDATE courses SET status = 'review' WHERE id = $1", [draft.id]);
      return draft;
    }

    it("lists every unmet publish precondition: rights, approvals, covers, Home row, lessons and videos", async () => {
      const course = await reviewCourse("blocked");
      await h.pool.query("UPDATE courses SET rights_status = 'unverified' WHERE id = $1", [course.id]);
      await h.pool.query("UPDATE catalog_texts SET status = 'draft', approved_by = NULL, approved_at = NULL, approved_sha256 = NULL WHERE entity_id = $1 AND field IN ('subtitle', 'format')", [course.id]);
      await h.pool.query("UPDATE catalog_media SET is_active = false WHERE owner_kind = 'course' AND owner_id = $1 AND kind = 'hero_present'", [course.id]);
      await h.pool.query("UPDATE lesson_videos SET status = 'embed-disabled' WHERE lesson_id = $1", [course.lessons[1]]);
      const before = await catalogFingerprint(h);
      const response = await call<PublicationData>(h, "POST", `/courses/${course.id}/publish`, { key: key(), body: { expectedRevision: 1, note: "try" } });
      expect(response.status).toBe(412);
      const failed = (response.body.error?.details as { failed: { rule: string; entity: string; message: string }[] }).failed;
      expect(failed.map((failure) => `${failure.rule} ${failure.entity}`).sort()).toEqual([
        `covers.active course:${course.id}`, `home.row course:${course.id}`, `rights.status course:${course.id}`,
        `texts.approved course:${course.id}`, `texts.approved course:${course.id}`, `videos.ok lesson:${course.lessons[1] ?? ""}`,
      ].sort());
      expect(await catalogFingerprint(h)).toBe(before);

      const empty = await reviewCourse("no-lessons");
      await h.pool.query("DELETE FROM catalog_texts WHERE entity_kind = 'lesson' AND entity_id = ANY($1)", [empty.lessons]);
      await h.pool.query("DELETE FROM lesson_videos WHERE lesson_id = ANY($1)", [empty.lessons]);
      await h.pool.query("DELETE FROM lessons WHERE course_id = $1", [empty.id]);
      const noLessons = await call<PublicationData>(h, "POST", `/courses/${empty.id}/publish`, { key: key(), body: { expectedRevision: 1, note: "try", allowOrphan: true } });
      expect((noLessons.body.error?.details as { failed: { rule: string }[] }).failed.map((failure) => failure.rule)).toEqual(["lessons.visible", "editions.lessons"]);
    });

    it("publishes: compiles, activates, revalidates once after the commit, and the health read shows it", async () => {
      const course = await reviewCourse("shipping");
      await h.pool.query("INSERT INTO home_row_items (row_id, course_id, position) VALUES ('picks', $1, 3)", [course.id]);
      const previous = await h.pool.query<{ payload: unknown }>("SELECT payload FROM catalog_releases WHERE number = 1");
      h.recorder.events.length = 0;
      const published = await call<PublicationData>(h, "POST", `/courses/${course.id}/publish`, { key: key(), body: { expectedRevision: 1, note: "Ship it" } });
      expect(published.status).toBe(200);
      expect(published.data.release).toMatchObject({ number: 2, created: true, counts: { courses: 3, lessons: 7 } });
      expect(published.data.diff.courses.added).toEqual([course.id]);
      expect(published.data.diff.lessons.added).toEqual(course.lessons);
      expect(await activeRelease(h)).toMatchObject({ number: 2 });
      expect(h.recorder.events.filter((event) => event === "invalidate")).toHaveLength(1);
      expect(afterLastCommit(h.recorder.events)).toEqual(["invalidate"]);
      expect(h.logs.filter((line) => line.includes("CATALOG_RELEASE_ACTIVATED"))).toEqual([JSON.stringify({ event: "CATALOG_RELEASE_ACTIVATED", number: 2, sha: published.data.release.sha })]);
      // /api/health reads getCatalogState: once the tag expired, the same process resolves the new release.
      const state = await resolveCatalog(() => readActiveRelease(h.pool), {});
      expect([state.catalog.number, state.sha, state.source]).toEqual([2, published.data.release.sha, "database"]);
      expect((await h.pool.query<Record<string, unknown>>("SELECT payload FROM catalog_releases WHERE number = 1")).rows[0]).toEqual(previous.rows[0]);
      const course2 = await h.pool.query<Record<string, unknown>>("SELECT status, published_at FROM courses WHERE id = $1", [course.id]);
      expect(course2.rows[0]).toMatchObject({ status: "published" });
      expect((await auditRows(h, { action: "course.publish" }))[0]).toMatchObject({ release_number: 2, before: { status: "review" } });
      expect((await auditRows(h, { action: "release.create" }))[0]).toMatchObject({ release_number: 2 });

      // Publishing it again without changes creates nothing.
      const again = await call<PublicationData>(h, "POST", `/courses/${course.id}/publish`, { key: key(), body: { expectedRevision: await revisionOf(h, "courses", course.id), note: "again" } });
      expect(again.data).toMatchObject({ noop: true, release: { number: 2, created: false } });
      expect(await activeRelease(h)).toMatchObject({ number: 2 });

      // Rollback by activating release 1 restores it.
      const rollback = await call(h, "POST", "/releases/1/activate", { key: key(), body: { note: "rollback" } });
      expect(rollback.data).toMatchObject({ release: { number: 1 }, previous: 2 });
      expect(await activeRelease(h)).toMatchObject({ number: 1 });
      expect((await resolveCatalog(() => readActiveRelease(h.pool), {})).catalog.number).toBe(1);
    });

    it("redoes oEmbed for videos checked more than 7 days ago, outside the transaction; a failing one is 412", async () => {
      const course = await reviewCourse("stale-embeds");
      const old = new Date(NOW.getTime() - 8 * 86_400_000).toISOString();
      await h.pool.query("UPDATE lesson_videos SET checked_at = $2 WHERE lesson_id = ANY($1)", [course.lessons, old]);
      const ids = (await h.pool.query<{ external_id: string }>("SELECT external_id FROM lesson_videos WHERE lesson_id = ANY($1) ORDER BY lesson_id", [course.lessons])).rows.map((row) => row.external_id);
      h.embeds.set(ids[0] ?? "", "unavailable");
      h.recorder.events.length = 0;
      const refused = await call<PublicationData>(h, "POST", `/courses/${course.id}/publish`, { key: key(), body: { expectedRevision: 1, note: "x", allowOrphan: true } });
      expect(refused.status).toBe(412);
      expect((refused.body.error?.details as { failed: { rule: string }[] }).failed.map((failure) => failure.rule)).toEqual(["videos.fresh"]);
      expect(h.recorder.events.filter((event) => event.startsWith("oembed:"))).toHaveLength(2);
      expect(insideTransactions(h.recorder.events, (event) => event.startsWith("oembed:"))).toEqual([]);

      h.embeds.clear();
      const published = await call<PublicationData>(h, "POST", `/courses/${course.id}/publish`, { key: key(), body: { expectedRevision: 1, note: "x", allowOrphan: true } });
      expect(published.data.release.number).toBe(2);
      const { rows } = await h.pool.query<{ checked_at: Date }>("SELECT checked_at FROM lesson_videos WHERE lesson_id = ANY($1)", [course.lessons]);
      expect(rows.every((row) => row.checked_at.toISOString() === NOW.toISOString())).toBe(true);
    });

    it("refuses to publish a draft (409) and unpublishes into a new release without the course", async () => {
      const draft = await seedDraftCourse(h, seed, "not-in-review");
      const refused = await call<PublicationData>(h, "POST", `/courses/${draft.id}/publish`, { key: key(), body: { expectedRevision: 1, note: "x" } });
      expect([refused.status, refused.body.error?.code]).toEqual([409, "state_conflict"]);

      h.recorder.events.length = 0;
      const down = await call<PublicationData>(h, "POST", `/courses/${seed.courses.beta}/unpublish`, { key: key(), body: { expectedRevision: await revisionOf(h, "courses", seed.courses.beta), note: "down" } });
      expect(down.data.release).toMatchObject({ number: 2, created: true });
      expect(down.data.diff.courses.removed).toEqual([seed.courses.beta]);
      expect(afterLastCommit(h.recorder.events)).toEqual(["invalidate"]);
      expect((await h.pool.query<Record<string, unknown>>("SELECT status FROM courses WHERE id = $1", [seed.courses.beta])).rows[0]?.status).toBe("draft");
      const payload = (await h.pool.query<{ payload: { home: { rows: { id: string; courseIds: string[] }[] } } }>("SELECT payload FROM catalog_releases WHERE is_active")).rows[0]?.payload;
      expect(payload?.home.rows.find((row) => row.id === "picks")?.courseIds).toEqual([seed.courses.alpha]);
    });

    it("needs a published replacement to unpublish the featured course", async () => {
      const revision = await revisionOf(h, "courses", seed.courses.alpha);
      const refused = await call<PublicationData>(h, "POST", `/courses/${seed.courses.alpha}/unpublish`, { key: key(), body: { expectedRevision: revision, note: "x" } });
      expect([refused.status, refused.body.error?.code]).toEqual([409, "state_conflict"]);
      const draft = await seedDraftCourse(h, seed, "not-published");
      const wrong = await call<PublicationData>(h, "POST", `/courses/${seed.courses.alpha}/unpublish`, { key: key(), body: { expectedRevision: revision, note: "x", replacementFeaturedId: draft.id } });
      expect([wrong.status, wrong.body.error?.code]).toEqual([422, "unprocessable"]);
      const done = await call<PublicationData>(h, "POST", `/courses/${seed.courses.alpha}/unpublish`, { key: key(), body: { expectedRevision: revision, note: "x", replacementFeaturedId: seed.courses.beta, to: "archived" } });
      expect(done.status).toBe(200);
      const active = (await h.pool.query<{ payload: { home: { featuredCourseId: string }; courses: { id: string; featured: boolean }[] } }>("SELECT payload FROM catalog_releases WHERE is_active")).rows[0]?.payload;
      expect(active?.home.featuredCourseId).toBe(seed.courses.beta);
      expect(active?.courses.map((course) => course.id)).toEqual([seed.courses.beta]);
      expect((await h.pool.query<Record<string, unknown>>("SELECT status FROM courses WHERE id = $1", [seed.courses.alpha])).rows[0]?.status).toBe("archived");
    });
  });

  describe("releases", () => {
    it("dry-runs the tables against the active release without writing: empty diff on the seed, the edit otherwise", async () => {
      const before = await catalogFingerprint(h);
      const clean = await call(h, "POST", "/releases?dryRun=true");
      expect(clean.data).toMatchObject({ valid: true, errors: [], unchanged: true, diff: { empty: true } });
      await h.pool.query("UPDATE lessons SET visible = false WHERE id = $1", [seed.lessons.alpha[2]]);
      const edited = await call(h, "POST", "/releases?dryRun=true");
      expect(edited.data).toMatchObject({ valid: true, unchanged: false, diff: { empty: false, lessons: { removed: [seed.lessons.alpha[2]] } } });
      await h.pool.query("UPDATE lessons SET visible = true WHERE id = $1", [seed.lessons.alpha[2]]);
      expect(await catalogFingerprint(h)).toBe(before);
    });

    it("keeps the active release when the tables do not compile (422) and reports it in the dry run", async () => {
      await h.pool.query("UPDATE lessons SET visible = false WHERE course_id = $1", [seed.courses.beta]);
      const dry = await call<{ valid: boolean; errors: string[] }>(h, "POST", "/releases?dryRun=true");
      expect(dry.data.valid).toBe(false);
      expect(dry.data.errors.length).toBeGreaterThan(0);
      h.recorder.events.length = 0;
      const refused = await call(h, "POST", "/releases", { key: key(), body: { note: "broken" } });
      expect([refused.status, refused.body.error?.code]).toEqual([422, "unprocessable"]);
      expect(await activeRelease(h)).toMatchObject({ number: 1 });
      expect((await h.pool.query<Record<string, unknown>>("SELECT count(*)::int AS n FROM catalog_releases")).rows[0]?.n).toBe(1);
      expect(h.recorder.events).not.toContain("invalidate");
    });

    it("creates MAX+1 and activates it, lists releases lightly and shows one in full; activating the active one is a noop", async () => {
      await h.pool.query("UPDATE home_rows SET title = 'Top picks' WHERE id = 'picks'");
      const created = await call<PublicationData>(h, "POST", "/releases", { key: key(), body: { note: "Rename row" } });
      expect([created.status, created.data.release.number, created.data.diff.home.changed]).toEqual([201, 2, true]);
      const list = await call<{ releases: { number: number; isActive: boolean; note: string }[] }>(h, "GET", "/releases");
      expect(list.data.releases.map((release) => [release.number, release.isActive, release.note])).toEqual([[2, true, "Rename row"], [1, false, "seed"]]);
      expect(list.data.releases[0]).not.toHaveProperty("payload");
      expect((await call<{ release: { payload: PublicCatalog } }>(h, "GET", "/releases/2")).data.release.payload.home.rows[1]?.title).toBe("Top picks");
      expect((await call(h, "GET", "/releases/9")).status).toBe(404);
      const noop = await call(h, "POST", "/releases/2/activate", { key: key(), body: { note: "again" } });
      expect(noop.data).toMatchObject({ noop: true });
      expect((await call(h, "POST", "/releases/9/activate", { key: key(), body: { note: "x" } })).status).toBe(404);
      const nothingNew = await call(h, "POST", "/releases", { key: key(), body: { note: "same" } });
      expect([nothingNew.status, nothingNew.data.noop]).toEqual([200, true]);
    });

    it("never updates a release payload: the API sends no such UPDATE and the database refuses one", async () => {
      await h.pool.query("UPDATE home_rows SET title = 'Top picks' WHERE id = 'picks'");
      await call(h, "POST", "/releases", { key: key(), body: { note: "r2" } });
      await call(h, "POST", "/releases/1/activate", { key: key(), body: { note: "back" } });
      await call(h, "POST", "/releases/2/activate", { key: key(), body: { note: "forward" } });
      const updates = h.recorder.statements.filter((sql) => /UPDATE\s+catalog_releases/i.test(sql));
      expect(updates.length).toBeGreaterThan(0);
      expect(updates.every((sql) => /SET is_active = (true|false)(, activated_at = now\(\))? WHERE/.test(sql) && !/payload/i.test(sql.split("WHERE")[0] ?? ""))).toBe(true);
      await expect(h.pool.query("UPDATE catalog_releases SET payload = '{}'::jsonb WHERE number = 1")).rejects.toMatchObject({ code: "55000" });
      await expect(h.pool.query("DELETE FROM catalog_releases WHERE number = 1")).rejects.toMatchObject({ code: "55000" });
      expect((await h.pool.query<Record<string, unknown>>("SELECT count(*)::int AS n FROM catalog_releases WHERE is_active")).rows[0]?.n).toBe(1);
    });
  });
});
