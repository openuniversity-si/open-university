import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { validateCourseBundle, type CourseBundleV1 } from "../domain/bundle.ts";
import { TEXT_FIELDS } from "../domain/fields.ts";
import { REQUIRED_COVERS } from "../domain/rules/status.ts";
import { batchContentHash } from "../domain/ship-batch.ts";
import { swapMedia } from "../../media/server/repository.ts";
import {
  call, coverInput, createHarness, seedCatalog, slotText, type Harness,
} from "../../../test/fixtures/admin-catalog.ts";

// Verifies: D-002
function youtube(index: number): string {
  return `shipvid${String(index).padStart(4, "0")}`;
}

function bundleOf(id: string, index: number, publish: boolean, video?: { lessonId?: string; youtubeId?: string; sharedWith?: string[] }): CourseBundleV1 {
  const lessonId = video?.lessonId ?? `${id}-l`;
  const youtubeId = video?.youtubeId ?? youtube(index);
  const texts = publish
    ? [
      ...Object.keys(TEXT_FIELDS.course).map((field) => ({
        entityKind: "course", entityId: id, field, text: slotText(field, "s"), approved: true, approvedBy: "editor", approvedAt: "2020-01-01T00:00:00.000Z",
      })),
      { entityKind: "lesson", entityId: lessonId, field: "displayTitle", text: "Intro", approved: true, approvedBy: "editor", approvedAt: "2020-01-01T00:00:00.000Z" },
    ]
    : [];
  const parsed = validateCourseBundle({
    version: 1,
    author: { id: "author-ship", slug: "ship-author", name: "Ship Author", monogram: "SA", kind: "person" },
    course: {
      id, slug: id, title: `Ship ${id}`, authorId: "author-ship", coverFrom: "own", sharedWith: video?.sharedWith ?? [],
      ...(publish ? {
        areaId: "computer-science", subareaId: "programming", licenseCode: "youtube-standard", sourceId: "src-test",
        canonicalUrl: `https://example.org/${id}`, rightsStatus: "cleared", coverFrom: "subarea:programming",
      } : {}),
    },
    editions: [{ id: `${id}-e`, slug: "original", label: "Original", position: 1, year: 2020 }],
    lessons: [{ id: lessonId, editionId: `${id}-e`, slug: lessonId.endsWith("-l") ? "intro" : "next", title: "Intro", position: lessonId.endsWith("-l") ? 1 : 2, youtubeId, durationSeconds: 60 }],
    texts,
  });
  if (!parsed.ok) throw parsed.error;
  return parsed.value;
}

function shipBody(all: readonly CourseBundleV1[], chunk: readonly CourseBundleV1[], options: { draft: boolean; chunkIndex?: number; chunks?: number }) {
  return {
    batchHash: batchContentHash(all),
    chunk: options.chunkIndex ?? 0,
    chunks: options.chunks ?? 1,
    draft: options.draft,
    bundles: chunk,
  };
}

async function rows(h: Harness, sql: string): Promise<number> {
  const { rows: found } = await h.pool.query<{ n: number }>(sql);
  return found[0]?.n ?? 0;
}

