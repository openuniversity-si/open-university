import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { createAdminRateLimiter } from "../../src/platform/security/rate-limit.ts";
import { validateCourseBundle } from "../../src/catalog/domain/bundle.ts";
import { batchContentHash } from "../../src/catalog/domain/ship-batch.ts";
import { batchV2Hash } from "../../src/catalog/domain/batch-v2.ts";
import { catalogBatchV2Schema } from "../../src/catalog/domain/schema/batch-v2.ts";
import { ADMIN_CATALOG_ROUTES } from "../../src/catalog/server/routes.ts";
import {
  auditRows, call, catalogFingerprint, createHarness, newVideoId, revisionOf, seedCatalog, seedDraftCourse, type Harness, type Seed,
} from "../fixtures/admin-catalog.ts";

// The per-route case table the brief requires: every route of routes.ts must have a scenario here (a missing one fails),
// and the generic cases below run for each: auth (401/429/503), envelope and no-store for all; audit in the same
// transaction (with an injected audit failure), expectedRevision and Idempotency-Key for the mutations that take them.

interface Request { readonly target: string; readonly body?: unknown }
interface Scenario {
  /** The request on a freshly seeded catalog (setup may write through SQL or the API). */
  readonly happy: (seed: Seed, harness: Harness) => Promise<Request>;
  readonly status?: number;
  /** Same route, a different valid body/query: the idempotency mismatch case. */
  readonly variant?: (request: Request) => Request;
  /** The table and row whose revision the request carries, for the revision_conflict case. */
  readonly revision?: (seed: Seed, request: Request) => { table: "courses" | "course_editions" | "lessons" | "authors" | "content_sources" | "home"; id: string };
}

const lessonBody = (editionId: string) => ({ editionId, youtubeId: newVideoId(), durationSeconds: 600 });
const sampleBundle = (title = "Bundled") => ({
  version: 1,
  author: { id: "bundle-author", slug: "bundle-author", name: "Bundle Author", monogram: "BA", kind: "person" },
  course: { id: `bundle-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")}`, slug: `bundle-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")}`, title, authorId: "bundle-author", lessonNoun: "Lecture" as const, coverFrom: "own", sharedWith: [] },
  editions: [{ id: "bundle-edition", slug: "original", label: "Original", position: 1, year: 2020 }],
  lessons: [{ id: "bundle-lesson", editionId: "bundle-edition", slug: "intro", title: "Intro", position: 1, youtubeId: "abcdefghijk", durationSeconds: 60, part: "lectures" as const }],
});
/** A second, empty edition of alpha (Fall 2024, after the seeded Fall 2025). */
const olderEdition = async (seed: Seed, h: Harness) => (await h.pool.query<{ id: string }>("INSERT INTO course_editions (course_id, slug, label, term, year, position) VALUES ($1, 'fall-2024', 'Fall 2024', 'fall', 2024, 2) RETURNING id", [seed.courses.alpha])).rows[0]?.id ?? "";
const homeBody = (seed: Seed, expectedRevision: number) => ({
  featuredCourseId: seed.courses.alpha, expectedRevision,
  rows: [{ id: "continue", kind: "continue", courseIds: [] }, { id: "picks", kind: "curated", title: "Picks", courseIds: [seed.courses.beta, seed.courses.alpha] }],
});
const withRevision = (target: string, revision: number) => target.replace(/expectedRevision=\d+/, `expectedRevision=${String(revision)}`);
const replaceBody = (request: Request, patch: Record<string, unknown>): Request => ({ ...request, body: { ...(request.body as Record<string, unknown>), ...patch } });
const rev = (harness: Harness, table: "courses" | "course_editions" | "lessons" | "authors" | "content_sources", id: string) => revisionOf(harness, table, id);

