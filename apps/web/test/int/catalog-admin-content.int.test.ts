import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import sharp from "sharp";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
vi.mock("server-only", () => ({}));
vi.mock("next/headers", () => ({ draftMode: () => Promise.resolve({ isEnabled: false }), cookies: () => Promise.resolve({ get: () => undefined }) }));
import { createAdminRateLimiter } from "../../src/platform/security/rate-limit.ts";
import { compileDraftCatalog } from "../../src/catalog/server/draft.ts";
import { handleAdminMediaUpload } from "../../src/media/server/admin.ts";
import { catalogCourseOf, catalogOwners } from "../../src/catalog/server/media-owners.ts";
import { createFsMediaStore } from "../../src/media/server/fs-store.ts";
import { swapMedia } from "../../src/media/server/repository.ts";
import { MEDIA_PUBLIC_HOST } from "../../src/media/domain/types.ts";
import { compileRelease } from "../../src/catalog/domain/compile.ts";
import { readCatalogTables } from "../../src/catalog/server/table-io.ts";
import type { ImportReport } from "../../src/catalog/server/imports.ts";
import {
  activeRelease, auditRows, call, catalogFingerprint, coverInput, createHarness, insideTransactions, newVideoId, NOW, SECRET, seedCatalog, seedDraftCourse, type AuditData, type CourseDetail, type CourseView, type DoctorData, type Harness, type HomeData, type LessonView, type Seed,
} from "../fixtures/admin-catalog.ts";

