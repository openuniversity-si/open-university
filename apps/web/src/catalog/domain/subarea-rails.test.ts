import { describe, expect, it } from "vitest";
import type { HomeCourse } from "./home.ts";
import type { PublicCatalog } from "./release.ts";
import { splitArea, SUBAREA_MIN_RAIL, SUBAREA_SPLIT_AT, universityRails } from "./universities.ts";

// ADR-26: a university page splits an area into subarea rails only when that page has SUBAREA_SPLIT_AT courses of it.
const SUBAREAS = [
  { id: "mechanical-engineering", areaId: "engineering", title: "Mechanical Engineering" },
  { id: "electrical-engineering", areaId: "engineering", title: "Electrical Engineering" },
  { id: "civil-engineering", areaId: "engineering", title: "Civil Engineering" },
];

/** A catalog whose engineering courses are given as subarea ids ("" = none), in rail order; plus `extra` psychology courses. */
function page(subareas: readonly string[], extra = 0): { catalog: PublicCatalog; courses: HomeCourse[] } {
  const rows = [
    ...subareas.map((subareaId, index) => ({ id: `eng-${String(index + 1)}`, areaId: "engineering", subareaId: subareaId === "" ? undefined : subareaId })),
    ...Array.from({ length: extra }, (_, index) => ({ id: `psy-${String(index + 1)}`, areaId: "psychology", subareaId: undefined })),
  ];
  const catalog = { areas: [{ id: "engineering", title: "Engineering" }, { id: "psychology", title: "Psychology" }], subareas: SUBAREAS, courses: rows } as unknown as PublicCatalog;
  return { catalog, courses: rows.map((row) => ({ id: row.id }) as HomeCourse) };
}
const repeat = (id: string, n: number): string[] => Array.from({ length: n }, () => id);
const shape = (catalog: PublicCatalog, courses: HomeCourse[]) => universityRails(catalog, "mit", courses).map((rail) => [rail.id, rail.kind, rail.title, rail.courses.length, rail.href]);

describe("subarea rails", () => {
  it("are fixed constants", () => {
    expect([SUBAREA_SPLIT_AT, SUBAREA_MIN_RAIL]).toEqual([12, 4]);
  });

  it("keep an area of 11 courses whole, split it at 12", () => {
    const eleven = page([...repeat("mechanical-engineering", 6), ...repeat("electrical-engineering", 5)]);
    expect(shape(eleven.catalog, eleven.courses)).toEqual([["engineering", "area", "Engineering", 11, "/universities/mit/engineering"]]);
    const twelve = page([...repeat("mechanical-engineering", 6), ...repeat("electrical-engineering", 6)]);
    expect(shape(twelve.catalog, twelve.courses)).toEqual([
      ["mechanical-engineering", "subarea", "Mechanical Engineering", 6, "/universities/mit/engineering#mechanical-engineering"],
      ["electrical-engineering", "subarea", "Electrical Engineering", 6, "/universities/mit/engineering#electrical-engineering"],
    ]);
  });

  it("give a subarea its rail from 4 courses; 3 go to the area's own rail, after the subareas, in taxonomy order", () => {
    // Listed electrical first: rails still follow the taxonomy (mechanical before electrical); cards keep the page order.
    const { catalog, courses } = page([...repeat("electrical-engineering", 4), ...repeat("civil-engineering", 3), ...repeat("mechanical-engineering", 4), ""]);
    expect(shape(catalog, courses)).toEqual([
      ["mechanical-engineering", "subarea", "Mechanical Engineering", 4, "/universities/mit/engineering#mechanical-engineering"],
      ["electrical-engineering", "subarea", "Electrical Engineering", 4, "/universities/mit/engineering#electrical-engineering"],
      ["engineering-other", "rest", "Engineering", 4, "/universities/mit/engineering#engineering-other"],
    ]);
    expect(universityRails(catalog, "mit", courses)[2]?.courses.map((course) => course.id)).toEqual(["eng-5", "eng-6", "eng-7", "eng-12"]);
  });

  it("show the area whole when the split would leave a single rail", () => {
    const allOne = page(repeat("mechanical-engineering", 14));
    expect(shape(allOne.catalog, allOne.courses)).toEqual([["engineering", "area", "Engineering", 14, "/universities/mit/engineering"]]);
    const allSmall = page([...repeat("mechanical-engineering", 3), ...repeat("electrical-engineering", 3), ...repeat("", 6)]);
    expect(shape(allSmall.catalog, allSmall.courses)).toEqual([["engineering", "area", "Engineering", 12, "/universities/mit/engineering"]]);
  });

  it("keep the split area in its place among the other areas, which stay whole", () => {
    const { catalog, courses } = page([...repeat("mechanical-engineering", 8), ...repeat("", 4)], 13);
    expect(universityRails(catalog, "mit", courses).map((rail) => [rail.areaId, rail.id])).toEqual([
      ["engineering", "mechanical-engineering"], ["engineering", "engineering-other"], ["psychology", "psychology"],
    ]);
  });

  it("are decided per page: the area page groups the same way", () => {
    const { catalog, courses } = page([...repeat("mechanical-engineering", 5), ...repeat("electrical-engineering", 7)]);
    const area = { id: "engineering", title: "Engineering", courses };
    expect(splitArea(catalog, area).map((group) => group.id)).toEqual(["mechanical-engineering", "electrical-engineering"]);
    expect(splitArea(catalog, { ...area, courses: courses.slice(0, 11) }).map((group) => group.kind)).toEqual(["area"]);
  });
});
