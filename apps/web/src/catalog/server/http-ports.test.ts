import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("catalog HTTP ports", () => {
  it("imports media and oEmbed types from ports", () => {
    const source = readFileSync(new URL("./http.ts", import.meta.url), "utf8");
    expect(source).toContain("../../media/ports/storage.ts");
    expect(source).toContain("../../playback/ports/oembed.ts");
    expect(source.includes("media/server/")).toBe(false);
    expect(source.includes("playback/server/")).toBe(false);
  });

  it("injects the oEmbed checker instead of importing the playback server", () => {
    const courses = readFileSync(new URL("./courses.ts", import.meta.url), "utf8");
    const lessons = readFileSync(new URL("./lessons.ts", import.meta.url), "utf8");
    const imports = readFileSync(new URL("./imports.ts", import.meta.url), "utf8");
    const deps = readFileSync(new URL("./deps.ts", import.meta.url), "utf8");
    expect(courses.includes("playback/server/")).toBe(false);
    expect(lessons.includes("playback/server/")).toBe(false);
    expect(imports.includes("playback/server/")).toBe(false);
    expect(courses).toContain("deps.oembedChecker");
    expect(lessons).toContain("deps.oembedChecker");
    expect(imports).toContain("deps.oembedChecker");
    expect(deps).toContain("oembedChecker: OEMBED_CHECKER");
  });
});
