import { describe, expect, it } from "vitest";
import { homeDiff } from "./commands/releases.ts";

// 0013: home set must see a full name/place change (it used to answer "already matches" and send nothing).
describe("homeDiff", () => {
  const row = { id: "yale", kind: "curated" as const, title: "Yale", authorId: null, visible: true, position: 1, courseIds: ["course-1"] };
  it("reports full name and place, and ignores them when omitted", () => {
    expect(homeDiff({ featuredCourseId: null, rows: [row] }, { featuredCourseId: null, rows: [{ ...row, fullName: "Yale University", place: "New Haven, CT" }] })).toEqual(["  ~ row yale: full name - → Yale University; place - → New Haven, CT"]);
    expect(homeDiff({ featuredCourseId: null, rows: [{ ...row, fullName: "Yale University" }] }, { featuredCourseId: null, rows: [row] })).toEqual([]);
  });
});
