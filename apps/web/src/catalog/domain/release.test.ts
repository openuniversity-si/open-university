import { describe, expect, it } from "vitest";
import { releaseFixture } from "../../../test/fixtures/release.ts";
import { releaseSchema, type PublicCatalog } from "./release.ts";

function nth<T>(items: T[], index: number): T {
  const item = items[index];
  if (item === undefined) throw new Error(`Fixture has no item ${String(index)}.`);
  return item;
}

function issues(mutate: (release: PublicCatalog) => void): string[] {
  const release = releaseFixture();
  mutate(release);
  const result = releaseSchema.safeParse(release);
  return result.success ? [] : result.error.issues.map((issue) => issue.message);
}

describe("releaseSchema", () => {
  it("accepts a two-course release without fixed counts", () => {
    expect(releaseSchema.parse(releaseFixture()).courses).toHaveLength(2);
  });

  it.each<[string, (release: PublicCatalog) => void, string]>([
    ["a duplicate lesson ID", (r) => { nth(r.lessons, 2).id = "lesson-1"; }, "Duplicate lesson ID"],
    ["a duplicate course slug", (r) => { nth(r.courses, 1).slug = "first-course"; }, "Duplicate course slug"],
    ["a duplicate YouTube ID in one course", (r) => { nth(r.lessons, 1).youtubeId = "AAAAAAAAAA1"; }, "Duplicate YouTube ID"],
    ["a non-contiguous order", (r) => { nth(r.lessons, 1).order = 3; }, "Non-contiguous order in edition course-1-e1"],
    ["a course without lessons", (r) => { r.lessons.pop(); }, "Course course-2 has no lessons"],
    ["an unknown author", (r) => { nth(r.courses, 1).authorId = "author-9"; }, "Unknown author for course-2"],
    ["two featured courses", (r) => { nth(r.courses, 1).featured = true; }, "More than one featured course"],
    ["an unpublished featured course", (r) => { nth(r.courses, 0).featured = false; r.home.featuredCourseId = "course-9"; }, "Featured course course-9 is not published"],
    ["an unknown course in a row", (r) => { nth(r.home.rows, 1).courseIds.push("course-9"); }, "Unknown course course-9"],
    ["courses in the continue row", (r) => { nth(r.home.rows, 0).courseIds.push("course-1"); }, "derived from progress"],
    ["a redirect to a missing page", (r) => { nth(r.redirects, 0).to = "/c/nowhere"; }, "points to a missing page"],
    ["a redirect cycle", (r) => { r.redirects.push({ from: "/c/first-course", to: "/c/old-first-course" }); }, "shadows a live page"],
  ])("rejects %s", (_label, mutate, message) => {
    expect(issues(mutate).join("\n")).toContain(message);
  });

  it("allows the same YouTube video as a lesson of two courses", () => {
    expect(issues((r) => { nth(r.lessons, 2).youtubeId = "AAAAAAAAAA1"; })).toEqual([]);
    const across = releaseFixture();
    nth(across.lessons, 2).youtubeId = "AAAAAAAAAA1";
    const lessons = releaseSchema.parse(across).lessons.filter((lesson) => lesson.youtubeId === "AAAAAAAAAA1");
    expect(lessons.map((lesson) => [lesson.courseId, lesson.slug, lesson.id])).toEqual([
      ["course-1", "intro", "lesson-1"],
      ["course-2", "intro", "lesson-3"],
    ]);
  });

  it("rejects another schema version and an invalid slug", () => {
    expect(issues((r) => { (r as { schemaVersion: number }).schemaVersion = 3; })).not.toEqual([]);
    expect(issues((r) => { nth(r.courses, 0).slug = "Bad Slug"; })).not.toEqual([]);
  });
});
