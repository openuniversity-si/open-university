import { describe, expect, it } from "vitest";
import { distanceToPageEnd, FOOTER_FADE_DISTANCE, footerOpacity, smoothstep } from "./fade";

describe("smoothstep", () => {
  it("clamps to [0, 1] and eases with t²(3 − 2t)", () => {
    expect(smoothstep(-1)).toBe(0);
    expect(smoothstep(0)).toBe(0);
    expect(smoothstep(0.25)).toBeCloseTo(0.15625, 10);
    expect(smoothstep(0.5)).toBe(0.5);
    expect(smoothstep(0.75)).toBeCloseTo(0.84375, 10);
    expect(smoothstep(1)).toBe(1);
    expect(smoothstep(2)).toBe(1);
  });
});

describe("footerOpacity (Addendum 2.5)", () => {
  it("is Hidden until the last 80 px of the page", () => {
    expect(FOOTER_FADE_DISTANCE).toBe(80);
    expect(footerOpacity(500, false)).toBe(0);
    expect(footerOpacity(80, false)).toBe(0);
  });

  it("fades in with smoothstep over the last 80 px", () => {
    expect(footerOpacity(60, false)).toBeCloseTo(0.15625, 10);
    expect(footerOpacity(40, false)).toBe(0.5);
    expect(footerOpacity(20, false)).toBeCloseTo(0.84375, 10);
  });

  it("is Visible at the end of the page and when the page does not scroll", () => {
    expect(footerOpacity(0, false)).toBe(1);
    expect(footerOpacity(-12, false)).toBe(1);
  });

  it("is fully visible with prefers-reduced-motion, whatever the scroll", () => {
    expect(footerOpacity(500, true)).toBe(1);
    expect(footerOpacity(40, true)).toBe(1);
  });
});

describe("distanceToPageEnd", () => {
  it("measures from the viewport bottom to the document end", () => {
    expect(distanceToPageEnd(1348, 0, 844)).toBe(504);
    expect(distanceToPageEnd(1348, 504, 844)).toBe(0);
    expect(distanceToPageEnd(600, 0, 844)).toBe(0);
  });
});
