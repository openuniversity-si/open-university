import { describe, expect, it } from "vitest";
import { planBatch, type BatchRefs } from "./batch-plan.ts";
import { catalogBatchV2Schema, type CatalogBatchV2 } from "./schema/batch-v2.ts";

// Verifies: D-031
// S07: the pure planner of CatalogBatchV2 over in-memory refs (no database, no network).

const sha = (seed: string) => seed.repeat(64).slice(0, 64);
const SHAS = ["a", "b", "c", "d", "e", "f", "0", "1"].map(sha);
const rowCover = (value: string) => ({ sha: value, alt: "USP", credit: "Photo: USP", sourceUrl: "https://usp.br", license: "CC BY 4.0" });

function batch(patch: Record<string, unknown> = {}, course: Record<string, unknown> = {}): CatalogBatchV2 {
  return catalogBatchV2Schema.parse({
    version: 2,
    sources: [{ id: "yt-usp", kind: "youtube-channel", title: "USP", url: "https://www.youtube.com/@usp" }],
    institutions: [{ id: "usp", slug: "usp", name: "USP", monogram: "USP", kind: "institution", cover: { poster: SHAS[0], og: SHAS[1] } }],
    lecturers: [{ id: "ana-lima", slug: "ana-lima", name: "Ana Lima", monogram: "AL", kind: "person" }],
    homeRows: [{ id: "usp", institutionId: "usp", title: "USP", fullName: "Universidade de São Paulo", place: "São Paulo, Brazil", after: "mit", cover: rowCover(SHAS[2] ?? "") }],
    courses: [{
      institutionId: "usp", homeRowId: "usp",
      course: { id: "usp-mecanica", slug: "mecanica-geral", title: "Mecânica Geral", authorId: "ana-lima", areaId: "physics", sourceId: "yt-usp", licenseCode: "youtube-standard", coverFrom: "own", sharedWith: [], ...course },
      editions: [{ id: "usp-mecanica-2021", slug: "2021", label: "2021", position: 1, year: 2021 }],
      lessons: [{ id: "usp-mecanica-1", editionId: "usp-mecanica-2021", slug: "aula-1", title: "Aula 1", position: 1, youtubeId: "abcdefghijk", durationSeconds: 60 }],
      covers: [{ kind: "poster_9x16", sha: SHAS[3] }, { kind: "hero_desktop_16x9", sha: SHAS[4] }, { kind: "hero_present", sha: SHAS[5] }, { kind: "hero_mobile_9x16", sha: SHAS[6] }],
    }],
    ...patch,
  });
}

const empty: BatchRefs = {
  sources: new Map(), authors: new Map(), areas: new Map([["physics", { title: "Physics" }]]), subareas: new Map(),
  homeRows: new Map([["mit", { institutionId: "mit", title: "MIT" }]]), courses: new Map(), licenses: new Set(["youtube-standard"]), covers: new Map(), media: new Set(SHAS),
};
const refs = (patch: Partial<BatchRefs>): BatchRefs => ({ ...empty, ...patch });

