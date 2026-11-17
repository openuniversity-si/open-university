import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { SlugFixture } from "../testing/slug-fixture.ts";
import type { CatalogTables } from "./tables.ts";
import { LEGACY_LESSON_IDS, reslugCourse, slugCourseFromTables, slugCoursesFromTables, slugQualityIssues, type SlugCourse } from "./slug-course.ts";

const fixture = JSON.parse(readFileSync(new URL("../testing/slug.fixtures.json", import.meta.url), "utf8")) as SlugFixture;

/** The fixture's courses as SlugCourse (edition ids are their labels). */
function fixtureCourses(): SlugCourse[] {
  return Object.entries(fixture.courses).map(([slug, course]) => {
    const rows = fixture.lessons.filter((row) => row.courseSlug === slug);
    const editions = [...new Map(rows.map((row) => [row.edition.label, { id: row.edition.label, ...row.edition }])).values()];
    return {
      slug, title: course.title, institution: course.institution, editions,
      lessons: rows.map((row) => ({ id: row.lessonId, editionId: row.edition.label, position: row.position, kind: row.kind, youtubeTitle: row.youtubeTitle, displayTitle: row.displayTitle, slug: row.currentSlug })),
    };
  });
}

describe("reslugCourse", () => {
  it("gives every one of the 386 imported lessons its reviewed expectedSlug", () => {
    const expected = new Map(fixture.lessons.map((row) => [row.lessonId, row.expectedSlug]));
    const results = fixtureCourses().flatMap((course) => reslugCourse(course));
    expect(results).toHaveLength(386);
    for (const result of results) expect(result.after, result.lessonId).toBe(expected.get(result.lessonId));
    expect(results.filter((result) => result.reason === "kept")).toEqual([]);
  });

  it("is idempotent: a course already on the rule keeps every slug", () => {
    for (const course of fixtureCourses()) {
      const once = reslugCourse(course);
      const again = reslugCourse({ ...course, lessons: course.lessons.map((lesson, index) => ({ ...lesson, slug: once[index]?.after ?? "" })) });
      expect(again.every((result) => result.reason === "kept"), course.slug).toBe(true);
    }
  });

  it("never touches legacy or excluded lessons, and keeps their slugs out of the others' way", () => {
    const course: SlugCourse = {
      slug: "mixed", title: "Mixed", institution: null, editions: [{ id: "e", label: "Fall 2024", term: "fall", year: 2024 }],
      lessons: [
        { id: "lesson-1", editionId: "e", position: 1, kind: "lecture", youtubeTitle: "Lecture 1: Intro", displayTitle: null, slug: "lecture-01-intro" },
        { id: "lesson-900", editionId: "e", position: 2, kind: "lecture", youtubeTitle: "Lecture 1: Intro", displayTitle: null, slug: "x" },
        { id: "lesson-901", editionId: "e", position: 3, kind: "lecture", youtubeTitle: "Lecture 2 - Mixed (Fall 2024)", displayTitle: null, slug: "keep-me" },
      ],
    };
    expect(reslugCourse(course, new Set(["lesson-901"]))).toEqual([
      { lessonId: "lesson-1", before: "lecture-01-intro", after: "lecture-01-intro", reason: "legacy" },
      { lessonId: "lesson-900", before: "x", after: "lecture-01-intro-2", reason: "rule, disambiguated" },
      { lessonId: "lesson-901", before: "keep-me", after: "keep-me", reason: "excluded" },
    ]);
  });

  it("names the 126 legacy lessons by a fixed list, the fixture's", () => {
    expect([...LEGACY_LESSON_IDS]).toEqual(fixture.legacyLessonIds);
    expect(LEGACY_LESSON_IDS.size).toBe(126);
  });
});

