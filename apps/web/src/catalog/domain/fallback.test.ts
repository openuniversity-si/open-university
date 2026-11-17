import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import generated from "./generated/release.json" with { type: "json" };
import { normalizeBakedRelease } from "./fallback.ts";

describe("baked release normalizer", () => {
  it("normalizes the object it is given and does not import the file", () => {
    const source = readFileSync(new URL("./fallback.ts", import.meta.url), "utf8");
    expect(source).not.toContain(".json");
    const baked = normalizeBakedRelease(generated);
    expect(["database", "fixture"]).toContain(baked.source);
    expect(baked.sha).toMatch(/^[a-f0-9]{64}$/);
    expect(baked.release.schemaVersion).toBe(2);
    expect(baked.release.courses.every((course) => course.editions.length > 0)).toBe(true);
  });
});
