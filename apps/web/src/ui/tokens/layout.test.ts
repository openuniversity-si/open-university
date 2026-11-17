import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { TOWER_THEME_COLOR, towerCourseLecturesWidth, towerPlayerMainWidth, towerSilverCtaAngle } from "./layout.ts";

describe("Spec 01 layout and Spec 05 CTA", () => {
  it.each([[390, 390], [1024, 548], [1366, 890], [1920, 1444], [1921, 1444], [2560, 1444]])("caps the player main at viewport %i", (width, main) => {
    expect(towerPlayerMainWidth(width)).toBe(main);
  });
  it("preserves Course columns", () => {
    expect(towerCourseLecturesWidth(1920)).toBe(1316);
    expect(towerCourseLecturesWidth(1366)).toBe(762);
    expect(towerCourseLecturesWidth(390)).toBe(350);
  });
  it("uses the hug geometry for the metallic gradient", () => {
    expect(towerSilverCtaAngle(105, 44)).toBeCloseTo(130.799, 3);
    expect(towerSilverCtaAngle(118, 48)).toBeCloseTo(131.643, 3);
    expect(() => towerSilverCtaAngle(0, 44)).toThrow();
  });
  it("keeps the browser theme colour on --tower-surface", () => {
    expect(readFileSync(new URL("tokens.css", import.meta.url), "utf8")).toContain(`--tower-surface: ${TOWER_THEME_COLOR};`);
  });
});
