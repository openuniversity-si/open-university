import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const root = new URL("../../..", import.meta.url);
const snapshot = JSON.parse(readFileSync(new URL("design/figma-tokens.snapshot.json", root), "utf8")) as {
  readonly variables: Readonly<Record<string, { readonly value: string; readonly source: string; readonly description?: string }>>;
};

const SHEETS = [
  ["src/ui/tokens/edition.css", "D-050 edition sheet", 30],
  ["src/ui/tokens/progress.css", "D-050 progress sheet", 20],
  ["src/ui/tokens/legal.css", "D-050 legal sheet", 15],
  ["src/ui/tokens/auth.css", "D-050 auth sheet", 15],
  ["src/ui/tokens/credits.css", "D-050 credits sheet", 8],
  ["src/ui/tokens/not-found.css", "D-050 not-found sheet", 4],
] as const;

/** Raw length or color. A `var(--token)` is the allowed spelling. */
export function rawThemeRestOffenders(css: string): string[] {
  const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const offenders: string[] = [];
  if (/\d+(?:\.\d+)?(?:px|rem|em|vh|vw|dvh|svh|ms)\b/.test(withoutComments)) offenders.push("length");
  if (/#[0-9a-fA-F]{3,8}\b/.test(withoutComments)) offenders.push("hex");
  if (/\brgb\s*\(|\bhsl\s*\(/.test(withoutComments)) offenders.push("color");
  return offenders;
}

describe("D-050 remaining theme sheets", () => {
  it("keeps the painted theme values on snapshot keys", () => {
    for (const [, source, floor] of SHEETS) {
      const painted = Object.values(snapshot.variables).filter((token) => token.source === source);
      expect(painted.length, source).toBeGreaterThan(floor);
      for (const token of painted) expect(token.description, source).toBeTruthy();
    }
    expect(snapshot.variables["tower-edition-tab-width"]?.value).toBe("88px");
    expect(snapshot.variables["tower-edition-tab-color"]?.value).toBe("#a1a2a3");
    expect(snapshot.variables["tower-legal-label-strong"]?.value).toBe("#d0d1d2");
    expect(snapshot.variables["tower-progress-check"]?.value).toBe("#f2f3f5");
    expect(snapshot.variables["tower-auth-avatar-background"]?.value).toBe("#1a1a1c");
    expect(snapshot.variables["tower-not-found-body-max-mobile"]?.value).toBe("320px");
  });

  it("D-050: a raw theme length, hex, or color is refused", () => {
    expect(rawThemeRestOffenders(".x { width: 88px; }")).toContain("length");
    expect(rawThemeRestOffenders(".x { padding: 1.5em; }")).toContain("length");
    expect(rawThemeRestOffenders(".x { color: #d0d1d2; }")).toContain("hex");
    expect(rawThemeRestOffenders(".x { color: rgb(242 243 245 / 72%); }")).toContain("color");
    expect(rawThemeRestOffenders(".x { width: var(--tower-edition-tab-width); color: var(--tower-edition-tab-color); }")).toEqual([]);
    for (const [path] of SHEETS) {
      const css = readFileSync(new URL(path, root), "utf8");
      expect(rawThemeRestOffenders(css), path).toEqual([]);
      expect(css, path).not.toContain("#d0d1d2");
      expect(css, path).not.toContain("88px");
    }
  });
});
