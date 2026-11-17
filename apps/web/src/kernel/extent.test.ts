import { describe, expect, it } from "vitest";
import { EXTENT } from "./extent.ts";

describe("D-050 extent", () => {
  it("names an empty result, the first element, and the floor of one", () => {
    expect(EXTENT.empty).toBe(0);
    expect(EXTENT.first).toBe(0);
    expect(EXTENT.one).toBe(1);
    expect(EXTENT.empty).toBe(EXTENT.first);
    expect(Object.keys(EXTENT)).toEqual(["empty", "first", "one"]);
  });
});