// Verifies: D-029
describe("admin catalog: texts, Home, imports, redirects, doctor, preview and media on PG18", () => {
  let h: Harness;
  let seed: Seed;
  beforeAll(() => { h = createHarness(); });
  afterAll(async () => { await h.close(); });
  beforeEach(async () => { seed = await seedCatalog(h); });
  const key = () => `k-${Math.random().toString(36).slice(2)}`;
  const text = (entityId: string, field: string, value: string, kind = "course") => ({ entityKind: kind, entityId, field, text: value, source: "manual", sourceRef: "int", confidence: "high" });
  const stored = async (entityId: string, field: string) => (await h.pool.query<Record<string, unknown>>("SELECT text, status, text_sha256, approved_sha256, approved_by FROM catalog_texts WHERE entity_id = $1 AND field = $2", [entityId, field])).rows[0];

  describe("texts", () => {
    it("shows every field with limits, status and hash", async () => {
      const response = await call(h, "GET", `/texts?entity=course:${seed.courses.alpha}`);
      const level = (response.data.fields as { field: string }[]).find((entry) => entry.field === "level");
      expect(level).toMatchObject({ field: "level", maxChars: 16, requiredForReview: true, requiredForPublish: true, status: "approved", sha256: expect.stringMatching(/^[a-f0-9]{64}$/) as string, issues: [] });
      expect(response.data.fields).toHaveLength(10);
      expect((await call(h, "GET", "/texts?entity=course:course-404")).status).toBe(404);
      expect((await call(h, "GET", "/texts?entity=nope:x")).status).toBe(400);
    });

    it("writes a batch as draft atomically; editing an approved text drops its approval and never touches the live release", async () => {
      const release = await activeRelease(h);
      const response = await call<{ items: { status: string; changed: boolean }[] }>(h, "PUT", "/texts", { body: [text(seed.courses.alpha, "subtitle", "Edited subtitle"), text(seed.lessons.alpha[0] ?? "", "about", "About this lesson", "lesson")] });
      expect(response.data.items.map((item) => [item.status, item.changed])).toEqual([["draft", true], ["draft", true]]);
      expect(await stored(seed.courses.alpha, "subtitle")).toMatchObject({ text: "Edited subtitle", status: "draft", approved_sha256: null, approved_by: null });
      expect(await activeRelease(h)).toEqual(release);
      // Other publishes keep the live text of this course while its edit awaits approval.
      expect((await call(h, "POST", "/releases?dryRun=true")).data).toMatchObject({ valid: true, unchanged: true });
      const audit = await auditRows(h, { action: "text.put" });
      expect(audit[0]).toMatchObject({ before: { field: "subtitle", status: "approved" }, after: { field: "subtitle", status: "draft" } });
      expect(JSON.stringify(audit)).not.toContain("Edited subtitle");
      // The same batch again changes nothing.
      expect((await call(h, "PUT", "/texts", { body: [text(seed.courses.alpha, "subtitle", "Edited subtitle")] })).data.noop).toBe(true);
    });

    it("refuses the whole batch (422 with every bad item) for an unknown field, empty text, over-limit or out-of-charset text", async () => {
      const before = await catalogFingerprint(h);
      const response = await call(h, "PUT", "/texts", {
        body: [
          text(seed.courses.alpha, "subtitle", "Fine"), text(seed.courses.alpha, "tagline", "x"), text(seed.courses.alpha, "level", " "),
          text(seed.courses.alpha, "format", "f".repeat(29)), text(seed.courses.alpha, "displayTitle", "Emoji 🙂"), text("course-404", "subtitle", "x"),
        ],
      });
      expect([response.status, response.body.error?.code]).toEqual([422, "unprocessable"]);
      const items = (response.body.error?.details as { items: { index: number; issues: { rule: string }[] }[] }).items;
      expect(items.map((item) => [item.index, item.issues.map((issue) => issue.rule)])).toEqual([
        [1, ["texts.field"]], [2, ["texts.empty"]], [3, ["texts.limit"]], [4, ["texts.charset"]], [5, ["texts.entity"]],
      ]);
      expect(JSON.stringify(response.body)).not.toContain("🙂");
      expect(await catalogFingerprint(h)).toBe(before);
    });

    it("approves the hash the reviewer saw; a changed text refuses the whole batch with 409", async () => {
      await call(h, "PUT", "/texts", { body: [text(seed.courses.alpha, "subtitle", "Reviewed subtitle"), text(seed.courses.alpha, "format", "Reviewed format")] });
      const subtitle = await stored(seed.courses.alpha, "subtitle");
      const format = await stored(seed.courses.alpha, "format");
      await call(h, "PUT", "/texts", { body: [text(seed.courses.alpha, "format", "Changed after review")] });
      const refused = await call(h, "POST", "/texts/approve", { key: key(), body: { approvedBy: "Daniel", items: [
        { entityKind: "course", entityId: seed.courses.alpha, field: "subtitle", sha256: subtitle?.text_sha256 },
        { entityKind: "course", entityId: seed.courses.alpha, field: "format", sha256: format?.text_sha256 },
      ] } });
      expect([refused.status, refused.body.error?.code]).toEqual([409, "state_conflict"]);
      expect((refused.body.error?.details as { mismatched: { field: string }[] }).mismatched.map((entry) => entry.field)).toEqual(["format"]);
      expect((await stored(seed.courses.alpha, "subtitle"))?.status).toBe("draft");
      const approved = await call(h, "POST", "/texts/approve", { key: key(), body: { approvedBy: "Daniel", items: [{ entityKind: "course", entityId: seed.courses.alpha, field: "subtitle", sha256: subtitle?.text_sha256 }] } });
      expect(approved.status).toBe(200);
      expect(await stored(seed.courses.alpha, "subtitle")).toMatchObject({ status: "approved", approved_by: "Daniel", approved_sha256: subtitle?.text_sha256 });
      const about = await stored(seed.courses.alpha, "about");
      const unchanged = await call(h, "POST", "/texts/approve", { key: key(), body: { approvedBy: "Daniel", items: [{ entityKind: "course", entityId: seed.courses.alpha, field: "about", sha256: about?.text_sha256 }] } });
      expect([unchanged.status, unchanged.data.noop]).toEqual([200, true]);
      expect((await call(h, "POST", "/texts/approve", { key: key(), body: { items: [{ entityKind: "course", entityId: seed.courses.alpha, field: "subtitle", sha256: subtitle?.text_sha256 }] } })).status).toBe(400);
      const unknown = await call(h, "POST", "/texts/approve", { key: key(), body: { approvedBy: "D", items: [{ entityKind: "lesson", entityId: "lesson-9999", field: "about", sha256: "0".repeat(64) }] } });
      expect([unknown.status, unknown.body.error?.code]).toEqual([404, "not_found"]);
    });

    it("revokes approvals back to draft", async () => {
      const revoked = await call(h, "POST", "/texts/revoke", { key: key(), body: { items: [{ entityKind: "course", entityId: seed.courses.alpha, field: "level" }] } });
      expect(revoked.data.items).toEqual([{ entity: `course:${seed.courses.alpha}`, field: "level", changed: true }]);
      expect(await stored(seed.courses.alpha, "level")).toMatchObject({ status: "draft", approved_sha256: null });
      expect((await call(h, "POST", "/texts/revoke", { key: key(), body: { items: [{ entityKind: "course", entityId: seed.courses.alpha, field: "level" }] } })).data.noop).toBe(true);
    });
  });

  describe("Home", () => {
    const portrait = (id: string, kind: "university_cover_9x16" | "author_cover_9x16") => ({
      url: `https://media.openuniversity.si/covers/${id}/${kind}/${"a".repeat(40)}.webp`,
      width: 1080, height: 1920, sha256: "b".repeat(64), alt: id, credit: "Test", sourceUrl: "https://example.org/cover", license: "test", note: null,
    });

    it("exposes its revision and replaces rows atomically with a new release", async () => {
      const home = await call(h, "GET", "/home");
      expect(home.data).toMatchObject({ revision: 1, featuredCourseId: seed.courses.alpha, rows: [{ id: "continue", kind: "continue" }, { id: "picks", courseIds: [seed.courses.alpha, seed.courses.beta] }] });
      await h.pool.query("UPDATE authors SET cover = $2::jsonb WHERE id = $1", [seed.authors[0], JSON.stringify(portrait(seed.authors[0], "author_cover_9x16"))]);
      await swapMedia(h.pool, "institution", coverInput("institution", seed.authors[0], "author_cover_9x16"));
      h.recorder.events.length = 0;
      const put = await call<{ home: HomeData; noop?: true }>(h, "PUT", "/home", { body: {
        featuredCourseId: seed.courses.beta, expectedRevision: 1,
        rows: [{ id: "new-row", kind: "curated", title: "New", cover: portrait("new-row", "university_cover_9x16"), courseIds: [seed.courses.beta] }, { id: "by-ann", kind: "author", authorId: seed.authors[0], courseIds: [seed.courses.alpha] }, { id: "continue", kind: "continue", courseIds: [] }],
      } });
      expect(put.body.error).toBeUndefined();
      expect(put.data).toMatchObject({ home: { revision: 2, featuredCourseId: seed.courses.beta }, release: { number: 2, created: true }, diff: { home: { changed: true } } });
      expect(put.data.home.rows.map((row) => [row.id, row.position])).toEqual([["new-row", 1], ["by-ann", 2], ["continue", 3]]);
      expect(h.recorder.events.at(-1)).toBe("invalidate");
      expect((await auditRows(h, { action: "home.set" }))[0]).toMatchObject({ release_number: 2 });
      const same = await call(h, "PUT", "/home", { body: { featuredCourseId: seed.courses.beta, expectedRevision: 2, rows: put.data.home.rows.map((row) => ({ id: row.id, kind: row.kind, ...(row.title ? { title: row.title } : {}), ...(row.authorId ? { authorId: row.authorId } : {}), courseIds: row.courseIds })) } });
      expect(same.data.noop).toBe(true);
    });

    it("S08: dryRun runs the whole change and its commit-time rules, then rolls it back", async () => {
      const rows = [{ id: "new-row", kind: "curated", title: "New", cover: portrait("new-row", "university_cover_9x16"), courseIds: [seed.courses.beta] }, { id: "continue", kind: "continue", courseIds: [] }];
      const tables = async () => (await h.pool.query("SELECT (SELECT revision FROM catalog_home) AS revision, (SELECT count(*)::int FROM catalog_releases) AS releases, (SELECT string_agg(id, ',' ORDER BY position) FROM home_rows) AS rows, (SELECT id FROM courses WHERE featured) AS featured")).rows[0] as unknown;
      const before = await tables();
      h.recorder.events.length = 0;
      const dry = await call<{ dryRun: true; release: { number: number; created: boolean } }>(h, "PUT", "/home", { body: { featuredCourseId: seed.courses.beta, expectedRevision: 1, rows, dryRun: true } });
      expect(dry.body.error).toBeUndefined();
      expect(dry.data).toMatchObject({ dryRun: true, home: { revision: 2 }, release: { number: 2, created: true } });
      expect(await tables()).toEqual(before);
      expect(h.recorder.events).not.toContain("invalidate");
      // JSON cover satisfies the Home rule; catalog_media does not, so only the deferred trigger can refuse.
      await h.pool.query("UPDATE authors SET cover = $2::jsonb WHERE id = $1", [seed.authors[0], JSON.stringify(portrait(seed.authors[0], "author_cover_9x16"))]);
      const authorRows = [{ id: "by-ann", kind: "author", authorId: seed.authors[0], courseIds: [seed.courses.alpha] }, { id: "continue", kind: "continue", courseIds: [] }];
      const refused = await call(h, "PUT", "/home", { body: { featuredCourseId: seed.courses.alpha, expectedRevision: 1, rows: authorRows, dryRun: true } });
      const written = await call(h, "PUT", "/home", { body: { featuredCourseId: seed.courses.alpha, expectedRevision: 1, rows: authorRows } });
      expect([refused.status, refused.body.error?.code, refused.body.error?.message]).toEqual([written.status, written.body.error?.code, written.body.error?.message]);
      expect(refused.status).toBe(422);
      expect(refused.body.error?.message).toContain("catalog_institution_cover");
      expect(await tables()).toEqual(before);
    });

    it("refuses invalid Homes with every broken invariant (422) and changes nothing", async () => {
      const draft = await seedDraftCourse(h, seed, "hidden");
      const archived = await seedDraftCourse(h, seed, "shelved");
      await h.pool.query("UPDATE courses SET status = 'archived' WHERE id = $1", [archived.id]);
      const before = await catalogFingerprint(h);
      const response = await call(h, "PUT", "/home", { body: {
        featuredCourseId: draft.id, expectedRevision: 1,
        rows: [
          { id: "continue", kind: "continue", courseIds: [seed.courses.alpha] }, { id: "again", kind: "continue", courseIds: [] }, { id: "untitled", kind: "curated", courseIds: [archived.id, "course-404", seed.courses.beta, seed.courses.beta] },
          { id: "untitled", kind: "author", courseIds: [] }, { id: "with-author", kind: "curated", title: "T", authorId: seed.authors[0], courseIds: [] },
        ],
      } });
      expect([response.status, response.body.error?.code]).toEqual([422, "unprocessable"]);
      expect((response.body.error?.details as { errors: string[] }).errors).toEqual([
        "At most one continue row.", "The continue row is derived from progress: no courseIds.", "Curated row untitled needs a title.", "Row untitled repeats a course.",
        `Row untitled: course ${archived.id} is archived.`, "Row untitled: course course-404 does not exist.", "Row untitled appears twice.", "Author row untitled needs an existing authorId.",
        "Row with-author (curated) takes no authorId.", `Featured course ${draft.id} is not published.`, "A curated row needs exactly one existing institution.",
        "Curated row untitled needs a cover.", "Curated row with-author needs a cover.",
      ]);
      expect(await catalogFingerprint(h)).toBe(before);
    });

    it("refuses a Universities row with no cover and names the row", async () => {
      const response = await call(h, "PUT", "/home", { body: {
        featuredCourseId: seed.courses.alpha, expectedRevision: 1,
        rows: [{ id: "continue", kind: "continue", courseIds: [] }, { id: "iit-roorkee", kind: "curated", title: "IIT Roorkee", courseIds: [seed.courses.alpha] }],
      } });
      expect([response.status, response.body.error?.code]).toEqual([422, "unprocessable"]);
      expect((response.body.error?.details as { errors: string[] }).errors).toEqual(["Curated row iit-roorkee needs a cover."]);
    });
  });

  describe("imports", () => {
    it("stores the items and the §4.2 report, with oEmbed outside the transaction", async () => {
      const owned = (await h.pool.query<{ external_id: string }>("SELECT external_id FROM lesson_videos WHERE lesson_id = $1", [seed.lessons.alpha[0]])).rows[0]?.external_id ?? "";
      const ids = Array.from({ length: 8 }, () => newVideoId());
      h.embeds.set(ids[6] ?? "", "embed-disabled");
      h.recorder.events.length = 0;
      const response = await call<{ import: { id: string; report: ImportReport } }>(h, "POST", "/imports", { key: key(), body: {
        playlistUrl: "https://www.youtube.com/playlist?list=PLreport0001", tool: "yt-dlp 2026.09", playlistTitle: "Report", channelId: "UCchannel",
        items: [
          { id: ids[0], title: "Course trailer", duration: 90, playlistIndex: 1 }, { id: ids[1], title: "Lecture 1 - Origins | Uni", duration: 2400, playlistIndex: 2, height: 360, channelId: "UCother" },
          { id: ids[2], title: "Private", duration: 600, playlistIndex: 3, availability: "private" }, { id: ids[3], title: "Live", playlistIndex: 4, liveStatus: "is_live" },
          { id: ids[4], title: "Adults", duration: 600, playlistIndex: 5, ageLimit: 18 }, { id: owned, title: "Already here", duration: 600, playlistIndex: 6 },
          { id: ids[6], title: "No embed", duration: 600, playlistIndex: 7 }, { id: ids[7], title: "Not embeddable", duration: 600, playlistIndex: 8, playableInEmbed: false },
          { id: ids[1], title: "Duplicate", duration: 600, playlistIndex: 9 },
        ],
      } });
      expect(response.status).toBe(201);
      const report = response.data.import.report;
      expect(response.data.import.id).toBe("import-PLreport0001-202610111200");
      expect(report.accepted.map((item: { id: string; suggestedKind: string; suggestedTitle: string; position: number }) => [item.id, item.position, item.suggestedKind, item.suggestedTitle])).toEqual([
        [ids[0], 1, "trailer", "Course trailer"], [ids[1], 2, "lecture", "Origins"], [owned, 3, "lecture", "Already here"],
      ]);
      expect(report.excluded).toEqual([
        { id: ids[2], reason: "private" }, { id: ids[3], reason: "live" }, { id: ids[4], reason: "age-restricted" },
        { id: ids[6], reason: "embed-disabled" }, { id: ids[7], reason: "embed-disabled" }, { id: ids[1], reason: "duplicate" },
      ]);
      expect(report.warnings).toEqual([{ id: ids[0], reason: "duration" }, { id: ids[1], reason: "resolution" }, { id: ids[1], reason: "channel" }]);
      expect(insideTransactions(h.recorder.events, (event) => event.startsWith("oembed:"))).toEqual([]);
      const second = await call<{ import: { id: string; report: ImportReport } }>(h, "POST", "/imports", { key: key(), body: { playlistUrl: "https://www.youtube.com/playlist?list=PLreport0001", items: [{ id: newVideoId(), title: "x", duration: 600 }] } });
      expect(second.data.import.id).toBe("import-PLreport0001-202610111200-2");
      expect((await call(h, "POST", "/imports", { key: key(), body: { playlistUrl: "https://example.org/list", items: [{ id: newVideoId(), title: "x" }] } })).status).toBe(400);
    });

    it("drafts a course with lessons from an import once; a drafted import is 409", async () => {
      const ids = [newVideoId(), newVideoId(), newVideoId()];
      const created = await call<{ import: { id: string; report: ImportReport } }>(h, "POST", "/imports", { key: key(), body: { playlistUrl: "https://www.youtube.com/playlist?list=PLdraft00001", playlistTitle: "Drafted", items: ids.map((id, index) => ({ id, title: `Lecture ${String(index + 1)} - Part ${String(index + 1)}`, duration: 1800 })) } });
      const id = created.data.import.id;
      const bad = await call(h, "POST", `/imports/${id}/draft`, { key: key(), body: { slug: "drafted", authorId: seed.authors[0], include: [newVideoId()] } });
      expect([bad.status, bad.body.error?.code]).toEqual([422, "unprocessable"]);
      const drafted = await call<{ course: CourseView; lessons: (LessonView & { youtubeId: string })[] }>(h, "POST", `/imports/${id}/draft`, { key: key(), body: { slug: "drafted", newAuthor: { slug: "new-person", name: "New Person", monogram: "NP", kind: "person" }, exclude: [ids[1] ?? ""] } });
      expect(drafted.status).toBe(201);
      expect(drafted.data.course).toMatchObject({ slug: "drafted", title: "Drafted", status: "draft" });
      expect(drafted.data.lessons.map((lesson) => [lesson.youtubeId, lesson.position, lesson.slug])).toEqual([[ids[0], 1, "lecture-01-part-1"], [ids[2], 2, "lecture-03-part-3"]]);
      expect((await h.pool.query<Record<string, unknown>>("SELECT status, course_id FROM catalog_imports WHERE id = $1", [id])).rows[0]).toEqual({ status: "drafted", course_id: drafted.data.course.id });
      expect((await auditRows(h, { requestId: drafted.body.requestId })).map((row) => row.action)).toEqual(["author.create", "course.create", "edition.create", "lesson.create", "lesson.create", "import.draft"]);
      const again = await call(h, "POST", `/imports/${id}/draft`, { key: key(), body: { slug: "drafted-2", authorId: seed.authors[0] } });
      expect([again.status, again.body.error?.code]).toEqual([409, "state_conflict"]);
      expect((await call(h, "POST", "/imports/import-PLnone-202610111200/draft", { key: key(), body: { slug: "x", authorId: seed.authors[0] } })).status).toBe(404);
    });
  });

  describe("redirects", () => {
    it("validates redirects (no shadowing, existing target, no chains) and deletes with a dry-run first", async () => {
      const bad = await call(h, "POST", "/redirects", { body: { from: "/c/alpha", to: "/c/nowhere" } });
      expect([bad.status, bad.body.error?.code]).toEqual([422, "unprocessable"]);
      expect((bad.body.error?.details as { errors: string[] }).errors).toEqual(["/c/alpha is a course or lesson page; a redirect would shadow it.", "/c/nowhere is not a course or lesson page."]);
      expect((await call(h, "POST", "/redirects", { body: { from: "/c/alpha-old", to: "/c/alpha/lesson-1" } })).status).toBe(201);
      expect((await call(h, "POST", "/redirects", { body: { from: "/c/alpha-old", to: "/c/alpha/lesson-1" } })).data.noop).toBe(true);
      expect((await call(h, "POST", "/redirects", { body: { from: "/c/alpha-old", to: "/c/beta" } })).body.error?.code).toBe("state_conflict");
      const chain = await call(h, "POST", "/redirects", { body: { from: "/c/older", to: "/c/alpha-old" } });
      expect(chain.status).toBe(422);
      expect((await call(h, "GET", "/redirects")).data.redirects).toEqual([{ from: "/c/alpha-old", to: "/c/alpha/lesson-1", live: true }]);
      const before = await catalogFingerprint(h);
      expect((await call(h, "DELETE", `/redirects?from=${encodeURIComponent("/c/alpha-old")}`)).data).toEqual({ dryRun: true, redirect: { from: "/c/alpha-old", to: "/c/alpha/lesson-1" } });
      expect(await catalogFingerprint(h)).toBe(before);
      expect((await call(h, "DELETE", `/redirects?from=${encodeURIComponent("/c/alpha-old")}&confirm=true`)).data.deleted).toBe(true);
      expect((await call(h, "DELETE", `/redirects?from=${encodeURIComponent("/c/alpha-old")}`)).status).toBe(404);
      expect((await call<AuditData>(h, "GET", `/audit?entity=${encodeURIComponent("redirect:/c/alpha-old")}`)).data.entries.map((entry) => entry.action)).toEqual(["redirect.delete", "redirect.create"]);
    });
  });

  describe("reference data", () => {
    it("creates licenses and sources, refuses duplicates, patches sources with a revision", async () => {
      expect((await call(h, "POST", "/licenses", { key: key(), body: { code: "youtube-standard", name: "Dup", requiresAttribution: false } })).body.error?.code).toBe("slug_taken");
      const licenses = await call(h, "GET", "/licenses");
      expect(licenses.data.licenses).toEqual([expect.objectContaining({ code: "youtube-standard", uses: 2, embedOnly: true })]);
      const source = await call(h, "POST", "/sources", { key: key(), body: { id: "yale-x", kind: "youtube-playlist", title: "Yale", publisher: "Yale", url: "https://www.youtube.com/playlist?list=PLyale0000", youtubePlaylistId: "PLyale0000" } });
      expect(source.status).toBe(201);
      expect((await call(h, "POST", "/sources", { key: key(), body: { id: "yale-y", kind: "youtube-playlist", title: "Y", publisher: "Y", url: "https://example.org/y", youtubePlaylistId: "PLyale0000" } })).body.error?.code).toBe("slug_taken");
      const patched = await call(h, "PATCH", "/sources/yale-x", { body: { expectedRevision: 1, title: "Yale courses" } });
      expect(patched.data.source).toMatchObject({ title: "Yale courses", revision: 2 });
      expect((await call(h, "PATCH", "/sources/yale-x", { body: { expectedRevision: 2, title: "Yale courses" } })).data.noop).toBe(true);
      expect((await call<{ sources: { id: string; uses: number }[] }>(h, "GET", "/sources")).data.sources.map((entry) => [entry.id, entry.uses])).toEqual([["src-test", 2], ["yale-x", 0]]);
    });
  });

  describe("doctor and audit", () => {
    it("is clean on a consistent catalog and never writes", async () => {
      const before = await catalogFingerprint(h);
      const doctor = await call<DoctorData>(h, "GET", "/doctor");
      const retained = Number((await h.pool.query<{ n: string }>("SELECT count(*)::int AS n FROM catalog_releases WHERE NOT is_active")).rows[0]?.n ?? 0);
      expect(doctor.data.ok).toBe(true);
      expect(doctor.data.activeRelease).toEqual({ number: 1, sha: (await activeRelease(h)).sha });
      expect(doctor.data.findings.map((finding) => finding.code)).not.toContain("media.legacy.reader");
      expect(doctor.data.findings.map((finding) => [finding.code, finding.severity, finding.count])).toEqual(retained > 0 ? [["release.retained", "info", retained]] : []);
      expect(doctor.data.operational).toMatchObject({ scope: "process", activeReleaseNumber: 1, projectionDriftCount: 0, pool: { total: 0, idle: 0, waiting: 0 } });
      expect(await catalogFingerprint(h)).toBe(before);
      expect(h.recorder.statements.filter((sql) => /^\s*(INSERT|UPDATE|DELETE|BEGIN)/i.test(sql))).toEqual([]);
    });

    it("finds orphans, broken redirects, not-ok videos, behind sequences, drift and compile failures", async () => {
      await h.pool.query("INSERT INTO catalog_texts (entity_kind, entity_id, field, text, source, source_ref, confidence) VALUES ('lesson', 'lesson-9999', 'about', 'x', 'manual', 'x', 'high')");
      // catalog_media has no owner foreign key, so a cover for a missing course is a real orphan the doctor reports.
      await h.pool.query(`INSERT INTO catalog_media (id, owner_kind, owner_id, kind, variant, url, pathname, width, height, sha256, alt, design_status, version, is_active)
        VALUES ('orphan', 'course', 'course-9999', 'poster_9x16', 'default', 'https://${MEDIA_PUBLIC_HOST}/covers/course-9999/poster_9x16/${"a".repeat(40)}.jpg', 'covers/course-9999/poster_9x16/${"a".repeat(40)}.jpg', 1, 1, '${"a".repeat(64)}', 'x', 'approved', 1, true)`);
      await h.pool.query("INSERT INTO slug_redirects (from_path, to_path) VALUES ('/c/gone', '/c/nowhere')");
      await h.pool.query("UPDATE lessons SET visible = false WHERE id = $1", [seed.lessons.alpha[2]]);
      await h.pool.query("UPDATE catalog_texts SET status = 'draft', approved_by = NULL, approved_at = NULL, approved_sha256 = NULL WHERE entity_id = $1 AND field = 'level'", [seed.courses.beta]);
      await h.pool.query<Record<string, unknown>>("SELECT setval('author_seq', 1, true)");
      const doctor = await call(h, "GET", "/doctor");
      expect(doctor.data.ok).toBe(false);
      const byCode = Object.fromEntries((doctor.data.findings as { code: string; count: number; sample: unknown[] }[]).map((finding) => [finding.code, finding]));
      expect(byCode["texts.orphan"]).toMatchObject({ severity: "error", count: 1, sample: ["lesson:lesson-9999.about"] });
      expect(byCode["assets.orphan"]).toMatchObject({ count: 1 });
      expect(byCode["redirects.broken"]).toMatchObject({ count: 1, sample: ["/c/gone -> /c/nowhere"] });
      expect(byCode["sequences.behind"]).toMatchObject({ sample: ["author_seq"] });
      expect(byCode["course.preconditions"]).toMatchObject({ count: 1 });
      expect(byCode["release.drift"]).toMatchObject({ severity: "info", sample: [expect.objectContaining({ lessons: expect.objectContaining({ removed: [seed.lessons.alpha[2]] }) as object })] });
      // A published lesson whose video went bad is reported, and the tables no longer compile until it is fixed or hidden.
      await h.pool.query("UPDATE lesson_videos SET status = 'unavailable' WHERE lesson_id = $1", [seed.lessons.beta[0]]);
      const broken = Object.fromEntries(((await call(h, "GET", "/doctor")).data.findings as { code: string }[]).map((finding) => [finding.code, finding]));
      expect(broken["videos.not_ok"]).toMatchObject({ severity: "error", count: 1, sample: [`${seed.lessons.beta[0] ?? ""}:unavailable`] });
      expect(broken["release.compile_failed"]).toMatchObject({ severity: "error" });
    });

    it("judges sequences by their next value, also right after catalog:migrate's setval(…, false)", async () => {
      const sequences = async () => ((await call(h, "GET", "/doctor")).data.findings as { code: string; sample: unknown[] }[]).find((finding) => finding.code === "sequences.behind")?.sample ?? [];
      const top = Number((await h.pool.query<{ n: string }>("SELECT max(substring(id FROM '^lesson-(\\d+)$')::bigint) AS n FROM lessons")).rows[0]?.n);
      await h.pool.query("SELECT setval('lesson_seq', $1, false)", [top + 1]);
      expect(await sequences()).toEqual([]);
      await h.pool.query("SELECT setval('lesson_seq', $1, false)", [top]);
      expect(await sequences()).toEqual(["lesson_seq"]);
      await h.pool.query("SELECT setval('lesson_seq', $1, true)", [top]);
      expect(await sequences()).toEqual([]);
    });

    it("lists one entity's audit trail, most recent first, within the limit", async () => {
      for (const title of ["One", "Two", "Three"]) {
        const revision = Number((await h.pool.query<Record<string, unknown>>("SELECT revision FROM courses WHERE id = $1", [seed.courses.beta])).rows[0]?.revision);
        await call(h, "PATCH", `/courses/${seed.courses.beta}`, { body: { expectedRevision: revision, title } });
      }
      const trail = await call<AuditData>(h, "GET", `/audit?entity=course:${seed.courses.beta}&limit=2`);
      expect(trail.data.entries.map((entry) => entry.after?.title)).toEqual(["Three", "Two"]);
      expect(trail.data.entries[0]).toMatchObject({ actor: "cli:tower-catalog", action: "course.update", before: { title: "Two" }, releaseNumber: null });
      expect((await call(h, "GET", `/audit?entity=course:${seed.courses.beta}&limit=500`)).status).toBe(400);
    });
  });

  describe("HTTP contract", () => {
    it("refuses bodies over 1 MB (413), invalid JSON, unknown fields and a bad actor (400) with issue paths but no values", async () => {
      const big = await call(h, "PUT", "/texts", { raw: JSON.stringify([{ text: "x".repeat(1024 * 1024) }]) });
      expect([big.status, big.body.error?.code]).toEqual([413, "payload_too_large"]);
      const declared = await call(h, "PUT", "/texts", { raw: "[]", headers: { "content-length": String(2 * 1024 * 1024) } });
      expect(declared.status).toBe(413);
      expect((await call(h, "PUT", "/texts", { raw: "{not json" })).body.error?.code).toBe("invalid");
      const strict = await call(h, "POST", "/courses", { key: key(), body: { slug: "x", authorId: seed.authors[0], title: "X", coverFrom: "own", secretField: "do-not-echo" } });
      expect(strict.status).toBe(400);
      expect(JSON.stringify(strict.body)).not.toContain("do-not-echo");
      expect((strict.body.error?.details as { path: string; code: string }[])[0]).toMatchObject({ code: "unrecognized_keys" });
      expect((await call(h, "GET", "/courses", { actor: "Not Valid!" })).status).toBe(400);
      expect((await call(h, "GET", "/courses", { actor: "cli:tower-catalog@box daniel" })).status).toBe(200);
      const leaked = await call(h, "GET", "/courses", { actor: `cli:${SECRET}` });
      expect(leaked.status).toBe(400);
      expect(JSON.stringify(leaked.body)).not.toContain(SECRET);
      expect((await call(h, "GET", "/courses?status=bogus")).status).toBe(400);
      expect((await call(h, "GET", "/courses/NOT_AN_ID")).status).toBe(400);
    });

    it("answers 502 without driver detail when the database fails, and counts failed auths on the shared limiter", async () => {
      const broken = h.depsWith({ pool: () => ({ query: () => Promise.reject(Object.assign(new Error("password authentication failed for postgres://u:p@h"), { code: "28P01" })), connect: () => Promise.reject(new Error("x")) }) });
      const failed = await call(h, "GET", "/courses", { deps: broken });
      expect([failed.status, failed.body.error?.message]).toEqual([502, "The catalog database or storage failed (Error 28P01)."]);
      expect(JSON.stringify(failed.body)).not.toMatch(/password|postgres:/);
      const limiter = createAdminRateLimiter({ requests: 100, failures: 2 });
      const deps = h.depsWith({ limiter });
      await call(h, "GET", "/courses", { deps, token: "nope" });
      await call(h, "GET", "/courses", { deps, token: "nope" });
      expect((await call(h, "GET", "/courses", { deps, token: "nope" })).status).toBe(429);
      expect((await call(h, "GET", "/courses", { deps })).status).toBe(200);
    });

    it("prunes idempotency keys older than 30 days on the next idempotent POST", async () => {
      await h.pool.query(`INSERT INTO admin_idempotency (key, route, request_sha256, status, response, created_at) VALUES
        ('old', 'POST /api/admin/catalog/courses', '${"0".repeat(64)}', 201, '{}', now() - interval '31 days'),
        ('recent', 'POST /api/admin/catalog/courses', '${"0".repeat(64)}', 201, '{}', now() - interval '29 days')`);
      await call(h, "POST", "/authors", { key: key(), body: { slug: "pruner", name: "P", monogram: "P", kind: "person" } });
      expect((await h.pool.query<Record<string, unknown>>("SELECT key FROM admin_idempotency WHERE key IN ('old', 'recent')")).rows).toEqual([{ key: "recent" }]);
    });
  });

  describe("preview (draft mode)", () => {
    it("compiles the token's draft course with placeholders, uncached, without changing the active release", async () => {
      const draft = await seedDraftCourse(h, seed, "preview-me", { ready: false });
      const release = await activeRelease(h);
      const scoped = await compileDraftCatalog(h.pool, draft.id);
      const course = scoped.catalog.courses.find((entry) => entry.id === draft.id);
      expect(course).toMatchObject({ slug: "preview-me", displayTitle: "[displayTitle]" });
      expect(scoped.catalog.lessons.filter((lesson) => lesson.courseId === draft.id)).toHaveLength(2);
      expect(scoped.catalog.courses.map((entry) => entry.id)).toEqual([seed.courses.alpha, seed.courses.beta, draft.id]);
      const other = await seedDraftCourse(h, seed, "other-draft");
      expect((await compileDraftCatalog(h.pool, draft.id)).catalog.courses.map((entry) => entry.id)).not.toContain(other.id);
      expect((await compileDraftCatalog(h.pool, null)).catalog.courses.map((entry) => entry.id)).toEqual(expect.arrayContaining([draft.id, other.id]));
      // Without preview, the site's release does not have it (/c/preview-me stays a 404).
      expect(await activeRelease(h)).toEqual(release);
      const payload = (await h.pool.query<{ payload: { courses: { slug: string }[] } }>("SELECT payload FROM catalog_releases WHERE is_active")).rows[0]?.payload;
      expect(payload?.courses.map((entry) => entry.slug)).not.toContain("preview-me");
      // A production compile of the same tables is unaffected by preview placeholders.
      expect(compileRelease(await readCatalogTables(h.pool), { number: 1, publishedAt: NOW.toISOString() }).courses.map((entry) => entry.id)).toEqual([seed.courses.alpha, seed.courses.beta]);
    });

    it("issues a scoped preview URL with a short-lived token", async () => {
      const draft = await seedDraftCourse(h, seed, "preview-url");
      const issued = await call(h, "POST", "/preview-token", { body: { courseId: draft.id, ttlMinutes: 15 } });
      expect(issued.data).toMatchObject({ to: "/c/preview-url", courseId: draft.id, expiresAt: "2026-10-11T12:15:00.000Z" });
      expect(issued.data.url).toMatch(/^\/api\/catalog\/preview\?token=[\w-]+\.[\w-]+&to=%2Fc%2Fpreview-url$/);
      expect(issued.data.url).not.toContain(SECRET);
      expect((await call(h, "POST", "/preview-token", { body: {} })).data.to).toBe("/");
      expect((await call(h, "POST", "/preview-token", { body: { courseId: "course-404" } })).status).toBe(404);
      expect((await call(h, "POST", "/preview-token", { body: { ttlMinutes: 61 } })).status).toBe(400);
    });
  });

  describe("media integration", () => {
    let directory: string;
    beforeAll(async () => { directory = await mkdtemp(path.join(tmpdir(), "tower-admin-media-")); });
    afterAll(async () => { await rm(directory, { recursive: true, force: true }); });

    it("uploads a cover for a draft course that GET /courses/:id then shows; an unknown owner is 404", async () => {
      const draft = await seedDraftCourse(h, seed, "covered", { ready: false });
      const deps = {
        secret: SECRET, limiter: createAdminRateLimiter({ requests: 100, failures: 100 }), db: () => h.pool, store: () => createFsMediaStore(directory, MEDIA_PUBLIC_HOST),
        invalidate: () => undefined, courseOf: catalogCourseOf(() => h.pool), owners: catalogOwners,
      };
      const image = await sharp({ create: { width: 540, height: 960, channels: 3, background: "#334455" } }).jpeg().toBuffer();
      const upload = (ownerId: string) => {
        const form = new FormData();
        form.set("file", new Blob([new Uint8Array(image)], { type: "image/jpeg" }), "poster.jpg");
        for (const [name, value] of Object.entries({ owner: "course", ownerId, kind: "poster_9x16", alt: "Poster" })) form.set(name, value);
        return handleAdminMediaUpload(new Request("https://tower.test/api/admin/media", { method: "POST", headers: { authorization: `Bearer ${SECRET}` }, body: form }), deps);
      };
      expect((await upload(draft.id)).status).toBe(200);
      const detail = await call<CourseDetail>(h, "GET", `/courses/${draft.id}`);
      expect(detail.data.covers.map((cover) => cover.kind)).toEqual(["poster_9x16"]);
      expect(detail.data.preconditions?.review.filter((failure) => failure.rule === "covers.active")).toHaveLength(3);
      expect((await upload("course-9999")).status).toBe(404);
    });
  });
});
