import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { HomeCourse } from "../../catalog/domain/home.ts";
import type { UniversityRail } from "../../catalog/domain/universities.ts";
import { UniversityRails } from "./UniversityRails.tsx";

const card = (id: string): HomeCourse => ({ id, slug: id, title: id, assets: {} }) as HomeCourse;
const rail = (id: string, courses: readonly HomeCourse[]): UniversityRail => ({
  id, kind: "area", title: id, courses, areaId: id, href: `/universities/mit/${id}`,
});

describe("UniversityRails", () => {
  it("lists every course of a rail, including past the old cap of 10, and the final rail", () => {
    const economics = Array.from({ length: 15 }, (_, index) => card(`econ-${String(index)}`));
    const more = [card("bare"), card("stray")];
    const html = renderToStaticMarkup(createElement(UniversityRails, { rails: [rail("economics", economics), rail("more", more)] }));
    const listed = [...html.matchAll(/data-testid="course-card-([^"]+)"/g)].map((match) => match[1]);
    expect(listed).toEqual([...economics, ...more].map((course) => course.id));
    expect(html).toContain('data-testid="see-all-economics"');
    expect(html).toMatch(/See all\s*(?:<!-- -->)?15/);
  });
});
