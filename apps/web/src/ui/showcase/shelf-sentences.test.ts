import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { groupByCountry, type Country } from "@/catalog/domain/countries.ts";
import type { HomeCourse } from "@/catalog/domain/home.ts";
import { universities, type University } from "@/catalog/domain/universities.ts";
import { releaseFixture } from "../../../test/fixtures/release.ts";
import { CountrySection } from "@/ui/CountrySection/CountrySection.tsx";
import { countryMeta, coverKindLabel, CREDITS_NOTE, universityHero } from "./shelf-sentences.ts";

const COUNTRIES: readonly Country[] = [
  { id: "us", name: "United States", rank: 1, placeEndings: ["MA", "CT"] },
  { id: "in", name: "India", rank: 2, placeEndings: ["India"] },
];

const university = (slug: string, place: string, courseIds: readonly string[]): University => {
  const courses = courseIds.map((id) => ({ id }) as HomeCourse);
  return { slug, name: slug, fullName: slug, place, cover: null, og: null, courses, areaCount: 0, areasNamed: false };
};

const mit = {
  slug: "mit", name: "MIT", fullName: "Massachusetts Institute of Technology", place: "Cambridge, MA",
  cover: null, courseCount: 2, areaCount: 2, areasNamed: true,
};

describe("shelf sentences", () => {
  it("paints the published university with the same hero sentence", () => {
    const release = releaseFixture();
    release.home.rows.push({ id: "mit", kind: "curated", title: "MIT", fullName: "Massachusetts Institute of Technology", place: "Cambridge, MA", courseIds: ["course-2", "course-1"] });
    release.areas = [{ id: "computer-science", title: "Computer Science" }, { id: "psychology", title: "Psychology" }, { id: "economics", title: "Economics" }];
    release.courses = release.courses.map((course) => (course.id === "course-1" ? { ...course, areaId: "psychology" } : course.id === "course-2" ? { ...course, areaId: "economics" } : course));
    const listed = universities(release)[0];
    if (!listed) throw new Error("mit");
    expect(listed.courses.map((course) => course.id)).toEqual(["course-2", "course-1"]);
    expect(universityHero({ ...listed, courseCount: listed.courses.length })).toMatchObject({
      displayTitle: "MIT", author: "CAMBRIDGE, MA · UNIVERSITY", meta: "2 courses  ·  2 areas  ·  Cambridge, MA", startHref: "/universities/mit",
    });
  });

  it("paints the university hero from counts, the published name and the place", () => {
    expect(universityHero(mit)).toMatchObject({
      displayTitle: "MIT", author: "CAMBRIDGE, MA · UNIVERSITY", meta: "2 courses  ·  2 areas  ·  Cambridge, MA",
      metaMobile: "2 courses  ·  2 areas  ·  Cambridge, MA", startHref: "/universities/mit",
    });
    expect(universityHero(mit).assets).toEqual({});
  });

  it("shifts the university's own cover and never invents a course poster", () => {
    const cover = { url: "https://media.openuniversity.si/covers/mit.webp", width: 1080, height: 1920 };
    const hero = universityHero({ ...mit, cover });
    expect(hero.assets.heroDesktop).toEqual({ ...cover, transform: [[1, 0, 0], [0, 1, 0.25]] });
    expect(hero.assets.heroMobile).toEqual({ ...cover, transform: null });
    expect(JSON.stringify(hero.assets)).not.toContain("m.test");
  });

  it("omits an area count the release does not name, and a place it does not have", () => {
    expect(universityHero({ ...mit, areasNamed: false }).meta).toBe("2 courses  ·  Cambridge, MA");
    expect(universityHero({ ...mit, place: "", courseCount: 1, areaCount: 0, areasNamed: false })).toMatchObject({
      author: "UNIVERSITY", meta: "1 course",
    });
  });

  it("paints the country line from the grouped counts, and a country with no flag last", () => {
    const groups = groupByCountry([
      university("iit-madras", "Chennai, India", ["c1"]),
      university("mit", "Cambridge, MA", ["c2", "c3"]),
      university("yale", "New Haven, CT", ["c5"]),
      university("nowhere", "", ["c6"]),
    ], COUNTRIES);
    expect(groups.map((group) => group.country?.id ?? null)).toEqual(["us", "in", null]);
    expect(countryMeta(groups[0] ?? { universityCount: 0, courseCount: 0 })).toBe("2 universities  ·  3 courses");
    expect(countryMeta(groups[1] ?? { universityCount: 0, courseCount: 0 })).toBe("1 university  ·  1 course");
    expect(countryMeta(groups[2] ?? { universityCount: 0, courseCount: 0 })).toBe("1 university  ·  1 course");
    const us = COUNTRIES[0];
    if (!us || !groups[0] || !groups[2]) throw new Error("groups");
    const flagged = renderToStaticMarkup(CountrySection({
      country: us, meta: countryMeta(groups[0]), children: null,
      flag: { width: 10, height: 6, shapes: [{ kind: "rect", x: 0, y: 0, width: 10, height: 6, fill: "#00f" }] },
    }));
    const residual = renderToStaticMarkup(CountrySection({ country: null, meta: countryMeta(groups[2]), children: null }));
    expect(flagged).toContain("2 universities  ·  3 courses");
    expect(flagged).toContain('data-flag="us"');
    expect(residual).toContain("1 university  ·  1 course");
    expect(residual).not.toContain("data-flag");
    expect(readFileSync(new URL("../Universities/UniversitiesShowcase.tsx", import.meta.url), "utf8")).toContain("countryMeta(group)");
  });

  it("paints the credit kind and the one credits sentence", () => {
    expect(coverKindLabel("university")).toBe("University cover");
    expect(coverKindLabel("author")).toBe("Author cover");
    expect(CREDITS_NOTE).toBe("Every cover is modified for Open University: cropped, toned warm black-and-white, with a gradient and title added.");
  });
});
