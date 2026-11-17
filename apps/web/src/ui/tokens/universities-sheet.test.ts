import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const root = new URL("../../..", import.meta.url);
const sheet = readFileSync(new URL("src/ui/tokens/universities.css", root), "utf8");
const snapshot = JSON.parse(readFileSync(new URL("design/figma-tokens.snapshot.json", root), "utf8")) as {
  readonly variables: Readonly<Record<string, { readonly value: string; readonly source: string; readonly description?: string }>>;
};

/** Raw length, hex, or type. A `var(--token)` is the allowed spelling. */
export function rawUniversitiesOffenders(css: string): string[] {
  const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const offenders: string[] = [];
  if (/\d+(?:\.\d+)?px\b/.test(withoutComments)) offenders.push("px");
  if (/#[0-9a-fA-F]{3,8}\b/.test(withoutComments)) offenders.push("hex");
  for (const match of withoutComments.matchAll(/font-(?:size|weight)\s*:\s*([^;]+)/g)) {
    const value = (match[1] ?? "").trim();
    if (!value.startsWith("var(")) {
      offenders.push("type");
      break;
    }
  }
  return offenders;
}

describe("D-050 universities sheet", () => {
  it("keeps the painted universities values on snapshot keys", () => {
    const painted = Object.values(snapshot.variables).filter((token) => token.source === "D-050 universities sheet");
    expect(painted.length).toBeGreaterThan(70);
    for (const token of painted) expect(token.description).toBeTruthy();
    expect(snapshot.variables["tower-u-title-font-size"]?.value).toBe("28px");
    expect(snapshot.variables["tower-u-title-font-weight"]?.value).toBe("700");
  });

  it("D-050: a raw universities length, hex, or type measure is refused", () => {
    expect(rawUniversitiesOffenders(".x { font-size: 28px; }")).toEqual(["px", "type"]);
    expect(rawUniversitiesOffenders(".x { font-weight: 700; }")).toContain("type");
    expect(rawUniversitiesOffenders(".x { color: #fff; }")).toContain("hex");
    expect(rawUniversitiesOffenders(".x { font-size: var(--tower-u-title-font-size); }")).toEqual([]);
    expect(rawUniversitiesOffenders(sheet)).toEqual([]);
    expect(sheet).not.toContain("font-size: 28px");
    expect(sheet).not.toContain("font-weight: 700");
  });
});
