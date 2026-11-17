import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const root = new URL("../../..", import.meta.url);
const sheet = readFileSync(new URL("src/ui/tokens/glass.css", root), "utf8");
const snapshot = JSON.parse(readFileSync(new URL("design/figma-tokens.snapshot.json", root), "utf8")) as {
  readonly variables: Readonly<Record<string, { readonly value: string; readonly source: string; readonly description?: string }>>;
};

/** Raw length, color, or font-size. A `var(--token)` is the allowed spelling. */
export function rawGlassOffenders(css: string): string[] {
  const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const offenders: string[] = [];
  if (/\d+(?:\.\d+)?px\b/.test(withoutComments)) offenders.push("px");
  if (/#[0-9a-fA-F]{3,8}\b/.test(withoutComments)) offenders.push("hex");
  if (/font-size\s*:/.test(withoutComments)) offenders.push("font-size");
  if (/\brgb\s*\(/.test(withoutComments)) offenders.push("rgb");
  return offenders;
}

describe("D-050 glass sheet", () => {
  it("keeps the painted glass values on snapshot keys", () => {
    const painted = Object.entries(snapshot.variables).filter(([, token]) => token.source === "D-050 glass sheet");
    expect(painted.length).toBeGreaterThan(100);
    for (const [name, token] of painted) {
      expect(token.description, name).toBeTruthy();
      expect(token.value, name).not.toBe("");
    }
  });

  it("D-050: a raw glass length, hex, or font-size is refused", () => {
    expect(rawGlassOffenders(".x { width: 12px; }")).toContain("px");
    expect(rawGlassOffenders(".x { color: #fff; }")).toContain("hex");
    expect(rawGlassOffenders(".x { font-size: 16px; }")).toEqual(["px", "font-size"]);
    expect(rawGlassOffenders(".x { color: rgb(0 0 0 / 40%); }")).toContain("rgb");
    expect(rawGlassOffenders(".x { width: var(--tower-cta-clear-height); color: var(--tower-ink); }")).toEqual([]);
    expect(rawGlassOffenders(sheet)).toEqual([]);
  });
});
