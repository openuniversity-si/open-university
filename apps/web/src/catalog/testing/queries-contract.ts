import { expect } from "vitest";
import type { CatalogQueriesPort } from "../ports/queries.ts";
import type { QueryFixture } from "./in-memory-queries.ts";
import { compileReleaseIndex } from "../domain/incremental-compile.ts";

export const queryFixture = (): QueryFixture => {
  const index = compileReleaseIndex({
    globalFingerprint: "global",
    courses: [
      { courseId: "course-live", sha256: "ab".repeat(32), fingerprint: "live", sourceRevision: 1 },
      { courseId: "course-old", sha256: "cd".repeat(32), fingerprint: "old", sourceRevision: 1 },
    ],
    authors: [{ id: "author-a", fingerprint: "author" }],
  });
  return {
    releases: [
      {
        number: 2,
        index,
        universities: [{ slug: "yale", title: "Yale", courseIds: ["course-live"] }],
        areas: [{ universitySlug: "yale", area: "law", courseIds: ["course-live"] }],
        courses: [{ id: "course-live", slug: "contracts", title: "Contracts", lessonIds: ["lesson-1"] }],
        authors: { authorIds: ["author-a"] },
        redirects: [{ from: "/c/old", to: "/c/contracts", statusCode: 308 }],
      },
      {
        number: 1,
        index: compileReleaseIndex({ globalFingerprint: "previous", courses: [{ courseId: "course-old", sha256: "cd".repeat(32), fingerprint: "old", sourceRevision: 1 }], authors: [] }),
        universities: [],
        areas: [],
        courses: [{ id: "course-old", slug: "old-course", title: "Old", lessonIds: [] }],
        authors: { authorIds: [] },
        redirects: [],
      },
    ],
    drafts: [{ id: "course-draft", slug: "draft", title: "Draft", status: "draft", revision: 3 }],
  };
};

export interface QueryBench {
  queries(): CatalogQueriesPort;
}

/** Shared cases for the in-memory port and the SQL adapter. */
export function queriesContract() {
  const scope = { releaseNumber: 2, preview: false as const };
  return [
    { id: "catalog.query.empty", async run(bench: QueryBench) {
      const page = await bench.queries().getUniversityPageProjection("missing", scope);
      expect(page).toBeNull();
      const authors = await bench.queries().getAuthorsDirectoryProjection({ releaseNumber: 1, preview: false });
      expect(authors.authorIds).toEqual([]);
    } },
    { id: "catalog.query.missing", async run(bench: QueryBench) {
      expect(await bench.queries().getCourseDetailProjection("absent", scope)).toBeNull();
      expect(await bench.queries().getAdminCourseSummary("absent")).toBeNull();
    } },
    { id: "catalog.query.release", async run(bench: QueryBench) {
      const current = await bench.queries().getCourseDetailProjection("contracts", scope);
      const previous = await bench.queries().getCourseDetailProjection("contracts", { releaseNumber: 1, preview: false });
      expect(current?.id).toBe("course-live");
      expect(previous).toBeNull();
      expect((await bench.queries().getCourseDetailProjection("old-course", { releaseNumber: 1, preview: false }))?.id).toBe("course-old");
    } },
    { id: "catalog.query.redirect", async run(bench: QueryBench) {
      expect(await bench.queries().resolveRedirect("/c/old", scope)).toEqual({ from: "/c/old", to: "/c/contracts", statusCode: 308 });
      expect(await bench.queries().resolveRedirect("/c/old", { releaseNumber: 1, preview: false })).toBeNull();
    } },
    { id: "catalog.query.draft", async run(bench: QueryBench) {
      const page = await bench.queries().listAdminCourses({ status: "draft", offset: 0, limit: 10 });
      expect(page.courses.map((course) => course.id)).toEqual(["course-draft"]);
      expect(await bench.queries().getCourseDetailProjection("draft", scope)).toBeNull();
    } },
    { id: "catalog.query.page", async run(bench: QueryBench) {
      const first = await bench.queries().listAdminCourses({ offset: 0, limit: 1 });
      const second = await bench.queries().listAdminCourses({ offset: 1, limit: 1 });
      expect(first.courses.map((course) => course.id)).not.toEqual(second.courses.map((course) => course.id));
      expect(first.total).toBe(second.total);
    } },
    { id: "catalog.query.isolated", async run(bench: QueryBench) {
      const page = await bench.queries().getUniversityPageProjection("yale", scope);
      if (page) page.courseIds.push("course-extra");
      const again = await bench.queries().getUniversityPageProjection("yale", scope);
      expect(again?.courseIds).toEqual(["course-live"]);
    } },
    { id: "catalog.query.preview", async run(bench: QueryBench) {
      expect(await bench.queries().getCatalogIndex({ releaseNumber: 2, preview: true })).toBeNull();
      expect(await bench.queries().getCatalogIndex(scope)).not.toBeNull();
    } },
  ];
}