describe("bulk ship", () => {
  let h: Harness;
  beforeAll(() => { h = createHarness(); });
  afterAll(async () => { await h.close(); });
  beforeEach(async () => { await seedCatalog(h); });

  it("drafts a course once when the same hash is sent with a new key", async () => {
    const bundle = bundleOf("ship-draft", 1, false);
    const body = shipBody([bundle], [bundle], { draft: true });
    const first = await call<{ courses: string[]; release: null; status: string }>(h, "POST", "/bundles/ship", { key: "ship-draft-1", body });
    expect(first.body.error, JSON.stringify(first.body.error)).toBeUndefined();
    expect(first.status).toBe(201);
    expect(first.data).toMatchObject({ status: "committed", draft: true, courses: ["ship-draft"], release: null });
    const lessons = await rows(h, "SELECT count(*)::int AS n FROM lessons WHERE course_id = 'ship-draft'");
    const second = await call(h, "POST", "/bundles/ship", { key: "ship-draft-2", body });
    expect(second.status).toBe(200);
    expect(second.data).toEqual(first.data);
    expect(await rows(h, "SELECT count(*)::int AS n FROM lessons WHERE course_id = 'ship-draft'")).toBe(lessons);
    expect(await rows(h, "SELECT count(*)::int AS n FROM catalog_releases")).toBe(1);
  });

  it("reports an invalid bundle by id and writes nothing", async () => {
    const before = await rows(h, "SELECT count(*)::int AS n FROM courses");
    const response = await call(h, "POST", "/bundles/ship", {
      key: "ship-bad",
      body: { batchHash: "ab".repeat(32), chunk: 0, chunks: 1, draft: true, bundles: [{ version: 2, course: { id: "ship-bad" } }] },
    });
    expect(response.status).toBe(412);
    expect(response.body.error).toMatchObject({ code: "preconditions_failed" });
    const failed = (response.body.error?.details as { failed?: { entity: string }[] } | undefined)?.failed ?? [];
    expect(failed.some((failure) => failure.entity === "course:ship-bad")).toBe(true);
    expect(await rows(h, "SELECT count(*)::int AS n FROM courses")).toBe(before);
    expect(await rows(h, "SELECT count(*)::int AS n FROM catalog_ship_batches")).toBe(0);
  });

  it("keeps the batch open until every chunk arrives, then commits once", async () => {
    const first = bundleOf("ship-chunk-a", 2, false);
    const second = bundleOf("ship-chunk-b", 3, false);
    const all = [first, second];
    const opened = await call<{ status: string; received: number }>(h, "POST", "/bundles/ship", { key: "ship-chunk-0", body: shipBody(all, [first], { draft: true, chunkIndex: 0, chunks: 2 }) });
    expect(opened.status).toBe(200);
    expect(opened.data).toMatchObject({ status: "partial", received: 1, chunks: 2 });
    expect(await rows(h, "SELECT count(*)::int AS n FROM courses WHERE id LIKE 'ship-chunk-%'")).toBe(0);
    const committed = await call<{ courses: string[] }>(h, "POST", "/bundles/ship", { key: "ship-chunk-1", body: shipBody(all, [second], { draft: true, chunkIndex: 1, chunks: 2 }) });
    expect(committed.status).toBe(201);
    expect(committed.data.courses).toEqual(["ship-chunk-a", "ship-chunk-b"]);
    const replay = await call(h, "POST", "/bundles/ship", { key: "ship-chunk-2", body: shipBody(all, [first], { draft: true, chunkIndex: 0, chunks: 2 }) });
    expect(replay.status).toBe(200);
    expect(replay.data).toEqual(committed.data);
  });

  it("refuses a bulk ship onto a university row with no cover", async () => {
    await h.pool.query("INSERT INTO authors (id, slug, name, monogram, kind) VALUES ('author-ship', 'ship-university', 'Ship University', 'SU', 'institution')");
    await h.pool.query("INSERT INTO home_rows (id, kind, institution_id, title, position, visible, cover) VALUES ('iit-roorkee', 'curated', 'author-ship', 'IIT Roorkee', 50, true, NULL)");
    const revision = (await h.pool.query<{ revision: number }>("SELECT revision FROM catalog_home")).rows[0]?.revision ?? 0;
    const base = bundleOf("ship-iit", 6, false);
    const parsed = validateCourseBundle({ ...base, home: { rowId: "iit-roorkee", expectedRevision: revision } });
    if (!parsed.ok) throw parsed.error;
    const before = await rows(h, "SELECT count(*)::int AS n FROM courses");
    const response = await call(h, "POST", "/bundles/ship", { key: "ship-iit-cover", body: shipBody([parsed.value], [parsed.value], { draft: true }) });
    expect(response.status).toBe(422);
    expect(response.body.error?.code).toBe("unprocessable");
    expect((response.body.error?.details as { errors: string[] }).errors).toEqual(["Curated row iit-roorkee needs a cover."]);
    expect(await rows(h, "SELECT count(*)::int AS n FROM courses")).toBe(before);
    expect(await rows(h, "SELECT count(*)::int AS n FROM home_row_items WHERE row_id = 'iit-roorkee'")).toBe(0);
  });

  it("publishes the batch in one release and a retry does not cut another", async () => {
    await Promise.all(REQUIRED_COVERS.map((kind) => swapMedia(h.pool, "subarea", coverInput("subarea", "programming", kind))));
    const bundles = [bundleOf("ship-live-a", 4, true), bundleOf("ship-live-b", 5, true)];
    const before = await rows(h, "SELECT count(*)::int AS n FROM catalog_releases");
    const body = shipBody(bundles, bundles, { draft: false });
    const first = await call<{ release: { number: number; created: boolean }; courses: string[] }>(h, "POST", "/bundles/ship", { key: "ship-live-1", body });
    expect(first.body.error, JSON.stringify(first.body.error)).toBeUndefined();
    expect(first.status).toBe(201);
    expect(first.data.courses).toEqual(["ship-live-a", "ship-live-b"]);
    expect(first.data.release.created).toBe(true);
    expect(await rows(h, "SELECT count(*)::int AS n FROM catalog_releases")).toBe(before + 1);
    const release = await call<{ release: { payload: { courses: { id: string }[] } } }>(h, "GET", `/releases/${String(first.data.release.number)}`);
    const ids = release.data.release.payload.courses.map((course) => course.id);
    expect(ids).toEqual(expect.arrayContaining(["ship-live-a", "ship-live-b"]));
    const second = await call<{ release: { number: number } }>(h, "POST", "/bundles/ship", { key: "ship-live-2", body });
    expect(second.status).toBe(200);
    expect(second.data.release.number).toBe(first.data.release.number);
    expect(await rows(h, "SELECT count(*)::int AS n FROM catalog_releases")).toBe(before + 1);
  });

  it("ships one YouTube video in two courses and refuses a second lesson of it in the same course", async () => {
    const shared = "sharedvid01";
    const first = bundleOf("ship-share-a", 6, false, { youtubeId: shared, sharedWith: ["ship-share-b"] });
    const second = bundleOf("ship-share-b", 7, false, { youtubeId: shared, sharedWith: ["ship-share-a"] });
    const shipped = await call<{ courses: string[] }>(h, "POST", "/bundles/ship", { key: "ship-share-1", body: shipBody([first, second], [first, second], { draft: true }) });
    expect(shipped.body.error, JSON.stringify(shipped.body.error)).toBeUndefined();
    expect(shipped.status).toBe(201);
    expect(shipped.data.courses).toEqual(["ship-share-a", "ship-share-b"]);
    const videos = await h.pool.query<{ course_id: string; external_id: string }>("SELECT l.course_id, v.external_id FROM lesson_videos v JOIN lessons l ON l.id = v.lesson_id WHERE v.external_id = $1 ORDER BY l.course_id", [shared]);
    expect(videos.rows).toEqual([
      { course_id: "ship-share-a", external_id: shared },
      { course_id: "ship-share-b", external_id: shared },
    ]);
    const again = bundleOf("ship-share-a", 8, false, { lessonId: "ship-share-a-l2", youtubeId: shared });
    const refused = await call(h, "POST", "/bundles/ship", { key: "ship-share-2", body: shipBody([again], [again], { draft: true }) });
    expect(refused.status).toBe(412);
    const failed = (refused.body.error?.details as { failed?: { rule: string; message: string }[] } | undefined)?.failed ?? [];
    expect(failed).toEqual(expect.arrayContaining([expect.objectContaining({ rule: "bundle.video", message: `Video ${shared} belongs to ship-share-a-l.` })]));
    expect(await rows(h, "SELECT count(*)::int AS n FROM lessons WHERE id = 'ship-share-a-l2'")).toBe(0);
  });

  it("D-034: writes two editions of one year when the variant differs and refuses the same variant", async () => {
    const base = bundleOf("ship-variant", 40, false);
    const edition = base.editions[0];
    const lesson = base.lessons[0];
    if (!edition || !lesson) throw new Error("bundle");
    const editions = [
      { ...edition, language: "Italiano", variant: { kind: "language" as const, label: "Italiano" } },
      { id: "ship-variant-en", slug: "english", label: "English", position: 2, year: 2020, language: "English", variant: { kind: "language" as const, label: "English" } },
    ];
    const parsed = validateCourseBundle({ ...base, editions });
    if (!parsed.ok) throw parsed.error;
    const shipped = await call(h, "POST", "/bundles/ship", { key: "ship-variant-1", body: shipBody([parsed.value], [parsed.value], { draft: true }) });
    expect(shipped.body.error, JSON.stringify(shipped.body.error)).toBeUndefined();
    expect(shipped.status).toBe(201);
    const stored = await h.pool.query<{ slug: string; variant_kind: string; variant_label: string; language: string }>("SELECT slug, variant_kind, variant_label, language FROM course_editions WHERE course_id = 'ship-variant' ORDER BY position");
    expect(stored.rows).toEqual([
      { slug: "original", variant_kind: "language", variant_label: "Italiano", language: "Italiano" },
      { slug: "english", variant_kind: "language", variant_label: "English", language: "English" },
    ]);
    const clash = validateCourseBundle({
      ...base, course: { ...base.course, id: "ship-variant", slug: "ship-variant" },
      editions: [{ id: "ship-variant-again", slug: "again", label: "Again", position: 3, year: 2020, language: "Italiano", variant: { kind: "language", label: "Italiano" } }],
      lessons: [{ ...lesson, id: "ship-variant-l2", editionId: "ship-variant-again", slug: "next", position: 1, youtubeId: "variantvid1" }],
    });
    if (!clash.ok) throw clash.error;
    const refused = await call(h, "POST", "/bundles/ship", { key: "ship-variant-2", body: shipBody([clash.value], [clash.value], { draft: true }) });
    expect(refused.status).toBe(412);
    const failed = (refused.body.error?.details as { failed?: { message: string }[] } | undefined)?.failed ?? [];
    expect(failed.map((failure) => failure.message)).toContain("Editions ship-variant-again, ship-variant-e share the year 2020 without a distinct variant.");
    expect(await rows(h, "SELECT count(*)::int AS n FROM course_editions WHERE id = 'ship-variant-again'")).toBe(0);
  });
});
