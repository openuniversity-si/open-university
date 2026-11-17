import { describe, expect, it } from "vitest";
import { preconditionsFailed } from "../../kernel/errors.ts";
import { planBatch, type BatchRefs } from "./batch-plan.ts";
import { batchAreaSchema, batchSubareaSchema, catalogBatchV2Schema, type CatalogBatchV2 } from "./schema/batch-v2.ts";

// D-035: the batch schema and the plan use the same cover list as the kernel. A subarea still is 412.

const sha = "ab".repeat(32);
const cover = { poster: sha, heroDesktop: sha, heroPresent: sha, heroMobile: sha, og: sha, lessonDefault: sha, still: sha };

function batch(patch: Record<string, unknown>): CatalogBatchV2 {
  return catalogBatchV2Schema.parse({
    version: 2,
    sources: [{ id: "yt-usp", kind: "youtube-channel", title: "USP", url: "https://www.youtube.com/@usp" }],
    institutions: [{ id: "usp", slug: "usp", name: "USP", monogram: "USP", kind: "institution", cover: { poster: sha, og: sha } }],
    lecturers: [{ id: "ana-lima", slug: "ana-lima", name: "Ana Lima", monogram: "AL", kind: "person" }],
    homeRows: [{ id: "usp", institutionId: "usp", title: "USP", after: "mit", cover: { sha, alt: "USP", credit: "Photo: USP", sourceUrl: "https://usp.br", license: "CC BY 4.0" } }],
    courses: [{
      institutionId: "usp", homeRowId: "usp",
      course: { id: "usp-mecanica", slug: "mecanica-geral", title: "Mecânica Geral", authorId: "ana-lima", areaId: "physics", sourceId: "yt-usp", licenseCode: "youtube-standard", coverFrom: "own", sharedWith: [] },
      editions: [{ id: "usp-mecanica-2021", slug: "2021", label: "2021", position: 1, year: 2021 }],
      lessons: [{ id: "usp-mecanica-1", editionId: "usp-mecanica-2021", slug: "aula-1", title: "Aula 1", position: 1, youtubeId: "abcdefghijk", durationSeconds: 60 }],
      covers: [{ kind: "poster_9x16", sha }, { kind: "hero_desktop_16x9", sha }, { kind: "hero_present", sha }, { kind: "hero_mobile_9x16", sha }],
    }],
    ...patch,
  });
}

const refs: BatchRefs = {
  sources: new Map(), authors: new Map(), areas: new Map([["physics", { title: "Physics" }]]), subareas: new Map(),
  homeRows: new Map([["mit", { institutionId: "mit", title: "MIT" }]]), courses: new Map(), licenses: new Set(["youtube-standard"]), covers: new Map(), media: new Set([sha]),
};

describe("cover kinds in the batch (D-035)", () => {
  it("accepts an area still and rejects a subarea still with 412", () => {
    expect(batchAreaSchema.parse({ id: "physics", title: "Physics", cover }).cover?.still).toBe(sha);
    expect(() => batchSubareaSchema.parse({ id: "mechanics", areaId: "physics", title: "Mechanics", cover })).toThrow();

    const area = batch({ areas: [{ id: "physics", title: "Physics", cover }] });
    const planned = planBatch(area, refs);
    expect(planned.failures).toEqual([]);
    expect(planned.ops.some((op) => op.id.startsWith("area:physics:still_16x9@"))).toBe(true);

    const sub = batch({ subareas: [{ id: "mechanics", areaId: "physics", title: "Mechanics", cover: { poster: sha, heroDesktop: sha, heroPresent: sha, heroMobile: sha } }] });
    const node = sub.subareas[0];
    if (!node?.cover) throw new Error("expected a subarea cover");
    const poisoned = { ...sub, subareas: [{ ...node, cover: { ...node.cover, still: sha } }] } as CatalogBatchV2;
    const rejected = planBatch(poisoned, refs);
    expect(rejected.failures).toContainEqual({ rule: "batch.cover-kind", entity: "subarea:mechanics:still_16x9", message: "subarea does not accept cover kind still_16x9." });
    expect(preconditionsFailed(rejected.failures).status).toBe(412);
  });
});
