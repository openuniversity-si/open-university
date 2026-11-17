import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { areaSectionTitle } from "./AreaGrid.tsx";

const here = dirname(fileURLToPath(import.meta.url));
const source = (path: string) => readFileSync(join(here, path), "utf8");

describe("area grid", () => {
  it("keeps the leftover section titled Other and a subarea titled as it was given", () => {
    expect(areaSectionTitle({ kind: "rest", title: "Physics" })).toBe("Other");
    expect(areaSectionTitle({ kind: "subarea", title: "Mechanics" })).toBe("Mechanics");
    expect(areaSectionTitle({ kind: "area", title: "Physics" })).toBe("Physics");
  });

  it("paints groups the page already split", () => {
    const grid = source("./AreaGrid.tsx");
    const page = source("../../app/universities/[slug]/[area]/view.tsx");
    expect(grid).not.toMatch(/\bsplitArea\b/);
    expect(grid).toContain("Math.floor(card / 7), card % 7");
    expect(page).toContain("splitArea");
    expect(page).toContain("<AreaGrid");
    expect(page).not.toContain("area-grid");
  });
});