const scenarios: Record<string, Scenario> = {
  "GET /courses": { happy: () => Promise.resolve({ target: "/courses?status=published" }) },
  "POST /courses": {
    happy: (seed) => Promise.resolve({ target: "/courses", body: { slug: "gamma", authorId: seed.authors[0], title: "Gamma", coverFrom: "own" } }), status: 201,
    variant: (request) => replaceBody(request, { title: "Gamma II" }),
  },
  "GET /courses/:id": { happy: (seed) => Promise.resolve({ target: `/courses/${seed.courses.alpha}` }) },
  "PATCH /courses/:id": {
    happy: async (seed, h) => ({ target: `/courses/${seed.courses.alpha}`, body: { expectedRevision: await rev(h, "courses", seed.courses.alpha), title: "Alpha renamed" } }),
    revision: (seed) => ({ table: "courses", id: seed.courses.alpha }),
  },
  "DELETE /courses/:id": {
    happy: async (seed, h) => {
      const draft = await seedDraftCourse(h, seed, "to-purge");
      return { target: `/courses/${draft.id}?mode=purge&confirm=true&expectedRevision=${String(await rev(h, "courses", draft.id))}` };
    },
    revision: (_seed, request) => ({ table: "courses", id: /courses\/([^?]+)/.exec(request.target)?.[1] ?? "" }),
  },
  "POST /courses/:id/status": {
    happy: async (seed, h) => {
      const draft = await seedDraftCourse(h, seed, "to-review");
      return { target: `/courses/${draft.id}/status`, body: { to: "review", expectedRevision: await rev(h, "courses", draft.id) } };
    },
    revision: (_seed, request) => ({ table: "courses", id: request.target.split("/")[2] ?? "" }),
  },
  "POST /courses/:id/publish": {
    happy: async (seed, h) => {
      const draft = await seedDraftCourse(h, seed, "to-publish");
      await h.pool.query("UPDATE courses SET status = 'review' WHERE id = $1", [draft.id]);
      return { target: `/courses/${draft.id}/publish`, body: { expectedRevision: await rev(h, "courses", draft.id), note: "Publish it", allowOrphan: true } };
    },
    variant: (request) => replaceBody(request, { note: "Another note" }),
    revision: (_seed, request) => ({ table: "courses", id: request.target.split("/")[2] ?? "" }),
  },
  "POST /courses/publish-batch": {
    happy: async (seed, h) => {
      const one = await seedDraftCourse(h, seed, "batch-one");
      const two = await seedDraftCourse(h, seed, "batch-two");
      await h.pool.query("UPDATE courses SET status = 'review' WHERE id = ANY($1::text[])", [[one.id, two.id]]);
      return { target: "/courses/publish-batch", body: { courses: [{ id: one.id, expectedRevision: await rev(h, "courses", one.id) }, { id: two.id, expectedRevision: await rev(h, "courses", two.id) }], note: "Batch", allowOrphan: true } };
    },
    // Per-course expectedRevision (not a top-level one): the stale-revision case lives in catalog-admin-batch.int.test.ts.
    variant: (request) => replaceBody(request, { note: "Another note" }),
  },
  "POST /media/references": { happy: () => Promise.resolve({ target: "/media/references", body: { keys: ["covers/unused/poster_9x16/a.jpg"] } }) },
  "POST /courses/classify": {
    happy: (seed) => Promise.resolve({ target: "/courses/classify", body: { items: [{ id: seed.courses.alpha, areaId: "engineering", subareaId: "mechanical-engineering" }, { id: seed.courses.beta, areaId: "psychology" }] } }),
    // Set semantics (no expectedRevision): writing what a course already has is a noop; stale revisions do not apply.
    variant: (request) => ({ ...request, body: { items: [{ id: (request.body as { items: { id: string }[] }).items[0]?.id, areaId: "engineering", subareaId: "electrical-engineering" }] } }),
  },
  "POST /courses/:id/unpublish": {
    happy: async (seed, h) => ({ target: `/courses/${seed.courses.beta}/unpublish`, body: { expectedRevision: await rev(h, "courses", seed.courses.beta), note: "Take it down" } }),
    variant: (request) => replaceBody(request, { note: "Another note" }),
    revision: (seed) => ({ table: "courses", id: seed.courses.beta }),
  },
  "GET /courses/:id/editions": { happy: (seed) => Promise.resolve({ target: `/courses/${seed.courses.alpha}/editions` }) },
  "POST /courses/:id/editions": {
    happy: (seed) => Promise.resolve({ target: `/courses/${seed.courses.alpha}/editions`, body: { slug: "spring-2026", label: "Spring 2026", term: "spring", year: 2026 } }), status: 201,
    variant: (request) => replaceBody(request, { resolution: "1080p" }),
  },
  "PUT /courses/:id/editions/order": {
    happy: async (seed, h) => {
      const older = await olderEdition(seed, h);
      return { target: `/courses/${seed.courses.alpha}/editions/order`, body: { editionIds: [older, seed.editions.alpha], expectedRevision: await rev(h, "courses", seed.courses.alpha) } };
    },
    revision: (seed) => ({ table: "courses", id: seed.courses.alpha }),
  },
  "PATCH /editions/:id": {
    happy: async (seed, h) => ({ target: `/editions/${seed.editions.alpha}`, body: { expectedRevision: await rev(h, "course_editions", seed.editions.alpha), resolution: "720p" } }),
    revision: (seed) => ({ table: "course_editions", id: seed.editions.alpha }),
  },
  "DELETE /editions/:id": {
    happy: async (seed, h) => {
      const older = await olderEdition(seed, h);
      return { target: `/editions/${older}?confirm=true&expectedRevision=${String(await rev(h, "course_editions", older))}` };
    },
    revision: (_seed, request) => ({ table: "course_editions", id: /editions\/([^?]+)/.exec(request.target)?.[1] ?? "" }),
  },
  "PUT /editions/:id/lessons/order": {
    happy: async (seed, h) => ({ target: `/editions/${seed.editions.alpha}/lessons/order`, body: { lessonIds: [...seed.lessons.alpha].reverse(), expectedRevision: await rev(h, "courses", seed.courses.alpha) } }),
    revision: (seed) => ({ table: "courses", id: seed.courses.alpha }),
  },
  "POST /courses/:id/lessons": {
    happy: async (seed, h) => {
      const draft = await seedDraftCourse(h, seed, "takes-lessons", { ready: false });
      return { target: `/courses/${draft.id}/lessons`, body: lessonBody(draft.edition) };
    },
    status: 201,
    variant: (request) => replaceBody(request, { durationSeconds: 601 }),
  },
  "PUT /courses/:id/lessons/order": {
    happy: async (seed, h) => ({ target: `/courses/${seed.courses.alpha}/lessons/order`, body: { lessonIds: [...seed.lessons.alpha].reverse(), expectedRevision: await rev(h, "courses", seed.courses.alpha) } }),
    revision: (seed) => ({ table: "courses", id: seed.courses.alpha }),
  },
  "PUT /lessons/slugs": {
    happy: async (seed, h) => ({ target: "/lessons/slugs", body: { courseId: seed.courses.alpha, expectedRevision: await rev(h, "courses", seed.courses.alpha), changes: [{ lessonId: seed.lessons.alpha[0] ?? "", slug: "the-start" }] } }),
    revision: (seed) => ({ table: "courses", id: seed.courses.alpha }),
    variant: (request) => replaceBody(request, { changes: [{ lessonId: ((request.body as { changes: { lessonId: string }[] }).changes[0]?.lessonId ?? ""), slug: "another-start" }] }),
  },
  "PATCH /lessons/:id": {
    happy: async (seed, h) => ({ target: `/lessons/${seed.lessons.alpha[0] ?? ""}`, body: { expectedRevision: await rev(h, "lessons", seed.lessons.alpha[0] ?? ""), kind: "background" } }),
    revision: (seed) => ({ table: "lessons", id: seed.lessons.alpha[0] ?? "" }),
  },
  "DELETE /lessons/:id": {
    happy: async (seed, h) => {
      const draft = await seedDraftCourse(h, seed, "loses-lesson", { lessons: 3 });
      const lesson = draft.lessons[1] ?? "";
      return { target: `/lessons/${lesson}?confirm=true&expectedRevision=${String(await rev(h, "lessons", lesson))}` };
    },
    revision: (_seed, request) => ({ table: "lessons", id: /lessons\/([^?]+)/.exec(request.target)?.[1] ?? "" }),
  },
  "GET /authors": { happy: () => Promise.resolve({ target: "/authors" }) },
  "POST /authors": {
    happy: () => Promise.resolve({ target: "/authors", body: { slug: "cy-three", name: "Cy Three", monogram: "CT", kind: "person" } }), status: 201,
    variant: (request) => replaceBody(request, { name: "Cy Third" }),
  },
  "PATCH /authors/:id": {
    happy: async (seed, h) => ({ target: `/authors/${seed.authors[1]}`, body: { expectedRevision: await rev(h, "authors", seed.authors[1]), name: "Bob Renamed" } }),
    revision: (seed) => ({ table: "authors", id: seed.authors[1] }),
  },
  "DELETE /authors/:id": {
    happy: async (seed, h) => ({ target: `/authors/${seed.authors[1]}?confirm=true&expectedRevision=${String(await rev(h, "authors", seed.authors[1]))}` }),
    revision: (seed) => ({ table: "authors", id: seed.authors[1] }),
  },
  "GET /texts": { happy: (seed) => Promise.resolve({ target: `/texts?entity=course:${seed.courses.alpha}` }) },
  "PUT /texts": {
    happy: (seed) => Promise.resolve({ target: "/texts", body: [{ entityKind: "course", entityId: seed.courses.alpha, field: "subtitle", text: "A new subtitle", source: "manual", sourceRef: "int", confidence: "high" }] }),
  },
  "POST /texts/approve": {
    happy: async (seed, h) => {
      await h.pool.query("UPDATE catalog_texts SET text = 'Edited subtitle', status = 'draft', approved_by = NULL, approved_at = NULL, approved_sha256 = NULL WHERE entity_id = $1 AND field = 'subtitle'", [seed.courses.alpha]);
      const { rows } = await h.pool.query<{ text_sha256: string }>("SELECT text_sha256 FROM catalog_texts WHERE entity_id = $1 AND field = 'subtitle'", [seed.courses.alpha]);
      return { target: "/texts/approve", body: { items: [{ entityKind: "course", entityId: seed.courses.alpha, field: "subtitle", sha256: rows[0]?.text_sha256 }], approvedBy: "Daniel" } };
    },
    variant: (request) => replaceBody(request, { approvedBy: "Someone else" }),
  },
  "POST /texts/revoke": {
    happy: (seed) => Promise.resolve({ target: "/texts/revoke", body: { items: [{ entityKind: "course", entityId: seed.courses.alpha, field: "subtitle" }] } }),
    variant: (request) => ({ ...request, body: { items: [...(request.body as { items: unknown[] }).items, { entityKind: "course", entityId: (request.body as { items: { entityId: string }[] }).items[0]?.entityId, field: "level" }] } }),
  },
  "GET /home": { happy: () => Promise.resolve({ target: "/home" }) },
  "PUT /home": {
    happy: (seed) => Promise.resolve({ target: "/home", body: homeBody(seed, 1) }),
    revision: () => ({ table: "home", id: "home" }),
  },
  "GET /areas": { happy: () => Promise.resolve({ target: "/areas" }) },
  "POST /areas": {
    happy: () => Promise.resolve({ target: "/areas", body: { id: "design", title: "Design" } }), status: 201,
    variant: (request) => replaceBody(request, { title: "Product Design" }),
  },
  "PATCH /areas/:id": { happy: () => Promise.resolve({ target: "/areas/law", body: { title: "Legal Studies" } }) },
  "POST /areas/:id/move": {
    happy: () => Promise.resolve({ target: "/areas/law/move", body: { position: 1 } }),
    variant: (request) => replaceBody(request, { position: 2 }),
  },
  "GET /subareas": { happy: () => Promise.resolve({ target: "/subareas" }) },
  "POST /subareas": {
    happy: () => Promise.resolve({ target: "/subareas", body: { id: "naval-engineering", areaId: "engineering", title: "Naval Engineering" } }), status: 201,
    variant: (request) => replaceBody(request, { title: "Naval Architecture" }),
  },
  "GET /licenses": { happy: () => Promise.resolve({ target: "/licenses" }) },
  "POST /licenses": {
    happy: () => Promise.resolve({ target: "/licenses", body: { code: "cc-by-4.0", name: "CC BY 4.0", url: "https://creativecommons.org/licenses/by/4.0/", requiresAttribution: true } }), status: 201,
    variant: (request) => replaceBody(request, { name: "Creative Commons BY 4.0" }),
  },
  "GET /sources": { happy: () => Promise.resolve({ target: "/sources" }) },
  "POST /sources": {
    happy: () => Promise.resolve({ target: "/sources", body: { id: "src-new", kind: "institution-site", title: "New", publisher: "New U", url: "https://example.org/new" } }), status: 201,
    variant: (request) => replaceBody(request, { title: "Newer" }),
  },
  "PATCH /sources/:id": {
    happy: async (seed, h) => ({ target: `/sources/${seed.source}`, body: { expectedRevision: await rev(h, "content_sources", seed.source), title: "Renamed source" } }),
    revision: (seed) => ({ table: "content_sources", id: seed.source }),
  },
  "POST /imports": {
    happy: () => Promise.resolve({ target: "/imports", body: { playlistUrl: "https://www.youtube.com/playlist?list=PLtest000001", items: [{ id: newVideoId(), title: "Lecture 1 - Start", duration: 1800, playlistIndex: 1 }] } }), status: 201,
    variant: (request) => replaceBody(request, { tool: "yt-dlp 2026.09" }),
  },
  "POST /imports/:id/draft": {
    happy: async (seed, h) => {
      const created = await call<{ import: { id: string } }>(h, "POST", "/imports", { key: `setup-${newVideoId()}`, body: { playlistUrl: "https://www.youtube.com/playlist?list=PLtest000002", items: [{ id: newVideoId(), title: "Lecture 1 - Start", duration: 1800 }] } });
      return { target: `/imports/${created.data.import.id}/draft`, body: { slug: "imported", authorId: seed.authors[0] } };
    },
    status: 201, variant: (request) => replaceBody(request, { slug: "imported-two" }),
  },
  "GET /releases": { happy: () => Promise.resolve({ target: "/releases" }) },
  "GET /releases/:n": { happy: () => Promise.resolve({ target: "/releases/1" }) },
  "POST /releases": {
    happy: async (_seed, h) => {
      await h.pool.query("UPDATE home_rows SET title = 'Top picks' WHERE id = 'picks'");
      return { target: "/releases", body: { note: "Manual release" } };
    },
    status: 201, variant: (request) => replaceBody(request, { note: "Another note" }),
  },
  "POST /releases/:n/activate": {
    happy: async (_seed, h) => {
      await h.pool.query("UPDATE home_rows SET title = 'Top picks' WHERE id = 'picks'");
      await call(h, "POST", "/releases", { key: `setup-${newVideoId()}`, body: { note: "Release 2" } });
      return { target: "/releases/1/activate", body: { note: "Roll back" } };
    },
    variant: (request) => replaceBody(request, { note: "Roll back again" }),
  },
  "GET /redirects": { happy: () => Promise.resolve({ target: "/redirects" }) },
  "POST /redirects": { happy: () => Promise.resolve({ target: "/redirects", body: { from: "/c/old-alpha", to: "/c/alpha" } }), status: 201 },
  "DELETE /redirects": {
    happy: async (_seed, h) => {
      await h.pool.query("INSERT INTO slug_redirects (from_path, to_path) VALUES ('/c/old-beta', '/c/beta')");
      return { target: `/redirects?from=${encodeURIComponent("/c/old-beta")}&confirm=true` };
    },
  },
  "POST /preview-token": { happy: (seed) => Promise.resolve({ target: "/preview-token", body: { courseId: seed.courses.alpha, ttlMinutes: 10 } }) },
  "GET /audit": { happy: (seed) => Promise.resolve({ target: `/audit?entity=course:${seed.courses.alpha}&limit=5` }) },
  "GET /tables": { happy: () => Promise.resolve({ target: "/tables" }) },
  "GET /doctor": { happy: () => Promise.resolve({ target: "/doctor" }) },
  "POST /bundles/validate": { happy: () => Promise.resolve({ target: "/bundles/validate", body: { bundle: sampleBundle() } }) },
  "POST /bundles/diff": { happy: () => Promise.resolve({ target: "/bundles/diff", body: { bundle: sampleBundle("Bundled two") } }) },
  "POST /bundles/export": { happy: () => Promise.resolve({ target: "/bundles/export", body: { bundle: sampleBundle("Bundled three") } }) },
  "POST /bundles/ship": {
    happy: () => {
      const bundle = sampleBundle("Ship Batch");
      const parsed = validateCourseBundle(bundle);
      if (!parsed.ok) throw parsed.error;
      return Promise.resolve({ target: "/bundles/ship", body: { batchHash: batchContentHash([parsed.value]), chunk: 0, chunks: 1, draft: true, bundles: [bundle] } });
    },
    variant: (request) => replaceBody(request, { note: "again" }),
    status: 201,
  },
  "POST /batches/apply": {
    happy: async (seed, h) => {
      const covers = (["poster_9x16", "hero_desktop_16x9", "hero_present", "hero_mobile_9x16"] as const).map((kind, index) => ({ kind, sha: String(index + 1).repeat(64) }));
      await h.pool.query(`INSERT INTO media_objects (sha256, ext, content_type, bytes, width, height)
        SELECT s, 'webp', 'image/webp', 100, 1080, 1920 FROM unnest($1::text[]) AS s ON CONFLICT (sha256) DO NOTHING`, [covers.map((cover) => cover.sha)]);
      const part = { version: 2, courses: [{ institutionId: seed.institution, course: { id: "batched", slug: "batched", title: "Batched", authorId: seed.authors[0], coverFrom: "own", sharedWith: [] },
        editions: [{ id: "batched-e", slug: "original", label: "Original", position: 1, year: 2020 }], covers }] };
      return Promise.resolve({ target: "/batches/apply", body: { batchHash: batchV2Hash(catalogBatchV2Schema.parse(part)), chunk: 0, chunks: 1, draft: true, part } });
    },
    variant: (request) => replaceBody(request, { note: "again" }),
    status: 201,
  },
  "POST /bundles/apply": {
    happy: async (seed, h) => {
      const bundle = sampleBundle(`Bundled ${newVideoId()}`);
      return { target: "/bundles/apply", body: { bundle: { ...bundle, author: { id: seed.authors[0], slug: "ann-one", name: "Ann One", monogram: "AO", kind: "person" }, course: { ...bundle.course, authorId: seed.authors[0] }, home: { rowId: "picks", expectedRevision: Number((await h.pool.query<{ revision: string }>("SELECT revision FROM catalog_home")).rows[0]?.revision ?? 0) } } } };
    },
    variant: (request) => {
      const body = request.body as { bundle: { course: { title: string } } };
      return { ...request, body: { bundle: { ...body.bundle, course: { ...body.bundle.course, title: `${body.bundle.course.title} II` } } } };
    },
    revision: () => ({ table: "home", id: "home" }),
  },
  "POST /jobs/claim": {
    happy: () => Promise.resolve({ target: "/jobs/claim", body: { idempotencyKey: `job-${newVideoId()}`, bundleSha256: "ab".repeat(32), environment: "preview", draft: true } }),
    variant: (request) => replaceBody(request, { bundleSha256: "cd".repeat(32) }),
  },
  "POST /jobs/:id/renew": {
    happy: async (_seed, h) => {
      const claimed = await call<{ jobId: string; token: number }>(h, "POST", "/jobs/claim", { key: `setup-${newVideoId()}`, body: { idempotencyKey: `job-${newVideoId()}`, bundleSha256: "ab".repeat(32), environment: "preview", draft: true } });
      return { target: `/jobs/${claimed.data.jobId}/renew`, body: { token: claimed.data.token, draft: true } };
    },
    variant: (request) => replaceBody(request, { token: (request.body as { token: number }).token + 1 }),
  },
  "POST /jobs/:id/advance": {
    happy: async (_seed, h) => {
      const claimed = await call<{ jobId: string; token: number }>(h, "POST", "/jobs/claim", { key: `setup-${newVideoId()}`, body: { idempotencyKey: `job-${newVideoId()}`, bundleSha256: "ab".repeat(32), environment: "preview", draft: true } });
      return { target: `/jobs/${claimed.data.jobId}/advance`, body: { token: claimed.data.token, expected: "VALIDATED", draft: true, checkpoint: { stage: "MEDIA_CHECKED", draft: true } } };
    },
    variant: (request) => replaceBody(request, { token: (request.body as { token: number }).token + 1 }),
  },
  "POST /jobs/:id/complete": {
    happy: async (_seed, h) => {
      const claimed = await call<{ jobId: string; token: number }>(h, "POST", "/jobs/claim", { key: `setup-${newVideoId()}`, body: { idempotencyKey: `job-${newVideoId()}`, bundleSha256: "ab".repeat(32), environment: "preview", draft: true } });
      return { target: `/jobs/${claimed.data.jobId}/complete`, body: { token: claimed.data.token, draft: true, stage: "VERIFIED" } };
    },
    variant: (request) => replaceBody(request, { error: "stopped" }),
  },
  "POST /lifecycle/inventory": { happy: () => Promise.resolve({ target: "/lifecycle/inventory" }) },
  "POST /lifecycle/gc": {
    happy: () => Promise.resolve({ target: "/lifecycle/gc", body: { op: "storage-list", cursor: null } }),
    variant: (request) => replaceBody(request, { cursor: "0" }),
  },
  "POST /lifecycle/preview-reset": {
    happy: () => Promise.resolve({ target: "/lifecycle/preview-reset", body: { dryRun: true } }),
    variant: (request) => replaceBody(request, { dryRun: false }),
  },
};

