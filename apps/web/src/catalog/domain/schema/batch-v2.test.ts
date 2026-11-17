import { describe, expect, it } from "vitest";
import { catalogBatchV2Schema } from "./batch-v2.ts";

const sha = "a".repeat(64);
const sample = (patch: Record<string, unknown> = {}, course: Record<string, unknown> = {}) => ({
  version: 2,
  institutions: [{ id: "usp", slug: "usp", name: "USP", monogram: "USP", kind: "institution", cover: { poster: sha } }],
  lecturers: [{ id: "ana-lima", slug: "ana-lima", name: "Ana Lima", monogram: "AL", kind: "person" }],
  courses: [{
    institutionId: "usp",
    course: { id: "usp-mecanica", slug: "mecanica-geral", title: "Mecânica Geral", authorId: "ana-lima", coverFrom: "own", sharedWith: [], ...course },
    editions: [{ id: "usp-mecanica-2021", slug: "2021", label: "2021", position: 1, year: 2021 }],
    covers: [{ kind: "poster_9x16", sha }],
  }],
  ...patch,
});

describe("CatalogBatchV2 schema (S07, CONTRACT §5)", () => {
  it("INV-R1: takes the API's limits (a 65-character id fails, 64 passes) and keeps an explicit null year", () => {
    expect(catalogBatchV2Schema.safeParse(sample({}, { id: "x".repeat(65) })).success).toBe(false);
    const parsed = catalogBatchV2Schema.parse(sample({}, { id: "x".repeat(64) }));
    expect(parsed.courses[0]?.course.id).toHaveLength(64);
    expect(catalogBatchV2Schema.parse(sample()).courses[0]?.editions[0]?.year).toBe(2021);
    const unknown = catalogBatchV2Schema.parse({ ...sample(), courses: [{ ...sample().courses[0], editions: [{ id: "usp-mecanica-2021", slug: "2021", label: "2021", position: 1, year: null }] }] });
    expect(unknown.courses[0]?.editions[0]?.year).toBeNull();
    expect(parsed).toMatchObject({ updateRefs: false, sources: [], areas: [], subareas: [], homeRows: [] });
  });

  it("D-024: an institution has kind institution and a lecturer never does", () => {
    expect(catalogBatchV2Schema.safeParse(sample({ institutions: [{ id: "x", slug: "x", name: "X", monogram: "X", kind: "person", cover: { poster: sha } }] })).error?.issues[0]?.message)
      .toBe("An institution has kind institution; a lecturer is a course author (D-024).");
    expect(catalogBatchV2Schema.safeParse(sample({ lecturers: [{ id: "x", slug: "x", name: "X", monogram: "X", kind: "institution" }] })).success).toBe(false);
  });

  it("covers travel by content address only, and a batch has at least one course", () => {
    expect(catalogBatchV2Schema.safeParse(sample({}, {})).success).toBe(true);
    expect(catalogBatchV2Schema.safeParse({ ...sample(), courses: [{ ...sample().courses[0], covers: [{ kind: "poster_9x16", path: "poster.jpg" }] }] }).success).toBe(false);
    expect(catalogBatchV2Schema.safeParse({ ...sample(), courses: [] }).success).toBe(false);
  });
});