describe("slugQualityIssues", () => {
  it("flags long slugs, edition tags, the course name and anything the rule would not give", () => {
    expect(slugQualityIssues("lecture-01-intro", "lecture-01-intro", "cmu-db")).toEqual([]);
    expect(slugQualityIssues("fa24-intro-to-android-bonus-lecture-2", "bonus-lecture-02", "android")).toEqual(["edition tag", "course name", "rule gives bonus-lecture-02"]);
    expect(slugQualityIssues("a".repeat(61), "a", "x")).toEqual(["longer than 60", "rule gives a"]);
    expect(slugQualityIssues("intro-spring-2025", "intro-spring-2025", "")).toEqual(["edition tag"]);
  });
});

describe("slugCourseFromTables", () => {
  const lesson = (id: string, edition: string, position: number, title: string) => ({ id, course_id: "course-30", edition_id: edition, part: "lectures", slug: `old-${id}`, position, kind: "lecture", youtube_title: title });
  const tables = (authorKind: string) => ({
    authors: [{ id: "author-30", name: "Cornell AppDev", kind: authorKind }],
    courses: [{ id: "course-30", slug: "android", title: "Android Course", author_id: "author-30" }],
    course_editions: [{ id: "e-old", course_id: "course-30", label: "Fall 2024", term: "fall", year: 2024, position: 2 }, { id: "e-new", course_id: "course-30", label: "Spring 2025", term: "spring", year: 2025, position: 1 }],
    lessons: [lesson("lesson-401", "e-old", 1, "Old 1"), lesson("lesson-402", "e-new", 2, "New 2"), lesson("lesson-403", "e-new", 1, "New 1")],
    catalog_texts: [
      { entity_kind: "lesson", entity_id: "lesson-403", field: "displayTitle", status: "approved", text: "Approved One" },
      { entity_kind: "lesson", entity_id: "lesson-402", field: "displayTitle", status: "draft", text: "Draft Two" },
    ],
  }) as unknown as CatalogTables;

  it("orders lessons by edition then position, takes only approved display titles and the non-person author as institution", () => {
    const course = slugCourseFromTables(tables("channel"), "course-30");
    expect(course?.institution).toBe("Cornell AppDev");
    expect(course?.editions.map((edition) => edition.id)).toEqual(["e-new", "e-old"]);
    expect(course?.lessons.map((entry) => [entry.id, entry.displayTitle])).toEqual([["lesson-403", "Approved One"], ["lesson-402", null], ["lesson-401", null]]);
    expect(slugCourseFromTables(tables("person"), "course-30")?.institution).toBeNull();
    expect(slugCourseFromTables(tables("person"), "course-404")).toBeNull();
    expect(slugCoursesFromTables(tables("channel")).get("course-30")).toEqual(course);
  });

  it("reads a course with no editions and a lesson whose edition is not on the course", () => {
    const bare = {
      authors: [],
      courses: [
        { id: "course-empty", slug: "empty", title: "Empty", author_id: "missing" },
        { id: "course-odd", slug: "odd", title: "Odd", author_id: "missing" },
      ],
      course_editions: [{ id: "e-1", course_id: "course-odd", label: "2024", term: null, year: 2024, position: 1 }],
      lessons: [
        { id: "lesson-9", course_id: "course-odd", edition_id: "gone", part: "lectures", slug: "old", position: 2, kind: "lecture", youtube_title: "Orphan" },
        { id: "lesson-8", course_id: "course-odd", edition_id: "e-1", part: "lectures", slug: "kept", position: 1, kind: "lecture", youtube_title: "Kept" },
      ],
      catalog_texts: [],
    } as unknown as CatalogTables;
    expect(slugCourseFromTables(bare, "course-empty")).toMatchObject({ editions: [], lessons: [] });
    const odd = slugCourseFromTables(bare, "course-odd");
    expect(odd?.lessons.map((entry) => entry.id)).toEqual(["lesson-8", "lesson-9"]);
    expect(reslugCourse(odd ?? { slug: "odd", title: "Odd", institution: null, editions: [], lessons: [] })[0]?.after).toBeTruthy();
  });
});
