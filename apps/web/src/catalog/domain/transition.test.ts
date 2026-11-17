import { describe, expect, it } from "vitest";
import { courseStatus } from "./course-status.ts";
import { createTransition } from "./transition.ts";

describe("stored status transitions", () => {
  it("refuses a move the stored map dropped", async () => {
    const state = {
      read: () => Promise.resolve({
        tables: { courses: [{ id: "course-1", status: courseStatus.draft }] },
        revisions: new Map([["course-1", 1]]),
        covers: new Map(),
      }),
      changeStatus: () => Promise.reject(new Error("should not write")),
    };
    await expect(createTransition(
      { courseId: "course-1", expectedRevision: 1, target: "review" },
      undefined,
      { state: state as never, audit: () => Promise.resolve() },
      { draft: [courseStatus.archived], review: [courseStatus.draft], archived: [courseStatus.draft], published: [] },
    )).rejects.toThrow(/cannot go from draft to review/);
  });
});
