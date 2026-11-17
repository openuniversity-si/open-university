import { describe, expect, it } from "vitest";
import { releaseFixture } from "../../../test/fixtures/release.ts";
import { snapshotCatalog as catalog } from "../testing/fake.ts";
import { authorOf, courseBySlug, lessonAbout, lessonBySlug, lessonLabel, lessonNeighbors, lessonsForCourse, redirectFor } from "./queries.ts";

function first<T>(items: T[]): T {
  const value = items[0];
  if (value === undefined) throw new Error("Test fixture is empty.");
  return value;
}

describe("queries over the release", () => {
  it("finds courses and lessons while preserving deep links", () => {
    const course = courseBySlug(catalog, "fixture-course-1");
    expect(course?.id).toBe("course-1");
    expect(course && authorOf(catalog, course)?.name).toBe("Fixture Lecturer 1");
    expect(lessonBySlug(catalog, "course-1", "fixture-lesson-4")?.id).toBe("lesson-4");
    expect(courseBySlug(catalog, "unknown")).toBeUndefined();
    expect(lessonBySlug(catalog, "course-2", first(catalog.lessons).slug)).toBeUndefined();
    expect(catalog.courses.map((entry) => lessonsForCourse(catalog, entry.id).length)).toEqual([17, 12, 20, 51, 26]);
  });
  it("never navigates across course boundaries or wraps endpoints", () => {
    expect(lessonNeighbors(catalog, "lesson-1").previous).toBeUndefined();
    expect(lessonNeighbors(catalog, "lesson-17").next).toBeUndefined();
    expect(lessonNeighbors(catalog, "lesson-4").previous?.id).toBe("lesson-3");
    expect(lessonNeighbors(catalog, "lesson-4").next?.id).toBe("lesson-5");
    expect(lessonNeighbors(catalog, "unknown")).toEqual({ previous: undefined, next: undefined });
    expect(catalog.lessons.find((lesson) => lesson.id === "lesson-4")?.youtubeId).toBe("fx000000004");
  });
  it("uses Background 9, Lecture 17 and retained trailers", () => {
    const genesis = first(catalog.courses);
    expect(lessonLabel(genesis, first(catalog.lessons.filter((lesson) => lesson.id === "lesson-9")))).toBe("Background");
    expect(lessonLabel(genesis, first(catalog.lessons.filter((lesson) => lesson.id === "lesson-17")))).toBe("Lecture");
    const course = first(catalog.courses.filter((entry) => entry.id === "course-4"));
    const lessons = lessonsForCourse(catalog, course.id);
    expect(lessonLabel(course, first(lessons))).toBe("Trailer");
    expect(lessonLabel(course, first(lessons.filter((lesson) => lesson.order === 12)))).toBe("Episode");
  });
  it("shows only approved About blocks (the release omits drafts)", () => {
    expect(catalog.lessons.filter((lesson) => lessonAbout(lesson) !== null)).toHaveLength(77);
    expect(catalog.lessons.filter((lesson) => lessonAbout(lesson) === null)).toHaveLength(49);
  });
  it("orders lessons by position whatever the release order", () => {
    const release = releaseFixture();
    const reversed = { ...release, lessons: [...release.lessons].reverse() };
    const courseId = first(release.courses).id;
    expect(lessonsForCourse(reversed, courseId).map((lesson) => lesson.order)).toEqual(lessonsForCourse(release, courseId).map((lesson) => lesson.order));
  });
  it("resolves old paths through the release redirects", () => {
    const release = { ...catalog, redirects: [{ from: "/c/old-genesis", to: "/c/fixture-course-1" }] };
    expect(redirectFor(release, "/c/old-genesis")).toBe("/c/fixture-course-1");
    expect(redirectFor(release, "/c/old-genesis/")).toBe("/c/fixture-course-1");
    expect(redirectFor(release, "/c/other")).toBeUndefined();
    expect(redirectFor(catalog, "/c/old-genesis")).toBeUndefined();
  });
});
