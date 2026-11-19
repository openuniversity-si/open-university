import { describe, expect, it } from "vitest";
import type { MediaAsset } from "../../media/domain/types.ts";
import { releaseFixture } from "../../../test/fixtures/release.ts";
import { publicRouteSnapshot } from "../../catalog/server/public-routes.ts";
import { publicUniversityPaths } from "../../site/domain/route-registry.ts";
import { coursesOnUniversityPage, findUniversity, railCards, universities, universityAreas, universityCourseCount, universityRails } from "./universities.ts";

// Verifies: D-017
// ADR-25: universities are the curated rows; areas follow the release's global order and only non-empty ones show.
function withAreas() {
  const release = releaseFixture();
  release.home.rows.push({ id: "mit", kind: "curated", title: "MIT", fullName: "Massachusetts Institute of Technology", place: "Cambridge, MA", courseIds: ["course-2", "course-1"] });
  release.areas = [{ id: "computer-science", title: "Computer Science" }, { id: "psychology", title: "Psychology" }, { id: "economics", title: "Economics" }];
  release.courses = release.courses.map((course) => (course.id === "course-1" ? { ...course, areaId: "psychology" } : course.id === "course-2" ? { ...course, areaId: "economics" } : course));
  return release;
}

describe("universities", () => {
  it("lists curated rows with courses, with presentation and a hero of their own", () => {
    const release = withAreas();
    const [mit] = universities(release);
    expect(mit).toMatchObject({ slug: "mit", name: "MIT", fullName: "Massachusetts Institute of Technology", place: "Cambridge, MA", areaCount: 2, areasNamed: true });
    expect(mit?.courses.map((course) => [course.id, course.title])).toEqual([["course-2", "Original second-course"], ["course-1", "Original first-course"]]);
    expect(universityCourseCount(universities(release))).toBe(2);
    expect(findUniversity(release, "nope")).toBeUndefined();
  });

  it("groups by area in the global order, only non-empty areas, each course once", () => {
    const release = withAreas();
    const mit = findUniversity(release, "mit");
    expect(universityAreas(release, mit?.courses ?? []).map((area) => [area.id, area.courses.map((course) => course.id)])).toEqual([["psychology", ["course-1"]], ["economics", ["course-2"]]]);
  });

  it("keeps a university without a cover free of course art", () => {
    const release = withAreas();
    const poster = { kind: "poster_9x16", variant: "default", isActive: true, url: "https://m.test/p2.webp", width: 540, height: 960, transform: null } as MediaAsset;
    const [mit] = universities(release, new Map([["course-2", [poster]]]));
    expect(mit?.cover).toBeNull();
    expect(JSON.stringify({ ...mit, courses: undefined })).not.toContain("m.test");
    release.home.rows.push({ id: "bare", kind: "curated", title: "Bare U", courseIds: ["course-1"] });
    expect(findUniversity(release, "bare")).toMatchObject({ fullName: "Bare U", place: "", cover: null });
  });

  it("uses the university's own cover for the card and the hero", () => {
    const release = withAreas();
    const cover = { url: `https://media.openuniversity.si/covers/mit/university_cover_9x16/${"a".repeat(40)}.webp`, width: 1080, height: 1920, sha256: "b".repeat(64), alt: "MIT", credit: "Test", sourceUrl: "https://example.org/mit", license: "test", note: null };
    const row = release.home.rows.find((entry) => entry.id === "mit");
    if (!row) throw new Error("mit");
    row.cover = cover;
    const poster = { kind: "poster_9x16", variant: "default", isActive: true, url: "https://m.test/p2.webp", width: 540, height: 960, transform: null } as MediaAsset;
    const [mit] = universities(release, new Map([["course-2", [poster]]]));
    expect(mit?.cover?.url).toBe(cover.url);
    expect(JSON.stringify({ ...mit, courses: undefined })).not.toContain("m.test");
  });

  it("D-017: never renders an unclassified trailing rail", () => {
    const release = withAreas();
    release.courses = release.courses.map((course) => (course.id === "course-2" ? { ...course, areaId: undefined } : course));
    expect(universityAreas(release, findUniversity(release, "mit")?.courses ?? []).map((area) => area.id)).toEqual(["psychology"]);
  });

  it("lists every live course of the university, including a long rail, with every course classified", () => {
    const release = withAreas();
    const template = release.courses.find((course) => course.id === "course-2");
    const lesson = release.lessons.find((entry) => entry.courseId === "course-2");
    const row = release.home.rows.find((entry) => entry.id === "mit");
    if (!template || !lesson || !row) throw new Error("fixture");
    const extras = [
      ...Array.from({ length: 14 }, (_, index) => ({ id: `econ-${String(index)}`, areaId: "economics" })),
    ];
    release.courses = [...release.courses, ...extras.map((extra) => ({
      ...template, id: extra.id, slug: extra.id, featured: false, areaId: extra.areaId,
      editions: template.editions.map((edition) => ({ ...edition, id: `${extra.id}-e1` })),
    }))];
    release.lessons = [...release.lessons, ...extras.map((extra) => ({
      ...lesson, id: `${extra.id}-l`, courseId: extra.id, editionId: `${extra.id}-e1`, slug: "intro", youtubeId: `Y${extra.id}`.padEnd(11, "0").slice(0, 11),
    }))];
    row.courseIds = [...row.courseIds, ...extras.map((extra) => extra.id)];
    const mit = findUniversity(release, "mit");
    const live = mit?.courses ?? [];
    const listed = coursesOnUniversityPage(release, "mit", live);
    expect(listed).toHaveLength(live.length);
    expect(new Set(listed.map((course) => course.id))).toEqual(new Set(live.map((course) => course.id)));
    const economics = universityRails(release, "mit", live).filter((rail) => rail.areaId === "economics").flatMap((rail) => railCards(rail));
    expect(economics.length).toBeGreaterThan(10);
    expect(universityRails(release, "mit", live).map((rail) => rail.title)).not.toContain("More courses");
  });

  it("puts every university and area page in the sitemap", () => {
    expect(publicUniversityPaths(publicRouteSnapshot(withAreas()))).toEqual(["/universities/mit", "/universities/mit/psychology", "/universities/mit/economics"]);
    expect(publicUniversityPaths(publicRouteSnapshot(releaseFixture()))).toEqual([]);
  });
});
