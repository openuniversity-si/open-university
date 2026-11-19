import { describe, expect, it } from "vitest";
import type { Country } from "./countries.ts";
import { universities } from "./universities.ts";
import { COURSE_BODY_MARKER, FULL_RELEASE_COURSES, fullSizeRelease } from "../testing/full-release.ts";
import { authorsClient, cardView, homeClient, universityDetailRails, universityIndexView } from "./view-model.ts";

// Verifies: D-037
const countries: readonly Country[] = [
  { id: "us", name: "United States", rank: 1, placeEndings: ["MA"] },
  { id: "uk", name: "United Kingdom", rank: 2, placeEndings: ["United Kingdom"] },
  { id: "in", name: "India", rank: 3, placeEndings: ["India"] },
  { id: "br", name: "Brazil", rank: 4, placeEndings: ["Brazil"] },
];

const bytes = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)).length;

describe("public page view models (D-037)", () => {
  const catalog = fullSizeRelease();

  it("sends /universities under 100 KB and without a course body", () => {
    const view = universityIndexView(catalog, countries);
    expect(view.courseCount).toBe(FULL_RELEASE_COURSES);
    expect(view.groups.flatMap((group) => group.universities)).toHaveLength(48);
    expect(bytes(view)).toBeLessThan(100 * 1024);
    expect(JSON.stringify(view)).not.toContain(COURSE_BODY_MARKER);
  });

  it("sends a university page's cards without a course body", () => {
    const entry = universities(catalog).find((university) => university.slug === "university-0");
    if (!entry) throw new Error("university-0");
    const rails = universityDetailRails(catalog, entry.slug, entry.courses);
    const cards = rails.flatMap((rail) => rail.courses);
    expect(cards.length).toBe(entry.courses.length);
    expect(cards.length).toBeGreaterThan(0);
    expect(JSON.stringify(rails)).not.toContain(COURSE_BODY_MARKER);
    expect(cards[0]).toEqual({ id: cards[0]?.id, slug: cards[0]?.slug, title: cards[0]?.title, assets: {} });
  });

  it("sends Home one billboard and the portals", () => {
    const home = homeClient(catalog);
    expect(home.featured?.id).toBe("course-0");
    expect(home.portals.map((portal) => portal.tab)).toEqual(["universities", "authors"]);
    const json = JSON.stringify(home);
    expect(json).toContain(COURSE_BODY_MARKER);
    expect(json).not.toContain("course-1");
    expect(bytes(home)).toBeLessThan(100 * 1024);
  });

  it("sends authors the billboard fields a selection paints, and a card none of the body", () => {
    const authors = authorsClient(catalog);
    const json = JSON.stringify(authors);
    expect(authors.rails.flatMap((rail) => rail.courses)).toHaveLength(FULL_RELEASE_COURSES);
    expect(json).toContain(COURSE_BODY_MARKER);
    expect(json).not.toContain('"description"');
    const course = universities(catalog)[0]?.courses[0];
    if (!course) throw new Error("course");
    expect(JSON.stringify(cardView(course))).not.toContain(COURSE_BODY_MARKER);
    expect(cardView(course)).toEqual({ id: course.id, slug: course.slug, title: course.title, assets: {} });
  });
});
