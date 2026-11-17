import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { coursesOnVisibleRows } from "./home.ts";
import { showcaseRowAnswer } from "./publish-answers.ts";

const source = (name: string) => readFileSync(new URL(name, import.meta.url), "utf8");

describe("courses on a visible row", () => {
  const rows = [
    { id: "open", visible: true },
    { id: "closed", visible: false },
  ];

  it("names a course on a visible row and skips a course on a hidden row", () => {
    const courses = coursesOnVisibleRows(rows, [
      { row_id: "open", course_id: "course-open" },
      { row_id: "closed", course_id: "course-closed" },
    ]);
    expect(courses.has("course-open")).toBe(true);
    expect(courses.has("course-closed")).toBe(false);
  });

  it("keeps a course that also sits on a hidden row when one row is visible", () => {
    const courses = coursesOnVisibleRows(rows, [
      { row_id: "closed", course_id: "course-9" },
      { row_id: "open", course_id: "course-9" },
    ]);
    expect([...courses]).toEqual(["course-9"]);
  });

  it("leaves an intentional orphan off the row and lets publish accept that answer", () => {
    const courses = coursesOnVisibleRows([{ id: "open", visible: true }], []);
    expect(courses.has("course-9")).toBe(false);
    expect(showcaseRowAnswer("course-9", courses.has("course-9"), true)).toEqual([]);
    expect(showcaseRowAnswer("course-9", false, false)).toEqual([
      expect.objectContaining({ rule: "home.row", owner: "showcase" }),
    ]);
  });

  it("keeps the portal, the rails and the country on the showcase", () => {
    expect(source("../home.ts")).toContain("export function signedOutHome");
    expect(source("../home.ts")).toContain("export function homePortals");
    expect(source("../universities.ts")).toContain("export function universityRails");
    expect(source("../countries.ts")).toContain("export function groupByCountry");
    expect(source("./status.ts")).not.toContain("row.visible");
  });
});
