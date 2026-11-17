import { expect, it } from "vitest";
import type { ReleaseFrame } from "./incremental-compile.ts";
import { frameForCourses } from "./page-frame.ts";

const frame: ReleaseFrame = {
  authors: [],
  home: {
    featuredCourseId: "course-live",
    rows: [
      { id: "yale", kind: "curated", title: "Yale", courseIds: ["course-live", "course-old"] },
      { id: "continue", kind: "continue", title: "Continue Watching", courseIds: [] },
    ],
  },
  redirects: [{ from: "/c/old", to: "/c/contracts" }, { from: "/c/gone", to: "/c/missing" }],
};

it("keeps only the courses a page selected, including a live redirect", () => {
  const next = frameForCourses(frame, [{ id: "course-live", slug: "contracts", featured: true }], [{ courseId: "course-live", slug: "lecture-1" }]);
  expect(next.home.featuredCourseId).toBe("course-live");
  expect(next.home.rows[0]?.courseIds).toEqual(["course-live"]);
  expect(next.redirects).toEqual([{ from: "/c/old", to: "/c/contracts" }]);
});

it("clears the featured flag when that course is outside the page", () => {
  const next = frameForCourses(frame, [{ id: "course-old", slug: "old-course", featured: false }], []);
  expect(next.home.featuredCourseId).toBeNull();
  expect(next.home.rows[0]?.courseIds).toEqual(["course-old"]);
  expect(next.redirects).toEqual([]);
});
