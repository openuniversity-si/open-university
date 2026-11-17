import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { cleanLessonSlug, cleanTitle } from "../../src/catalog/domain/lesson-address.ts";
import { lessonBySlug } from "../../src/catalog/domain/queries.ts";
import { signedInHome } from "../../src/catalog/domain/home.ts";
import { catalogProgressViews } from "../../src/catalog/server/progress-reading.ts";
import type { PublicCatalog } from "../../src/catalog/domain/release.ts";
import { lessonMetadataInput } from "../../src/catalog/server/metadata.ts";
import { publicRouteSnapshot } from "../../src/catalog/server/public-routes.ts";
import { lessonStartSecond } from "../../src/progress/domain/rules.ts";
import { readProgress } from "../../src/progress/server/repo.ts";
import { publicPaths } from "../../src/site/domain/route-registry.ts";
import {
  auditRows, call, catalogFingerprint, coverInput, createHarness, insideTransactions, newVideoId, revisionOf, seedCatalog, seedDraftCourse, seedLesson, seedProgress, type DeleteReportData, type DoctorData, type Harness, type LessonData, type PublicationData, type ReleaseData, type Seed,
} from "../fixtures/admin-catalog.ts";
import { swapMedia } from "../../src/media/server/repository.ts";

describe("admin catalog: lessons, reorder and deletes on PG18", () => {
  let h: Harness;
  let seed: Seed;
  beforeAll(() => { h = createHarness(); });
  afterAll(async () => { await h.close(); });
  beforeEach(async () => { seed = await seedCatalog(h); });
  const key = () => `k-${Math.random().toString(36).slice(2)}`;
  const positions = async (courseId: string) => (await h.pool.query<{ id: string; position: number }>("SELECT id, position FROM lessons WHERE course_id = $1 ORDER BY position", [courseId])).rows;

  describe("POST /courses/:id/lessons", () => {
    it("adds a lesson after a positive oEmbed check made outside the transaction, at the end by default", async () => {
      const draft = await seedDraftCourse(h, seed, "growing", { ready: false });
      const youtubeId = newVideoId();
      h.recorder.events.length = 0;
      const created = await call<LessonData>(h, "POST", `/courses/${draft.id}/lessons`, { key: key(), body: { editionId: draft.edition, youtubeId, durationSeconds: 1200 } });
      expect(created.status).toBe(201);
      expect(created.data.lesson).toMatchObject({ position: 3, slug: `video-${youtubeId.toLowerCase()}`, youtubeTitle: `Video ${youtubeId}`, durationSeconds: 1200 });
      expect(created.data.courseRevision).toBe(2);
      expect(insideTransactions(h.recorder.events, (event) => event.startsWith("oembed:"))).toEqual([]);
      const video = (await h.pool.query<Record<string, unknown>>("SELECT status, checked_by FROM lesson_videos WHERE external_id = $1", [youtubeId])).rows[0];
      expect(video).toEqual({ status: "ok", checked_by: "oembed" });
      const title = (await h.pool.query<Record<string, unknown>>("SELECT text, status, source FROM catalog_texts WHERE entity_id = $1 AND field = 'displayTitle'", [created.data.lesson.id])).rows[0];
      expect(title).toEqual({ text: `Video ${youtubeId}`, status: "draft", source: "youtube" });
    });

    it("gives a hand-added lesson the same address as the received list and curation", async () => {
      const draft = await seedDraftCourse(h, seed, "growing-address", { ready: false });
      const youtubeTitle = "Lecture 3 – Freud | Picks University";
      const youtubeId = newVideoId();
      const deps = h.depsWith({ oembed: () => Promise.resolve({ status: "ok", title: youtubeTitle }) });
      const before = (await h.pool.query<{ slug: string }>("SELECT slug FROM lessons WHERE course_id = $1 ORDER BY position", [draft.id])).rows.map((row) => row.slug);
      const created = await call<LessonData>(h, "POST", `/courses/${draft.id}/lessons`, { key: key(), deps, body: { editionId: draft.edition, youtubeId, durationSeconds: 1200 } });
      const address = cleanLessonSlug({
        youtubeTitle,
        courseTitle: "growing-address",
        courseSlug: "growing-address",
        institution: "Picks University",
        edition: { label: "Fall 2025", term: "fall", year: 2025 },
        position: before.length + 1,
        kind: "lecture",
      }, new Set(before));
      expect(created.status).toBe(201);
      expect(created.data.lesson).toMatchObject({ position: before.length + 1, slug: address, youtubeTitle });
      expect(address).not.toBe("freud");
      const title = (await h.pool.query<Record<string, unknown>>("SELECT text FROM catalog_texts WHERE entity_id = $1 AND field = 'displayTitle'", [created.data.lesson.id])).rows[0];
      expect(title).toEqual({ text: cleanTitle(youtubeTitle) });
      const kept = (await h.pool.query<{ slug: string }>("SELECT slug FROM lessons WHERE id = ANY($1) ORDER BY position", [draft.lessons])).rows.map((row) => row.slug);
      expect(kept).toEqual(before);
    });

    it("inserts in the middle by shifting with transient positions, and suffixes a colliding slug", async () => {
      const draft = await seedDraftCourse(h, seed, "middle", { lessons: 3, ready: false });
      const created = await call<LessonData>(h, "POST", `/courses/${draft.id}/lessons`, { key: key(), body: { editionId: draft.edition, youtubeId: newVideoId(), durationSeconds: 600, position: 2, slug: "intro" } });
      expect(created.data.lesson.position).toBe(2);
      expect((await positions(draft.id)).map((row) => row.id)).toEqual([draft.lessons[0], created.data.lesson.id, draft.lessons[1], draft.lessons[2]]);
      expect((await positions(draft.id)).map((row) => row.position)).toEqual([1, 2, 3, 4]);
      h.embeds.clear();
      const youtubeId = newVideoId();
      await h.pool.query("UPDATE lessons SET slug = $2 WHERE id = $1", [draft.lessons[0], `video-${youtubeId.toLowerCase()}`]);
      const suffixed = await call<LessonData>(h, "POST", `/courses/${draft.id}/lessons`, { key: key(), body: { editionId: draft.edition, youtubeId, durationSeconds: 600 } });
      expect(suffixed.data.lesson.slug).toBe(`video-${youtubeId.toLowerCase()}-2`);
      const taken = await call(h, "POST", `/courses/${draft.id}/lessons`, { key: key(), body: { editionId: draft.edition, youtubeId: newVideoId(), durationSeconds: 600, slug: "intro" } });
      expect([taken.status, taken.body.error?.code]).toEqual([409, "slug_taken"]);
      const past = await call(h, "POST", `/courses/${draft.id}/lessons`, { key: key(), body: { editionId: draft.edition, youtubeId: newVideoId(), durationSeconds: 600, position: 99 } });
      expect([past.status, past.body.error?.code]).toEqual([422, "unprocessable"]);
    });

    it("reuses a YouTube video in another course and refuses a second lesson of it in the same course", async () => {
      const draft = await seedDraftCourse(h, seed, "shared", { ready: false });
      const owned = (await h.pool.query<{ external_id: string }>("SELECT external_id FROM lesson_videos WHERE lesson_id = $1", [seed.lessons.alpha[0]])).rows[0]?.external_id;
      const undeclared = await call(h, "POST", `/courses/${draft.id}/lessons`, { key: key(), body: { editionId: draft.edition, youtubeId: owned, durationSeconds: 600, slug: "the-shared-lecture" } });
      expect(undeclared.status).toBe(409);
      expect(undeclared.body.error?.message).toMatch(/both courses must declare the share/);
      const client = await h.pool.connect();
      try {
        await client.query("BEGIN");
        await client.query("UPDATE courses SET shared_with = ARRAY[$2]::text[] WHERE id = $1", [draft.id, seed.courses.alpha]);
        await client.query("UPDATE courses SET shared_with = ARRAY[$2]::text[] WHERE id = $1", [seed.courses.alpha, draft.id]);
        await client.query("COMMIT");
      } finally {
        client.release();
      }
      const shared = await call<LessonData & { youtubeId: string }>(h, "POST", `/courses/${draft.id}/lessons`, { key: key(), body: { editionId: draft.edition, youtubeId: owned, durationSeconds: 600, slug: "the-shared-lecture" } });
      expect(shared.status).toBe(201);
      expect(shared.data.lesson).toMatchObject({ courseId: draft.id, slug: "the-shared-lecture", position: 3 });
      expect(shared.data.youtubeId).toBe(owned);
      const again = await call(h, "POST", `/courses/${draft.id}/lessons`, { key: key(), body: { editionId: draft.edition, youtubeId: owned, durationSeconds: 600 } });
      expect([again.status, again.body.error?.code]).toEqual([409, "state_conflict"]);
      expect(again.body.error?.details).toEqual({ owner: { lessonId: shared.data.lesson.id, courseId: draft.id } });
      const inAlpha = await call(h, "POST", `/courses/${seed.courses.alpha}/lessons`, { key: key(), body: { editionId: seed.editions.alpha, youtubeId: owned, durationSeconds: 600 } });
      expect([inAlpha.status, inAlpha.body.error?.code]).toEqual([409, "state_conflict"]);
      expect(inAlpha.body.error?.details).toEqual({ owner: { lessonId: seed.lessons.alpha[0], courseId: seed.courses.alpha } });
    });

    it("refuses embed-disabled and unavailable videos (422 with the status) and archived courses", async () => {
      const draft = await seedDraftCourse(h, seed, "picky", { ready: false });
      for (const status of ["embed-disabled", "unavailable"] as const) {
        const youtubeId = newVideoId();
        h.embeds.set(youtubeId, status);
        const refused = await call(h, "POST", `/courses/${draft.id}/lessons`, { key: key(), body: { editionId: draft.edition, youtubeId, durationSeconds: 600 } });
        expect([refused.status, refused.body.error?.code, refused.body.error?.details]).toEqual([422, "unprocessable", { status }]);
      }
      await h.pool.query("UPDATE courses SET status = 'archived' WHERE id = $1", [draft.id]);
      expect((await call(h, "POST", `/courses/${draft.id}/lessons`, { key: key(), body: { editionId: draft.edition, youtubeId: newVideoId(), durationSeconds: 600 } })).body.error?.code).toBe("state_conflict");
      expect((await call(h, "POST", "/courses/course-404/lessons", { key: key(), body: { editionId: draft.edition, youtubeId: newVideoId(), durationSeconds: 600 } })).status).toBe(404);
      expect((await call(h, "POST", `/courses/${draft.id}/lessons`, { key: key(), body: { editionId: draft.edition, youtubeId: "short", durationSeconds: 600 } })).status).toBe(400);
    });

    it("answers 502 when oEmbed itself fails, without leaking upstream detail", async () => {
      const draft = await seedDraftCourse(h, seed, "offline", { ready: false });
      const deps = h.depsWith({ oembed: () => Promise.reject(Object.assign(new Error("connect ECONNREFUSED 10.0.0.1 token=abc"), { code: "ECONNREFUSED" })) });
      const failed = await call(h, "POST", `/courses/${draft.id}/lessons`, { key: key(), body: { editionId: draft.edition, youtubeId: newVideoId(), durationSeconds: 600 }, deps });
      expect([failed.status, failed.body.error?.code, failed.body.error?.message]).toEqual([502, "upstream_failed", "The catalog database or storage failed (Error ECONNREFUSED)."]);
    });
  });

  describe("PUT /courses/:id/lessons/order", () => {
    it("rewrites positions 1..N in the given order and bumps the course revision", async () => {
      const revision = await revisionOf(h, "courses", seed.courses.alpha);
      const order = [seed.lessons.alpha[2], seed.lessons.alpha[0], seed.lessons.alpha[1]];
      const response = await call(h, "PUT", `/courses/${seed.courses.alpha}/lessons/order`, { body: { lessonIds: order, expectedRevision: revision } });
      expect(response.data).toEqual({ editionId: seed.editions.alpha, lessonIds: order, revision: revision + 1 });
      expect(await positions(seed.courses.alpha)).toEqual(order.map((id, index) => ({ id, position: index + 1 })));
      expect(await auditRows(h, { action: "lesson.reorder" })).toMatchObject([{ before: { lessonIds: seed.lessons.alpha }, after: { lessonIds: order } }]);
    });

    it("needs an exact permutation: 422 lists missing, unknown and duplicated ids", async () => {
      const revision = await revisionOf(h, "courses", seed.courses.alpha);
      const [a, b] = seed.lessons.alpha;
      const response = await call(h, "PUT", `/courses/${seed.courses.alpha}/lessons/order`, { body: { lessonIds: [a, a, b, seed.lessons.beta[0]], expectedRevision: revision } });
      expect([response.status, response.body.error?.code]).toEqual([422, "unprocessable"]);
      expect(response.body.error?.details).toEqual({ missing: [seed.lessons.alpha[2]], unknown: [seed.lessons.beta[0]], duplicated: [a] });
      expect((await positions(seed.courses.alpha)).map((row) => row.id)).toEqual(seed.lessons.alpha);
    });

    it("treats the current order as a noop: 200, no audit, same revision", async () => {
      const revision = await revisionOf(h, "courses", seed.courses.alpha);
      const response = await call(h, "PUT", `/courses/${seed.courses.alpha}/lessons/order`, { body: { lessonIds: seed.lessons.alpha, expectedRevision: revision } });
      expect(response.data).toMatchObject({ noop: true, revision });
      expect(await revisionOf(h, "courses", seed.courses.alpha)).toBe(revision);
      expect(await auditRows(h, { action: "lesson.reorder" })).toEqual([]);
      expect(h.logs.some((line) => line.includes('"action":"lesson.reorder"') && line.includes('"noop":true'))).toBe(true);
    });

    it("lets one of two concurrent reorders win; the other gets 409 and the unique index never breaks", async () => {
      const revision = await revisionOf(h, "courses", seed.courses.alpha);
      const first = [...seed.lessons.alpha].reverse();
      const second = [seed.lessons.alpha[1], seed.lessons.alpha[2], seed.lessons.alpha[0]];
      const results = await Promise.all([first, second].map((lessonIds) => call(h, "PUT", `/courses/${seed.courses.alpha}/lessons/order`, { body: { lessonIds, expectedRevision: revision } })));
      expect(results.map((result) => result.status).sort()).toEqual([200, 409]);
      const winner = results.find((result) => result.status === 200);
      expect(results.find((result) => result.status === 409)?.body.error).toMatchObject({ code: "revision_conflict", details: { currentRevision: revision + 1 } });
      expect((await positions(seed.courses.alpha)).map((row) => row.id)).toEqual(winner?.data.lessonIds);
      expect((await positions(seed.courses.alpha)).map((row) => row.position)).toEqual([1, 2, 3]);
    });
  });

  describe("PATCH /lessons/:id", () => {
    it("redirects a renamed lesson of a published course and hides a lesson from the next release", async () => {
      const lesson = seed.lessons.alpha[0] ?? "";
      const renamed = await call<LessonData>(h, "PATCH", `/lessons/${lesson}`, { body: { expectedRevision: await revisionOf(h, "lessons", lesson), slug: "the-start" } });
      expect(renamed.data.lesson.slug).toBe("the-start");
      expect((await h.pool.query<Record<string, unknown>>("SELECT to_path FROM slug_redirects WHERE from_path = '/c/alpha/lesson-1'")).rows[0]?.to_path).toBe("/c/alpha/the-start");
      const hidden = await call<LessonData>(h, "PATCH", `/lessons/${seed.lessons.alpha[1] ?? ""}`, { body: { expectedRevision: await revisionOf(h, "lessons", seed.lessons.alpha[1] ?? ""), visible: false } });
      expect(hidden.data.lesson.visible).toBe(false);
      const dry = await call<PublicationData>(h, "POST", "/releases?dryRun=true");
      expect(dry.data.diff.lessons.removed).toEqual([seed.lessons.alpha[1]]);
      expect((await call<ReleaseData>(h, "GET", "/releases/1")).data.release.payload.lessons.map((entry) => entry.id)).toContain(seed.lessons.alpha[1]);
    });

    it("keeps one visible lesson in a published course (412)", async () => {
      for (const lesson of seed.lessons.beta.slice(1)) await h.pool.query("UPDATE lessons SET visible = false WHERE id = $1", [lesson]);
      const last = seed.lessons.beta[0] ?? "";
      const refused = await call(h, "PATCH", `/lessons/${last}`, { body: { expectedRevision: await revisionOf(h, "lessons", last), visible: false } });
      expect(refused.status).toBe(412);
      expect(refused.body.error?.details).toEqual({ failed: [{ rule: "lessons.visible", entity: `course:${seed.courses.beta}`, message: "A published course keeps at least one visible lesson." }] });
      expect((await call(h, "PATCH", "/lessons/lesson-9999", { body: { expectedRevision: 1, visible: false } })).status).toBe(404);
    });
  });

  describe("DELETE /lessons/:id", () => {
    it("dry-runs by default with an exact report and no change", async () => {
      const lesson = seed.lessons.alpha[1] ?? "";
      await swapMedia(h.pool, "lesson", coverInput("lesson", lesson, "cover_16x9"));
      await seedProgress(h, lesson, seed.courses.alpha);
      const before = await catalogFingerprint(h);
      const dry = await call(h, "DELETE", `/lessons/${lesson}`);
      expect(dry.data).toEqual({
        dryRun: true,
        report: {
          lesson: { id: lesson, slug: "lesson-2", courseId: seed.courses.alpha, position: 2, visible: true, revision: 1 }, coursePublished: true,
          recommendation: "The course is published: PATCH {visible:false} hides the lesson and keeps it; delete only with confirm=true.",
          texts: 1, lessonAssets: 1, r2Candidates: [coverInput("lesson", lesson, "cover_16x9").pathname], r2Objects: [], lessonProgressRows: 1,
          redirect: { from: "/c/alpha/lesson-2", to: "/c/alpha" }, blockedBy: [],
        },
      });
      expect(await catalogFingerprint(h)).toBe(before);
    });

    it("deletes with confirm: recompacts positions, redirects to the course, keeps progress, removes bytes after the commit", async () => {
      const lesson = seed.lessons.alpha[1] ?? "";
      await swapMedia(h.pool, "lesson", coverInput("lesson", lesson, "cover_16x9"));
      await seedProgress(h, lesson, seed.courses.alpha);
      const courseRevision = await revisionOf(h, "courses", seed.courses.alpha);
      h.recorder.events.length = 0;
      const deleted = await call(h, "DELETE", `/lessons/${lesson}?confirm=true&expectedRevision=1&deleteBytes=true&checkedKeys=${encodeURIComponent(JSON.stringify([coverInput("lesson", lesson, "cover_16x9").pathname]))}`);
      expect(deleted.data).toMatchObject({ dryRun: false, deleted: true, report: { courseRevision: courseRevision + 1 }, bytes: { deleted: [], pending: [coverInput("lesson", lesson, "cover_16x9").pathname] } });
      expect(await positions(seed.courses.alpha)).toEqual([{ id: seed.lessons.alpha[0], position: 1 }, { id: seed.lessons.alpha[2], position: 2 }]);
      expect((await h.pool.query<Record<string, unknown>>("SELECT to_path FROM slug_redirects WHERE from_path = '/c/alpha/lesson-2'")).rows[0]?.to_path).toBe("/c/alpha");
      expect((await h.pool.query<Record<string, unknown>>("SELECT count(*)::int AS n FROM lesson_progress WHERE lesson_id = $1", [lesson])).rows[0]?.n).toBe(1);
      expect((await h.pool.query<Record<string, unknown>>("SELECT count(*)::int AS n FROM catalog_texts WHERE entity_id = $1", [lesson])).rows[0]?.n).toBe(0);
      const commitAt = h.recorder.events.findIndex((event) => event.startsWith("COMMIT#"));
      expect(commitAt).toBeGreaterThanOrEqual(0);
      expect(h.recorder.events.filter((event) => event.startsWith("r2:delete:"))).toEqual([]);
      expect(insideTransactions(h.recorder.events, (event) => event.startsWith("r2:"))).toEqual([]);
      expect((await call(h, "DELETE", `/lessons/${lesson}?confirm=true&expectedRevision=1&deleteBytes=true&checkedKeys=${encodeURIComponent(JSON.stringify([coverInput("lesson", lesson, "cover_16x9").pathname]))}`)).data).toMatchObject({ alreadyDeleted: true, deleted: true });
    });

    it("refuses to delete the last visible lesson of a published course (412)", async () => {
      await h.pool.query("UPDATE lessons SET visible = false WHERE id = $1", [seed.lessons.beta[1]]);
      const last = seed.lessons.beta[0] ?? "";
      expect((await call<DeleteReportData>(h, "DELETE", `/lessons/${last}`)).data.report.blockedBy).toHaveLength(1);
      const refused = await call(h, "DELETE", `/lessons/${last}?confirm=true&expectedRevision=1`);
      expect([refused.status, refused.body.error?.code]).toEqual([412, "preconditions_failed"]);
      expect((await call(h, "DELETE", `/lessons/${last}?confirm=true`)).status).toBe(400);
    });

    it("reports a partial R2 failure with 502 and pending keys; re-running the DELETE finishes it", async () => {
      const draft = await seedDraftCourse(h, seed, "bytes", { lessons: 2, ready: false });
      const lesson = draft.lessons[0] ?? "";
      const cover = coverInput("lesson", lesson, "cover_16x9");
      await swapMedia(h.pool, "lesson", cover);
      h.store.failing.add(cover.pathname);
      const held = await call(h, "DELETE", `/lessons/${lesson}?confirm=true&expectedRevision=1&deleteBytes=true&checkedKeys=${encodeURIComponent(JSON.stringify([coverInput("lesson", lesson, "cover_16x9").pathname]))}`);
      expect(held.data).toMatchObject({ dryRun: false, deleted: true, bytes: { deleted: [], pending: [cover.pathname] } });
      expect((await h.pool.query<Record<string, unknown>>("SELECT count(*)::int AS n FROM lessons WHERE id = $1", [lesson])).rows[0]?.n).toBe(0);
      const doctor = await call<DoctorData>(h, "GET", "/doctor");
      expect(doctor.data.findings.find((finding: { code: string }) => finding.code === "r2.pending")).toMatchObject({ count: 1 });
      h.store.failing.clear();
      expect((await call(h, "DELETE", `/lessons/${lesson}`)).data).toEqual({ dryRun: true, alreadyDeleted: true, r2Pending: 1 });
      const finished = await call(h, "DELETE", `/lessons/${lesson}?confirm=true&deleteBytes=true&checkedKeys=${encodeURIComponent(JSON.stringify([coverInput("lesson", lesson, "cover_16x9").pathname]))}`);
      expect(finished.data).toMatchObject({ deleted: true, alreadyDeleted: true, bytes: { deleted: [], pending: [cover.pathname] } });
      const audits = await auditRows(h, { entity: `lesson:${lesson}` });
      expect(audits.map((row) => row.action)).toEqual(["lesson.delete", "lesson.delete", "lesson.delete"]);
      expect(audits[1]?.after).toEqual({ r2Completed: [], r2Pending: [cover.pathname] });
      expect(audits[2]?.after).toEqual({ r2Completed: [], r2Pending: [cover.pathname] });
    });
  });

  describe("a YouTube video shared by two courses", () => {
    it("validates, publishes and renders each lesson, and keeps watch progress per lesson", async () => {
      const owned = (await h.pool.query<{ external_id: string }>("SELECT external_id FROM lesson_videos WHERE lesson_id = $1", [seed.lessons.alpha[0]])).rows[0]?.external_id ?? "";
      const draft = await seedDraftCourse(h, seed, "reuse");
      const shared = await seedLesson(h.pool, draft.id, { youtubeId: owned });
      await h.pool.query("UPDATE courses SET status = 'review' WHERE id = $1", [draft.id]);
      await h.pool.query("INSERT INTO home_row_items (row_id, course_id, position) VALUES ('picks', $1, 3)", [draft.id]);
      const published = await call<PublicationData>(h, "POST", `/courses/${draft.id}/publish`, { key: key(), body: { expectedRevision: await revisionOf(h, "courses", draft.id), note: "Share the lecture" } });
      expect(published.status).toBe(200);
      const catalog = (await h.pool.query<{ payload: PublicCatalog }>("SELECT payload FROM catalog_releases WHERE is_active")).rows[0]?.payload;
      if (!catalog) throw new Error("No active release.");
      const alphaLesson = lessonBySlug(catalog, seed.courses.alpha, "lesson-1");
      const rendered = lessonBySlug(catalog, draft.id, "lesson-3");
      expect(alphaLesson).toMatchObject({ id: seed.lessons.alpha[0], slug: "lesson-1", courseId: seed.courses.alpha, youtubeId: owned, order: 1 });
      expect(rendered).toMatchObject({ id: shared.id, slug: "lesson-3", courseId: draft.id, youtubeId: owned });
      expect(rendered?.id).not.toBe(alphaLesson?.id);
      expect(rendered?.order).not.toBe(alphaLesson?.order);
      const paths = publicPaths(publicRouteSnapshot(catalog));
      expect(paths).toEqual(expect.arrayContaining(["/c/alpha/lesson-1", "/c/reuse/lesson-3"]));
      expect(lessonMetadataInput(catalog, "alpha", "lesson-1")).toMatchObject({ slug: "lesson-1", course: { slug: "alpha" } });
      expect(lessonMetadataInput(catalog, "reuse", "lesson-3")).toMatchObject({ slug: "lesson-3", course: { slug: "reuse" } });
      const user = "user-shared-youtube";
      await h.pool.query(`INSERT INTO "user" (id, name, email, email_verified, created_at, updated_at) VALUES ($1, 'Shared', $2, true, now(), now())`, [user, `${user}@example.invalid`]);
      await h.pool.query(`INSERT INTO lesson_progress (user_id, lesson_id, course_id, position_seconds, duration_seconds, updated_at)
        VALUES ($1, $2, $3, 111, 900, now()), ($1, $4, $5, 444, 900, now() - interval '1 minute')`,
      [user, seed.lessons.alpha[0], seed.courses.alpha, shared.id, draft.id]);
      const rows = await readProgress(h.pool, user);
      expect(rows.map((row) => [row.lessonId, row.courseId, row.positionSeconds]).sort()).toEqual([
        [seed.lessons.alpha[0], seed.courses.alpha, 111],
        [shared.id, draft.id, 444],
      ].sort());
      expect(lessonStartSecond(rows.find((row) => row.lessonId === seed.lessons.alpha[0]), null, 900)).toBe(111);
      expect(lessonStartSecond(rows.find((row) => row.lessonId === shared.id), null, 900)).toBe(444);
      const watching = signedInHome(catalog, new Map(), catalogProgressViews(catalog, rows)).continueWatching.map((course) => [course.slug, course.progress?.card?.href, course.progress?.current?.lessonId]);
      expect(watching).toEqual([
        ["alpha", "/c/alpha/lesson-1?t=111", seed.lessons.alpha[0]],
        ["reuse", "/c/reuse/lesson-3?t=444", shared.id],
      ]);
    });
  });
});
