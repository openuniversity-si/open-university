import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const root = new URL("../../..", import.meta.url);
const snapshot = JSON.parse(readFileSync(new URL("design/figma-tokens.snapshot.json", root), "utf8")) as {
  readonly variables: Readonly<Record<string, { readonly value: string; readonly source: string; readonly description?: string }>>;
};

function sheet(path: string): string {
  return readFileSync(new URL(path, root), "utf8");
}

const SHEETS = ["src/ui/tokens/player.css", "src/ui/tokens/course.css"] as const;

/** Raw length or color. A `var(--token)` is the allowed spelling. */
export function rawPlayerCourseOffenders(css: string): string[] {
  const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const offenders: string[] = [];
  if (/\d+(?:\.\d+)?(?:px|rem|em|vh|vw|dvh|svh|ms)\b/.test(withoutComments)) offenders.push("length");
  if (/#[0-9a-fA-F]{3,8}\b/.test(withoutComments)) offenders.push("hex");
  if (/\brgb\s*\(|\bhsl\s*\(/.test(withoutComments)) offenders.push("color");
  return offenders;
}

describe("D-050 player and course sheets", () => {
  it("keeps the painted player and course values on snapshot keys", () => {
    const player = Object.values(snapshot.variables).filter((token) => token.source === "D-050 player sheet");
    const course = Object.values(snapshot.variables).filter((token) => token.source === "D-050 course sheet");
    expect(player.length).toBeGreaterThan(50);
    expect(course.length).toBeGreaterThan(30);
    for (const token of [...player, ...course]) expect(token.description).toBeTruthy();
    expect(snapshot.variables["tower-player-actions-width"]?.value).toBe("551px");
    expect(snapshot.variables["tower-player-play-ink"]?.value).toBe("#f2f3f5");
    expect(snapshot.variables["tower-course-footer-gradient"]?.value).toContain("#0c0c0d");
    expect(snapshot.variables["tower-course-thumb-width"]?.value).toBe("96px");
    expect(snapshot.variables["tower-course-thumb-width"]?.source).toBe("D-050");
  });

  it("D-050: a raw player or course length or color is refused", () => {
    expect(rawPlayerCourseOffenders(".x { width: 551px; }")).toContain("length");
    expect(rawPlayerCourseOffenders(".x { width: -15px; }")).toContain("length");
    expect(rawPlayerCourseOffenders(".x { color: #f2f3f5; }")).toContain("hex");
    expect(rawPlayerCourseOffenders(".x { color: rgb(242 243 245 / 85%); }")).toContain("color");
    expect(rawPlayerCourseOffenders(".x { width: var(--tower-player-actions-width); color: var(--tower-player-play-ink); }")).toEqual([]);
    for (const path of SHEETS) {
      const css = sheet(path);
      expect(rawPlayerCourseOffenders(css), path).toEqual([]);
      expect(css, path).not.toContain("551px");
      expect(css, path).not.toContain("#f2f3f5");
    }
  });
});