describe("admin catalog API: per-route cases on PG18", () => {
  let h: Harness;
  let seed: Seed;
  beforeAll(() => { h = createHarness(); });
  afterAll(async () => { await h.close(); });
  beforeEach(async () => { seed = await seedCatalog(h); });

  it("has a scenario for every route of routes.ts, and for nothing else", () => {
    expect(Object.keys(scenarios).sort()).toEqual(ADMIN_CATALOG_ROUTES.map((route) => route.key).sort());
  });

  it("covers revision_conflict for every route taking expectedRevision, and idempotency for every route requiring a key", () => {
    const revisioned = ["PATCH /courses/:id", "DELETE /courses/:id", "POST /courses/:id/status", "POST /courses/:id/publish", "POST /courses/:id/unpublish", "PUT /courses/:id/lessons/order",
      "PUT /courses/:id/editions/order", "PATCH /editions/:id", "DELETE /editions/:id", "PUT /editions/:id/lessons/order", "PUT /lessons/slugs", "PATCH /lessons/:id", "DELETE /lessons/:id", "PATCH /authors/:id", "DELETE /authors/:id", "PUT /home", "PATCH /sources/:id", "POST /bundles/apply"];
    expect(Object.entries(scenarios).filter(([, scenario]) => scenario.revision).map(([key]) => key).sort()).toEqual(revisioned.sort());
    for (const route of ADMIN_CATALOG_ROUTES.filter((entry) => entry.idempotency !== "none")) expect(scenarios[route.key]?.variant, route.key).toBeDefined();
  });

  for (const route of ADMIN_CATALOG_ROUTES) {
    const scenario = scenarios[route.key];
    if (!scenario) continue;
    const send = (request: Request, options: Parameters<typeof call>[3] = {}) => call(h, route.method, request.target, {
      ...(request.body === undefined ? {} : { body: request.body }), ...(route.idempotency === "none" ? {} : { key: `key-${route.method}-${route.path}`.replace(/[^A-Za-z0-9._:-]/g, "_") }), ...options,
    });

    describe(route.key, () => {
      it("answers 401 without or with a wrong Bearer, 503 without a secret and 429 over the limit, all no-store", async () => {
        const request = await scenario.happy(seed, h);
        for (const response of [await send(request, { token: null }), await send(request, { token: "wrong-secret" })]) {
          expect(response.status).toBe(401);
          expect(response.body).toMatchObject({ ok: false, error: { code: "unauthorized" } });
          expect(response.headers.get("cache-control")).toBe("no-store");
        }
        const unconfigured = await send(request, { deps: h.depsWith({ secret: undefined }) });
        expect([unconfigured.status, unconfigured.body.error?.code]).toEqual([503, "unconfigured"]);
        const limited = await send(request, { deps: h.depsWith({ limiter: createAdminRateLimiter({ requests: 0, failures: 10, authenticated: 0 }) }) });
        expect(Number(limited.headers.get("Retry-After"))).toBeGreaterThan(0);
        expect([limited.status, limited.body.error?.code, limited.headers.get("cache-control")]).toEqual([429, "rate_limited", "no-store"]);
      });

      it("answers the envelope with the echoed request id, no-store", async () => {
        const response = await send(await scenario.happy(seed, h), { requestId: "int-req-1" });
        expect(response.body.error, JSON.stringify(response.body.error)).toBeUndefined();
        expect(response.status).toBe(scenario.status ?? 200);
        expect(response.body).toMatchObject({ ok: true, requestId: "int-req-1" });
        expect(response.headers.get("x-request-id")).toBe("int-req-1");
        expect(response.headers.get("cache-control")).toBe("no-store");
        const generated = await send(await scenario.happy(await seedCatalog(h), h), { requestId: "bad id!" });
        expect(generated.body.requestId).toMatch(/^00000000-0000-4000-8000-\d{12}$/);
      });

      if (route.action === null) {
        it("writes nothing and audits nothing", async () => {
          const request = await scenario.happy(seed, h);
          const before = await catalogFingerprint(h);
          expect((await send(request)).body.ok).toBe(true);
          expect(await catalogFingerprint(h)).toBe(before);
        });
        return;
      }

      it("audits the mutation with actor, request id and before/after, in its transaction", async () => {
        const response = await send(await scenario.happy(seed, h), { requestId: "int-audit", actor: "cli:tower-catalog@int" });
        expect(response.body.error, JSON.stringify(response.body.error)).toBeUndefined();
        const rows = await auditRows(h, { requestId: "int-audit" });
        expect(rows.length).toBeGreaterThan(0);
        expect(rows.every((row) => row.actor === "cli:tower-catalog@int")).toBe(true);
        expect(rows.some((row) => row.action.startsWith(route.action ?? "-"))).toBe(true);
        expect(rows.every((row) => row.before !== null || row.after !== null)).toBe(true);
        expect(JSON.stringify(rows)).not.toContain(h.deps.secret ?? "-");
        expect(h.logs.some((line) => line.includes('"event":"CATALOG_ADMIN"') && line.includes('"requestId":"int-audit"'))).toBe(true);
      });

      it("rolls the whole mutation back when its audit row cannot be written", async () => {
        const request = await scenario.happy(seed, h);
        const before = await catalogFingerprint(h);
        h.recorder.events.length = 0;
        await h.pool.query(`CREATE OR REPLACE FUNCTION int_fail_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'audit refused' USING ERRCODE = 'P0001'; END $$;
          CREATE TRIGGER int_fail_audit BEFORE INSERT ON catalog_audit FOR EACH ROW EXECUTE FUNCTION int_fail_audit();`);
        try {
          const response = await send(request);
          expect([response.status, response.body.error?.code]).toEqual([502, "upstream_failed"]);
          expect(response.body.error?.message).not.toContain("audit refused");
        } finally {
          await h.pool.query("DROP TRIGGER int_fail_audit ON catalog_audit; DROP FUNCTION int_fail_audit();");
        }
        expect(await catalogFingerprint(h)).toBe(before);
        expect(h.recorder.events.filter((event) => event === "invalidate" || event.startsWith("r2:delete"))).toEqual([]);
      });

      if (scenario.revision) {
        const target = scenario.revision;
        it("answers 409 revision_conflict with the current revision for a stale expectedRevision", async () => {
          const request = await scenario.happy(seed, h);
          const { table, id } = target(seed, request);
          const current = table === "home" ? Number((await h.pool.query<{ revision: number }>("SELECT revision FROM catalog_home")).rows[0]?.revision) : await revisionOf(h, table, id);
          const body = request.body as { bundle?: { home?: { expectedRevision?: number } } } | undefined;
          const home = body?.bundle?.home;
          const stale = request.target.includes("expectedRevision=")
            ? { ...request, target: withRevision(request.target, current + 7) }
            : home
              ? { ...request, body: { ...body, bundle: { ...body.bundle, home: { ...home, expectedRevision: current + 7 } } } }
              : replaceBody(request, { expectedRevision: current + 7 });
          const before = await catalogFingerprint(h);
          const response = await send(stale);
          expect(response.status).toBe(409);
          expect(response.body.error).toMatchObject({ code: "revision_conflict", details: { currentRevision: current } });
          expect(await catalogFingerprint(h)).toBe(before);
        });
      }

      if (route.idempotency !== "none") {
        it("requires an Idempotency-Key", async () => {
          const response = await call(h, route.method, (await scenario.happy(seed, h)).target, { body: (await scenario.happy(await seedCatalog(h), h)).body });
          expect([response.status, response.body.error?.code]).toEqual([400, "invalid"]);
        });

        it("replays the stored response for the same key and body, without executing or auditing again", async () => {
          const request = await scenario.happy(seed, h);
          const first = await send(request, { requestId: "first" });
          expect(first.body.ok, JSON.stringify(first.body.error)).toBe(true);
          const audits = (await auditRows(h)).length;
          const fingerprint = await catalogFingerprint(h);
          const replay = await send(request, { requestId: "second" });
          expect(replay.status).toBe(first.status);
          expect(replay.data).toEqual(first.data);
          expect(replay.headers.get("idempotent-replay")).toBe("true");
          expect(replay.body.requestId).toBe("second");
          expect((await auditRows(h)).length).toBe(audits);
          expect(await catalogFingerprint(h)).toBe(fingerprint);
        });

        it("answers 422 idempotency_mismatch for the same key with another body or route", async () => {
          const request = await scenario.happy(seed, h);
          expect((await send(request)).body.ok).toBe(true);
          const variant = scenario.variant?.(request) ?? request;
          const mismatch = await send(variant);
          expect([mismatch.status, mismatch.body.error?.code]).toEqual([422, "idempotency_mismatch"]);
          const elsewhere = await call(h, "POST", "/licenses", { key: `key-${route.method}-${route.path}`.replace(/[^A-Za-z0-9._:-]/g, "_"), body: { code: "other-license", name: "Other", requiresAttribution: false } });
          expect([elsewhere.status, elsewhere.body.error?.code]).toEqual([422, "idempotency_mismatch"]);
        });

        it("executes once when two requests with the same key race", async () => {
          const request = await scenario.happy(seed, h);
          const before = (await auditRows(h)).length;
          const [a, b] = await Promise.all([send(request, { requestId: "race-a" }), send(request, { requestId: "race-b" })]);
          expect([a.body.ok, b.body.ok]).toEqual([true, true]);
          expect(a.data).toEqual(b.data);
          expect([a.headers.get("idempotent-replay"), b.headers.get("idempotent-replay")].filter((value) => value === "true")).toHaveLength(1);
          const executed = (await auditRows(h)).slice(before);
          expect(new Set(executed.map((row) => row.request_id)).size).toBe(1);
        });
      }
    });
  }
});
