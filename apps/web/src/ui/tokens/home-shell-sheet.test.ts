import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const root = new URL("../../..", import.meta.url);
const snapshot = JSON.parse(readFileSync(new URL("design/figma-tokens.snapshot.json", root), "utf8")) as {
  readonly variables: Readonly<Record<string, { readonly value: string; readonly source: string; readonly description?: string }>>;
};

function sheet(path: string): string {
  return readFileSync(new URL(path, root), "utf8");
}

const SHEETS = ["src/ui/tokens/home.css", "src/ui/tokens/shell.css"] as const;

/** Raw length, color, or type. A `var(--token)` is the allowed spelling. */
export function rawThemeOffenders(css: string): string[] {
  const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const offenders: string[] = [];
  if (/\d+(?:\.\d+)?(?:px|rem|em|vh|vw|dvh|svh|ms)\b/.test(withoutComments)) offenders.push("length");
  if (/#[0-9a-fA-F]{3,8}\b/.test(withoutComments)) offenders.push("hex");
  if (/\brgb\s*\(|\bhsl\s*\(/.test(withoutComments)) offenders.push("color");
  if (/font-size\s*:|font-weight\s*:|(?:^|[^\w-])font\s*:/.test(withoutComments)) offenders.push("type");
  return offenders;
}

describe("D-050 home and shell sheets", () => {
  it("keeps the painted home and shell values on snapshot keys", () => {
    const home = Object.values(snapshot.variables).filter((token) => token.source === "D-050 home sheet");
    const shell = Object.values(snapshot.variables).filter((token) => token.source === "D-050 shell sheet");
    expect(home.length).toBeGreaterThan(100);
    expect(shell.length).toBeGreaterThan(70);
    for (const token of [...home, ...shell]) expect(token.description).toBeTruthy();
    expect(snapshot.variables["tower-layout-gutter-tablet"]?.value).toBe("32px");
    expect(snapshot.variables["tower-layout-gutter-tablet"]?.source).toBe("D-050");
  });

  it("D-050: a raw home or shell length, color, or type measure is refused", () => {
    expect(rawThemeOffenders(".x { width: 12px; }")).toContain("length");
    expect(rawThemeOffenders(".x { color: #fff; }")).toContain("hex");
    expect(rawThemeOffenders(".x { color: rgb(0 0 0 / 40%); }")).toContain("color");
    expect(rawThemeOffenders(".x { font-weight: 700; }")).toContain("type");
    expect(rawThemeOffenders(".x { width: var(--tower-layout-gutter-tablet); color: var(--tower-ink); }")).toEqual([]);
    for (const path of SHEETS) expect(rawThemeOffenders(sheet(path)), path).toEqual([]);
  });
});