describe("planBatch (CatalogBatchV2, S07)", () => {
  it("G-4: plans a new institution, its row and a course with own covers in one order", () => {
    const plan = planBatch(batch(), empty);
    expect(plan.failures).toEqual([]);
    expect(plan.ops.map((op) => `${op.step} ${op.action} ${op.id}`)).toEqual([
      "source create yt-usp",
      "institution create usp",
      "lecturer create ana-lima",
      "home-row create usp",
      `media attach institution:usp:poster_9x16@${SHAS[0]?.slice(0, 12) ?? ""}`,
      `media attach institution:usp:og@${SHAS[1]?.slice(0, 12) ?? ""}`,
      `media attach home_row:usp:university_cover_9x16@${SHAS[2]?.slice(0, 12) ?? ""}`,
      `media attach course:usp-mecanica:poster_9x16@${SHAS[3]?.slice(0, 12) ?? ""}`,
      `media attach course:usp-mecanica:hero_desktop_16x9@${SHAS[4]?.slice(0, 12) ?? ""}`,
      `media attach course:usp-mecanica:hero_present@${SHAS[5]?.slice(0, 12) ?? ""}`,
      `media attach course:usp-mecanica:hero_mobile_9x16@${SHAS[6]?.slice(0, 12) ?? ""}`,
      "course create usp-mecanica",
      "placement attach usp/usp-mecanica",
      "release create release",
    ]);
  });

  it("an existing reference with the same content is a no-op; different content is a conflict unless updateRefs", () => {
    const stored = refs({
      sources: new Map([["yt-usp", { id: "yt-usp", kind: "youtube-channel", title: "USP", url: "https://www.youtube.com/@usp" }]]),
      authors: new Map([["usp", { slug: "usp", name: "USP", monogram: "USP", kind: "institution" }], ["ana-lima", { slug: "ana-lima", name: "Ana Lima", monogram: "AL", kind: "person" }]]),
      homeRows: new Map([["mit", { institutionId: "mit", title: "MIT" }], ["usp", { institutionId: "usp", title: "USP" }]]),
      courses: new Map([["usp-mecanica", { slug: "mecanica-geral", institutionId: "usp" }]]),
    });
    const same = planBatch(batch(), stored);
    expect(same.failures).toEqual([]);
    expect(same.ops.filter((op) => op.action === "noop").map((op) => `${op.step}:${op.id}`)).toEqual(["source:yt-usp", "institution:usp", "lecturer:ana-lima", "home-row:usp"]);
    expect(same.ops.find((op) => op.step === "course")).toEqual({ step: "course", action: "update", id: "usp-mecanica" });

    const renamed = refs({ ...stored, authors: new Map([...stored.authors, ["usp", { slug: "usp", name: "Universidade de São Paulo", monogram: "USP", kind: "institution" }]]) });
    expect(planBatch(batch(), renamed).failures).toEqual([{ rule: "batch.ref-conflict", entity: "institution:usp", message: "Stored institution usp differs from the batch; set updateRefs to overwrite it." }]);
    const updated = planBatch(batch({ updateRefs: true }), renamed);
    expect(updated.failures).toEqual([]);
    expect(updated.ops.find((op) => op.step === "institution")).toEqual({ step: "institution", action: "update", id: "usp" });
  });

  it("G-5: lists every failure by rule and entity, not the first", () => {
    const broken = batch({
      lecturers: [{ id: "ana-lima", slug: "ana-lima", name: "Ana Lima", monogram: "AL", kind: "person" }, { id: "ana-lima", slug: "ana-2", name: "Ana", monogram: "A", kind: "person" }],
      homeRows: [{ id: "usp", institutionId: "ana-lima", title: "USP", cover: rowCover(sha("9")) }],
    }, { areaId: "chemistry", licenseCode: "cc-by", subareaId: "optics" });
    broken.courses[0]?.editions.push({ id: "usp-mecanica-old", slug: "old", label: "Old", position: 2, year: null });
    const plan = planBatch(broken, refs({ courses: new Map([["other", { slug: "mecanica-geral", institutionId: "mit" }]]) }));
    expect(plan.failures.map((failure) => `${failure.rule} ${failure.entity}`)).toEqual([
      "batch.duplicate institution:ana-lima",
      "batch.institution-kind home_row:usp",
      "batch.cover home_row:usp:university_cover_9x16",
      "batch.course course:usp-mecanica",
      "batch.reference course:usp-mecanica",
      "batch.reference course:usp-mecanica",
      "batch.reference course:usp-mecanica",
      "batch.duplicate course:usp-mecanica",
      "batch.home-row course:usp-mecanica",
    ]);
    expect(plan.failures.map((failure) => failure.message)).toContain("Row usp belongs to ana-lima.");
  });

  it("D-024: a lecturer cannot offer a course, and an institution keeps its one row", () => {
    const plan = planBatch(batch({}, {}), refs({ homeRows: new Map([...empty.homeRows, ["usp-old", { institutionId: "usp", title: "USP" }]]) }));
    expect(plan.failures).toEqual([{ rule: "batch.home-row", entity: "home_row:usp", message: "Institution usp already has row usp-old." }]);
    const lecturerOffers = catalogBatchV2Schema.parse({ ...batch(), courses: batch().courses.map((item) => ({ ...item, institutionId: "ana-lima", homeRowId: null })) });
    expect(planBatch(lecturerOffers, empty).failures.map((failure) => failure.rule)).toEqual(["batch.institution-kind"]);
  });

  it("D-031: rejects a coverFrom that is not the course's subarea or an owner without a required kind", () => {
    const wrong = planBatch(batch({}, { subareaId: "mechanics", coverFrom: "area:physics" }), refs({
      subareas: new Map([["mechanics", { areaId: "physics", title: "Mechanics" }]]),
    }));
    expect(wrong.failures).toEqual(expect.arrayContaining([expect.objectContaining({ rule: "cover.declared", entity: "course:usp-mecanica" })]));
    const thin = batch();
    const course = thin.courses[0];
    if (!course) throw new Error("missing course");
    course.covers = [{ kind: "poster_9x16", sha: SHAS[3] ?? "" }];
    const missing = planBatch(thin, empty);
    expect(missing.failures.map((failure) => failure.rule)).toEqual(["cover.declared"]);
    expect(missing.failures[0]?.message).toMatch(/lacks hero_desktop_16x9/);
  });

  it("D-031: a new area, its four covers, a license and a course that declares the area plan in one pass", () => {
    const cover = { poster: SHAS[3] ?? "", heroDesktop: SHAS[4] ?? "", heroPresent: SHAS[5] ?? "", heroMobile: SHAS[6] ?? "" };
    const planned = catalogBatchV2Schema.parse({
      version: 2,
      licenses: [{ code: "cc-by", name: "CC BY", url: "https://creativecommons.org/licenses/by/4.0/", requiresAttribution: true, embedOnly: false }],
      areas: [{ id: "law", title: "Law", cover }],
      institutions: [{ id: "usp", slug: "usp", name: "USP", monogram: "USP", kind: "institution", cover: { poster: SHAS[0], og: SHAS[1] } }],
      lecturers: [{ id: "ana-lima", slug: "ana-lima", name: "Ana Lima", monogram: "AL", kind: "person" }],
      courses: [{
        institutionId: "usp",
        course: { id: "usp-law", slug: "intro-law", title: "Intro Law", authorId: "ana-lima", areaId: "law", subareaId: null, coverFrom: "area:law", licenseCode: "cc-by", sharedWith: [] },
        editions: [{ id: "usp-law-2021", slug: "2021", label: "2021", position: 1, year: 2021 }],
        covers: [],
      }],
    });
    const plan = planBatch(planned, refs({ areas: new Map(), licenses: new Set() }));
    expect(plan.failures).toEqual([]);
    expect(plan.ops).toEqual(expect.arrayContaining([
      { step: "license", action: "create", id: "cc-by" },
      { step: "area", action: "create", id: "law" },
      { step: "course", action: "create", id: "usp-law" },
    ]));
  });
});
