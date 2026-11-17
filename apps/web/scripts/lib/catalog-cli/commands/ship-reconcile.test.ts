import { describe, expect, it } from "vitest";
import { validateCourseBundle } from "../../../../src/catalog/domain/bundle.ts";
import { releaseShowsBundle } from "./ship-reconcile.ts";

function bundleOf(extra: { course?: Record<string, unknown>; texts?: unknown[]; editions?: unknown[] } = {}) {
  const parsed = validateCourseBundle({
    version: 1,
    author: { id: "author-a", slug: "ann", name: "Ann", monogram: "A", kind: "person" },
    course: { id: "course-a", slug: "course-a", title: "Contracts", authorId: "author-a", areaId: "engineering", subareaId: "textile-engineering", coverFrom: "subarea:textile-engineering", sharedWith: [], ...extra.course },
    editions: extra.editions ?? [{ id: "edition-1", slug: "original", label: "Original", position: 1, year: 2020 }],
    lessons: [{ id: "lesson-1", editionId: "edition-1", slug: "intro", title: "Intro", position: 1, youtubeId: "abcdefghijk", durationSeconds: 90 }],
    texts: extra.texts ?? [
      { entityKind: "course", entityId: "course-a", field: "displayTitle", text: "Contracts", approved: true, approvedBy: "ai-review", approvedAt: "2026-10-17T00:00:00Z" },
      { entityKind: "lesson", entityId: "lesson-1", field: "displayTitle", text: "Intro", approved: true, approvedBy: "ai-review", approvedAt: "2026-10-17T00:00:00Z" },
      { entityKind: "course", entityId: "course-a", field: "description", text: "Draft copy", approved: false, approvedBy: null, approvedAt: null },
    ],
  });
  if (!parsed.ok) throw parsed.error;
  return parsed.value;
}

const release = (course: Record<string, unknown> = {}, lesson: Record<string, unknown> = {}) => ({
  courses: [{
    id: "course-a", slug: "course-a", title: "Contracts", authorId: "author-a", lessonNoun: "Lecture", areaId: "engineering", subareaId: "textile-engineering",
    coverFrom: "subarea:textile-engineering", displayTitle: "Contracts", description: "Published copy", rights: {},
    editions: [{ id: "edition-1", slug: "original", label: "Original", year: 2020, position: 1 }], ...course,
  }],
  lessons: [{ id: "lesson-1", courseId: "course-a", slug: "intro", youtubeId: "abcdefghijk", durationSeconds: 90, editionId: "edition-1", part: "lectures", displayTitle: "Intro", ...lesson }],
});

describe("releaseShowsBundle", () => {
  it("accepts the release that shows the bundle and ignores draft texts, which are never published", () => {
    expect(releaseShowsBundle(release(), bundleOf())).toBe(true);
  });

  it("refuses any difference the bundle controls", () => {
    expect(releaseShowsBundle({ courses: [], lessons: [] }, bundleOf())).toBe(false);
    expect(releaseShowsBundle(release({ title: "Other" }), bundleOf())).toBe(false);
    expect(releaseShowsBundle(release({ displayTitle: "Old title" }), bundleOf())).toBe(false);
    expect(releaseShowsBundle(release({ coverFrom: "own" }), bundleOf())).toBe(false);
    expect(releaseShowsBundle(release({ subareaId: undefined }), bundleOf())).toBe(false);
    expect(releaseShowsBundle(release({}, { youtubeId: "zzzzzzzzzzz" }), bundleOf())).toBe(false);
    expect(releaseShowsBundle(release({}, { displayTitle: "Lecture 1" }), bundleOf())).toBe(false);
    expect(releaseShowsBundle(release({ editions: [] }), bundleOf())).toBe(false);
    expect(releaseShowsBundle({ courses: release().courses, lessons: [] }, bundleOf())).toBe(false);
  });

  it("D-034: a variant-only difference is not the release that shows the bundle", () => {
    const variant = { kind: "language" as const, label: "Italiano" };
    const edition = { id: "edition-1", slug: "original", label: "Original", position: 1, year: 2020, language: "Italiano", variant };
    const bundle = bundleOf({ editions: [edition] });
    expect(releaseShowsBundle(release(), bundle)).toBe(false);
    expect(releaseShowsBundle(release({ editions: [edition] }), bundle)).toBe(true);
    expect(releaseShowsBundle(release({ editions: [{ ...edition, variant: { kind: "language", label: "English" } }] }), bundle)).toBe(false);
  });

  it("reads a course without a subarea as subareaId null", () => {
    const value = bundleOf({ course: { subareaId: null, coverFrom: "own" } });
    expect(releaseShowsBundle(release({ subareaId: undefined, coverFrom: "own" }), value)).toBe(true);
  });
});
