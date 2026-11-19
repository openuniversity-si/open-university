import { readdirSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// Verifies: D-053
describe("factory domain boundary", () => {
  it("D-053: does not import the database or name publishRelease", () => {
    const dir = new URL(".", import.meta.url);
    const leaks = readdirSync(dir).filter((name) => name.endsWith(".ts") && !name.endsWith(".test.ts")).filter((name) => {
      const source = readFileSync(new URL(name, dir), "utf8");
      return source.includes("platform/db") || source.includes("publishRelease");
    });
    expect(leaks).toEqual([]);
  });
});
