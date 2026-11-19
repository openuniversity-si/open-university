import { describe, expect, it } from "vitest";
import { bundleHash, diffCourseBundle, exportCourseBundle, validateCourseBundle } from "./bundle.ts";

// Verifies: D-034
const author = { id: "author-a", slug: "ann", name: "Ann", monogram: "A", kind: "person" };
const course = { id: "course-live", slug: "contracts", title: "Contracts", authorId: "author-a", coverFrom: "own", sharedWith: [] };
const edition = { id: "edition-1", slug: "original", label: "Original", position: 1, year: 2020 };
const lesson = { id: "lesson-1", editionId: "edition-1", slug: "intro", title: "Intro", position: 1, youtubeId: "abcdefghijk", durationSeconds: 90 };

function bundle(extra: Record<string, unknown> = {}) {
  const parsed = validateCourseBundle({ version: 1, author, course, editions: [edition], lessons: [lesson], ...extra });
  if (!parsed.ok) throw parsed.error;
  return parsed.value;
}

describe("course bundles", () => {
  it("rejects an unknown version and a missing edition before any write", () => {
    expect(validateCourseBundle({ version: 2 }).ok).toBe(false);
    expect(validateCourseBundle({ version: 1, author, course, editions: [edition], lessons: [{ ...lesson, editionId: "missing" }] }).ok).toBe(false);
  });

  it("round-trips validate, export and diff to an empty diff", () => {
    const value = bundle({ texts: [{ entityKind: "lesson", entityId: "lesson-1", field: "displayTitle", text: "Intro", approved: true, approvedBy: "Ann", approvedAt: "2020-01-01T00:00:00.000Z" }] });
    const exported = exportCourseBundle(value);
    expect(exported.lessons[0]?.id).toBe("lesson-1");
    expect(exported.texts[0]?.approvedBy).toBe("Ann");
    expect(diffCourseBundle(exported, value).empty).toBe(true);
    expect(bundleHash(exported)).toBe(bundleHash(value));
  });

  it("treats a missing lesson as omitted, not deleted", () => {
    const full = bundle();
    const subset = validateCourseBundle({ ...full, lessons: [] });
    if (!subset.ok) throw subset.error;
    const diff = diffCourseBundle(full, subset.value);
    expect(diff.lessons.omitted).toEqual(["lesson-1"]);
    expect(diff.lessons.added).toEqual([]);
  });

  it("keeps optional classification and rights, and rejects a subarea without its area", () => {
    const value = bundle({
      course: { ...course, languageLabel: "English", areaId: "law", subareaId: "contracts", licenseCode: "cc-by", sourceId: "src-1", attributionText: "Ann", canonicalUrl: "https://example.org/c", rightsStatus: "cleared" },
      editions: [{ ...edition, language: "English" }],
      covers: [{ kind: "poster_9x16", path: "covers/poster.jpg" }],
    });
    expect(value.course).toMatchObject({ languageLabel: "English", areaId: "law", subareaId: "contracts", licenseCode: "cc-by", sourceId: "src-1", attributionText: "Ann", rightsStatus: "cleared" });
    expect(value.covers).toEqual([{ kind: "poster_9x16", path: "covers/poster.jpg" }]);
    expect(validateCourseBundle({ version: 1, author, course: { ...course, subareaId: "contracts" }, editions: [edition], lessons: [lesson] }).ok).toBe(false);
    expect(validateCourseBundle({ version: 1, author, course, editions: [edition], lessons: [lesson], covers: [{ kind: "poster_9x16", path: "../secret.jpg" }] }).ok).toBe(false);
  });

  it("D-031: coverFrom is required and only the course's own subarea, or its area when it has none", () => {
    const classified = { ...course, areaId: "engineering", subareaId: "textile-engineering", coverFrom: "subarea:textile-engineering" };
    expect(bundle({ course: classified }).course.coverFrom).toBe("subarea:textile-engineering");
    expect(diffCourseBundle(bundle({ course: classified }), bundle({ course: { ...classified, coverFrom: "own", sharedWith: [] } })).course.changed).toEqual(["coverFrom"]);
    const invalid = (extra: Record<string, unknown>) => validateCourseBundle({ version: 1, author, course: { ...course, ...extra }, editions: [edition], lessons: [lesson] });
    expect(invalid({ coverFrom: undefined }).ok).toBe(false);
    expect(invalid({ areaId: "engineering", subareaId: "textile-engineering", coverFrom: "area:engineering" }).ok).toBe(false);
    expect(invalid({ areaId: "engineering", subareaId: null, coverFrom: "area:engineering" }).ok).toBe(true);
    expect(invalid({ coverFrom: "institution:usp" }).ok).toBe(false);
  });

  it("D-034: a bundle refuses two editions of one year without a distinct variant", () => {
    const other = { id: "edition-2", slug: "other", label: "Other", position: 2, year: 2020 };
    const parsed = (editions: unknown[]) => validateCourseBundle({ version: 1, author, course, editions, lessons: [lesson] });
    const refused = parsed([edition, other]);
    expect(refused.ok).toBe(false);
    if (!refused.ok) expect(refused.error.message).toBe("Editions edition-1, edition-2 share the year 2020 without a distinct variant.");
    expect(parsed([edition, { ...other, year: 2021 }]).ok).toBe(true);
    expect(parsed([
      { ...edition, language: "English", variant: { kind: "language", label: "English" } },
      { ...other, language: "Italiano", variant: { kind: "language", label: "Italiano" } },
    ]).ok).toBe(true);
    expect(parsed([
      { ...edition, variant: { kind: "term", label: "SS" } },
      { ...other, variant: { kind: "term", label: "WS" } },
    ]).ok).toBe(true);
    expect(parsed([
      { ...edition, variant: { kind: "group", label: "presencial" } },
      { ...other, variant: { kind: "group", label: "semipresencial" } },
    ]).ok).toBe(true);
    expect(parsed([
      { ...edition, language: "Italiano", variant: { kind: "language", label: "Italiano" } },
      { ...other, language: "Italiano", variant: { kind: "language", label: "Italiano" } },
    ]).ok).toBe(false);
    expect(parsed([{ ...edition, variant: { kind: "season", label: "fall" } }]).ok).toBe(false);
    expect(parsed([{ ...edition, variant: { kind: "language" } }]).ok).toBe(false);
  });

  it("D-032: a share is a list of other courses, each named once", () => {
    const invalid = (sharedWith: string[]) => validateCourseBundle({ version: 1, author, course: { ...course, sharedWith }, editions: [edition], lessons: [lesson] });
    expect(invalid([]).ok).toBe(true);
    expect(invalid(["course-live"]).ok).toBe(false);
    expect(invalid(["course-other", "course-other"]).ok).toBe(false);
    expect(bundle({ course: { ...course, sharedWith: ["course-other"] } }).course.sharedWith).toEqual(["course-other"]);
  });

});
