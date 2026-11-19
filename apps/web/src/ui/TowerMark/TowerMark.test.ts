import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Verifies: D-028
const read = (path: string) => readFileSync(new URL(`../../../${path}`, import.meta.url), "utf8");
const LEGACY_PATH = ["M9.", "37636"].join("");

function filesContaining(dir: string, needle: string, hits: string[]): void {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name.startsWith(".next")) continue;
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      filesContaining(path, needle, hits);
      continue;
    }
    if (readFileSync(path).includes(needle)) hits.push(path);
  }
}

describe("TowerMark", () => {
  it("D-028: the mark is the Saturn PNG at the approved Figma sizes and the tower path is gone", () => {
    const component = read("src/ui/TowerMark/TowerMark.tsx");
    const shell = read("src/ui/tokens/tokens.css");
    const card = read("scripts/brand-og.ts");
    expect(component).toContain('src="/brand/logo.png"');
    expect(component).toContain("width={112}");
    expect(component).toContain("height={60}");
    expect(component).toContain('data-testid="tower-mark"');
    expect(component).not.toContain("<svg");
    expect(component).not.toContain("<path");
    expect(shell).toContain("--tower-topnav-mark-width-desktop: 44.8px;");
    expect(shell).toContain("--tower-topnav-mark-height-desktop: 24px;");
    expect(shell).toContain("--tower-topnav-mark-width-mobile: 39.2px;");
    expect(shell).toContain("--tower-topnav-mark-height-mobile: 21px;");
    expect(shell).toContain("--tower-footer-mark-width: 25.2px;");
    expect(shell).toContain("--tower-footer-mark-height: 13.5px;");
    expect(shell).not.toContain("16.8px");
    expect(shell).not.toContain("19.2px");
    expect(shell).not.toContain("10.8px");
    expect(card).toContain("left: 52px; top: 121.8px; width: 154px; height: 82.5px;");
    expect(card).toContain("public/brand/logo.png");
    expect(card).not.toContain('viewBox="0 0 60 100"');
    const root = new URL("../../..", import.meta.url).pathname;
    const hits: string[] = [];
    filesContaining(root, LEGACY_PATH, hits);
    expect(hits).toEqual([]);
  });
});
