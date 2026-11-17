import { describe, expect, it } from "vitest";
import { fakeCatalog, snapshotCatalog as catalog, TEST_REDIRECTS } from "@/catalog/testing/fake";
import { lessonsForCourse } from "@/catalog/domain/queries";
import { universities, universityAreas } from "@/catalog/domain/universities";
import { releaseFixture } from "../../../test/fixtures/release.ts";
import { catalogPathStatus, publicCatalogRoutes, publicPaths, publicUniversityPaths } from "../../site/domain/route-registry.ts";
import { publicRouteSnapshot } from "./public-routes.ts";

const status = (release: typeof catalog, path: string) => catalogPathStatus(publicRouteSnapshot(release), path);

describe("public route snapshot", () => {
  it("matches the release: every course and lesson, only institutions with published courses", () => {
    const snapshot = publicRouteSnapshot(catalog);
    const expected = catalog.courses.flatMap((course) => [`/c/${course.slug}`, ...lessonsForCourse(catalog, course.id).map((lesson) => `/c/${course.slug}/${lesson.slug}`)]);
    expect(publicCatalogRoutes(snapshot).map((route) => route.path)).toEqual(expected);
    expect(expected).toHaveLength(5 + 126);
    for (const path of expected) expect(status(catalog, path), path).toEqual({ kind: "live" });
    expect(snapshot.institutions).toEqual(universities(catalog).map((entry) => ({ slug: entry.slug, areaIds: universityAreas(catalog, entry.courses).map((area) => area.id) })));
    expect(publicUniversityPaths(publicRouteSnapshot(releaseFixture()))).toEqual([]);
  });

  it("keeps redirects and drops a withdrawn course", () => {
    for (const { from, to } of TEST_REDIRECTS) {
      expect(status(fakeCatalog, from)).toEqual({ kind: "redirect", to });
      expect(status(fakeCatalog, to)).toEqual({ kind: "live" });
      expect(status(catalog, from)).toEqual({ kind: "missing" });
    }
    const [first, ...rest] = catalog.courses;
    if (!first) throw new Error("A course is required.");
    const withdrawn = { ...catalog, courses: rest, lessons: catalog.lessons.filter((lesson) => lesson.courseId !== first.id) };
    expect(status(withdrawn, `/c/${first.slug}`)).toEqual({ kind: "missing" });
    const renamed = { ...catalog, courses: catalog.courses.map((course) => (course.id === first.id ? { ...course, slug: "brand-new" } : course)) };
    expect(status(renamed, "/c/brand-new")).toEqual({ kind: "live" });
  });

  it("omits an institution with no published course and an area with none", () => {
    const release = releaseFixture();
    release.home.rows.push({ id: "empty-u", kind: "curated", title: "Empty", courseIds: [] });
    release.home.rows.push({ id: "mit", kind: "curated", title: "MIT", courseIds: ["course-1"] });
    release.areas = [{ id: "psychology", title: "Psychology" }, { id: "unused", title: "Unused" }];
    release.courses = release.courses.map((course) => (course.id === "course-1" ? { ...course, areaId: "psychology" } : course));
    const snapshot = publicRouteSnapshot(release);
    expect(snapshot.institutions.map((entry) => entry.slug)).toEqual(["mit"]);
    expect(snapshot.institutions[0]?.areaIds).toEqual(["psychology"]);
    expect(publicPaths(snapshot)).toContain("/universities/mit/psychology");
    expect(publicPaths(snapshot)).not.toContain("/universities/empty-u");
    expect(publicPaths({ ...snapshot, institutions: [] }).some((path) => path.startsWith("/universities/"))).toBe(false);
  });
});
