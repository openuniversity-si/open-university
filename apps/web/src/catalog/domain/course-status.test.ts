import { describe, expect, it } from "vitest";
import { courseBodyStatuses, courseBulkStatuses, courseStatus } from "./course-status.ts";

describe("course status bodies", () => {
  it("keeps the words and the order the request schemas already accept", () => {
    expect(courseBodyStatuses).toEqual([courseStatus.review, courseStatus.draft, courseStatus.archived]);
    expect(courseBulkStatuses).toEqual([courseStatus.draft, courseStatus.archived]);
    expect(courseBodyStatuses).not.toContain(courseStatus.published);
  });
});
