import { describe, expect, it } from "vitest";
import { fakeCatalog, snapshotCatalog as catalog, TEST_REDIRECTS } from "@/catalog/testing/fake";
import { lessonsForCourse } from "@/catalog/domain/queries";
import { catalogPathStatus } from "../domain/route-registry.ts";
import { publicRouteSnapshot } from "../../catalog/server/public-routes.ts";

const status = (release: typeof catalog, path: string) => catalogPathStatus(publicRouteSnapshot(release), path);

describe("catalog paths the layout guards serve", () => {
  it("serves every course and every lesson under its own course", () => {
    const expected = catalog.courses.flatMap((course) => [`/c/${course.slug}`, ...lessonsForCourse(catalog, course.id).map((lesson) => `/c/${course.slug}/${lesson.slug}`)]);
    expect(expected.length).toBeGreaterThan(0);
    for (const path of expected) expect(status(catalog, path), path).toEqual({ kind: "live" });
  });

  it("answers 404 for unknown courses, unknown lessons and lessons under another course", () => {
    const [first] = catalog.courses;
    const [lesson] = first ? lessonsForCourse(catalog, first.id) : [];
    expect(status(catalog, "/c/not-a-course")).toEqual({ kind: "missing" });
    expect(status(catalog, "/c/not-a-course/not-a-lesson")).toEqual({ kind: "missing" });
    const other = catalog.courses.find((course) => course.id !== first?.id);
    if (first && lesson && other) expect(status(catalog, `/c/${other.slug}/${lesson.slug}`)).toEqual({ kind: "missing" });
  });

  it("answers 308 for the release's old paths, course and lesson alike", () => {
    expect(TEST_REDIRECTS.length).toBeGreaterThan(0);
    for (const { from, to } of TEST_REDIRECTS) {
      expect(status(fakeCatalog, from)).toEqual({ kind: "redirect", to });
    }
  });

  it("follows the release, not the build: a new course is served, a withdrawn one is a 404", () => {
    const [first, ...rest] = catalog.courses;
    if (!first) throw new Error("A course is required.");
    const withdrawn = { ...catalog, courses: rest, lessons: catalog.lessons.filter((lesson) => lesson.courseId !== first.id) };
    expect(status(withdrawn, `/c/${first.slug}`)).toEqual({ kind: "missing" });
    const renamed = { ...catalog, courses: catalog.courses.map((course) => (course.id === first.id ? { ...course, slug: "brand-new" } : course)) };
    expect(status(renamed, "/c/brand-new")).toEqual({ kind: "live" });
  });
});
