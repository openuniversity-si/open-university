import { describe, expect, it } from "vitest";
import { lessonDuration, requestedSecond } from "./time";

describe("Player return second", () => {
  it("rejects missing, repeated, negative and non-finite values", () => {
    for (const value of [undefined, ["1", "2"], "", " ", "-1", "NaN", "Infinity"]) expect(requestedSecond(value, 100)).toBe(0);
  });
  it("retains whole seconds within the lesson duration", () => {
    expect(requestedSecond("3134.9", 9128)).toBe(3134);
    expect(requestedSecond("9999", 9128)).toBe(9128);
  });
  it("formats the lesson metadata", () => {
    expect(lessonDuration(9128)).toBe("2h 32m");
  });
});
