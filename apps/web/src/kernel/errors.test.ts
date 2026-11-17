import { describe, expect, it } from "vitest";
import { AppError, assertRevision, errorSummary, preconditionsFailed } from "./errors.ts";

describe("admin errors", () => {
  it("carries the contract status and details", () => {
    const error = preconditionsFailed([{ rule: "covers.active", entity: "course:course-6", message: "No active hero_present cover." }]);
    expect([error.code, error.status, error.message]).toEqual(["preconditions_failed", 412, "1 precondition(s) failed."]);
    expect(() => { assertRevision(4, 3); }).toThrow(expect.objectContaining({ code: "revision_conflict", details: { currentRevision: 4 } }) as Error);
    expect(() => { assertRevision(3, 3); }).not.toThrow();
  });

  it("summarizes unknown errors by class and code only", () => {
    expect(errorSummary(Object.assign(new Error("password=hunter2 at postgres://u:p@h/db"), { code: "ECONNRESET" }))).toBe("Error ECONNRESET");
    expect(errorSummary(new TypeError("boom"))).toBe("TypeError");
    expect(errorSummary("string")).toBe("Error");
    expect(new AppError("invalid", "x").name).toBe("AppError");
  });
});

