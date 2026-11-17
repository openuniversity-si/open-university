import { describe, expect, it } from "vitest";
import { mediaInvalidation, subareaInvalidation } from "./tags.ts";

it("expires a shared descriptor and only published courses, adding lists for shared list art", () => {
  const courses = [{ courseId: "course-1", published: true }, { courseId: "course-2", published: false }];
  expect(subareaInvalidation("algorithms", courses, "lesson_default")).toEqual({ tags: ["media:subarea:algorithms", "media:course:course-1"], paths: [] });
  expect(subareaInvalidation("algorithms", courses, "poster_9x16")).toEqual({ tags: ["media:subarea:algorithms", "media:course:course-1", "media:courses"], paths: [] });
  expect(subareaInvalidation("algorithms", [], "poster_9x16")).toEqual({ tags: ["media:subarea:algorithms"], paths: [] });
});

describe("mediaInvalidation", () => {
  it("expires nothing for a course outside the active release", () => {
    expect(mediaInvalidation({ owner: "course", kind: "poster_9x16", courseId: "course-9", published: false })).toEqual({ tags: [], paths: [] });
    expect(mediaInvalidation({ owner: "lesson", courseId: "course-9", published: false })).toEqual({ tags: [], paths: [] });
  });
  it("expires only the course's lesson covers for a lesson asset of a published course", () => {
    expect(mediaInvalidation({ owner: "lesson", courseId: "course-3", published: true })).toEqual({ tags: ["media:course:course-3"], paths: [] });
  });
  it("adds the course-list read for a poster for a course asset of a published course", () => {
    expect(mediaInvalidation({ owner: "course", kind: "poster_9x16", courseId: "course-3", published: true })).toEqual({ tags: ["media:course:course-3", "media:courses"], paths: [] });
  });
  it("does not invalidate lists for course stills or thumbs", () => {
    for (const kind of ["still_16x9", "thumb"]) expect(mediaInvalidation({ owner: "course", courseId: "course-3", published: true, kind })).toEqual({ tags: ["media:course:course-3"], paths: [] });
  });
  it("never plans the global media tag or a path other than the Home", () => {
    for (const owner of ["course", "lesson"] as const) for (const published of [true, false]) {
      const plan = mediaInvalidation({ owner, courseId: "course-1", published });
      expect(plan.tags).not.toContain("media");
      expect(plan.paths).toEqual([]);
    }
  });
});
