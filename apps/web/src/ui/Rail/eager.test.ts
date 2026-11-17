import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { EAGER_CARDS_IN_HTML, EAGER_CARDS_PER_ROW, EAGER_ROWS, isEagerPoster } from "./eager.ts";

const css = ["tokens.css", "shell.css"].map((file) => readFileSync(new URL(`../tokens/${file}`, import.meta.url), "utf8")).join("\n");
function px(token: string): number {
  let current = token;
  for (let hop = 0; hop < 8; hop += 1) {
    const match = new RegExp(`--${current}: ([^;]+);`).exec(css);
    const value = match?.[1]?.trim();
    if (!value) throw new Error(`Missing token --${token}.`);
    const linked = /^var\(--(tower-[a-z0-9-]+)\)$/.exec(value);
    if (linked?.[1]) {
      current = linked[1];
      continue;
    }
    const length = /^(\d+)px$/.exec(value);
    if (!length?.[1]) throw new Error(`Missing token --${token}.`);
    return Number(length[1]);
  }
  throw new Error(`Missing token --${token}.`);
}
/** Cards a rail shows (even partially) at a viewport width: gutter, then card + gap repeated. */
function visibleCards(viewport: number, card: string, gap: string, gutter: string): number {
  return Math.ceil((viewport - px(gutter) + px(gap)) / (px(card) + px(gap)));
}

describe("eager posters (P8)", () => {
  it("derives the cards per row from the rail tokens at each breakpoint", () => {
    expect(EAGER_CARDS_PER_ROW).toEqual({
      mobile: visibleCards(390, "tower-poster-portrait-card-mobile", "tower-card-gap-mobile", "tower-layout-gutter-mobile"),
      tablet: visibleCards(768, "tower-poster-portrait-card-mobile", "tower-card-gap-mobile", "tower-layout-gutter-tablet"),
      desktop: visibleCards(1920, "tower-poster-portrait-card", "tower-home-rail-gap", "tower-layout-gutter-desktop"),
    });
  });
  it("puts only the first row, narrowest viewport's cards, in the HTML", () => {
    expect(EAGER_ROWS).toBe(1);
    expect(EAGER_CARDS_IN_HTML).toBe(EAGER_CARDS_PER_ROW.mobile);
    const eager = Array.from({ length: 10 }, (_, row) => Array.from({ length: 50 }, (_, card) => isEagerPoster(row, card)));
    expect(eager.map((row) => row.filter(Boolean).length)).toEqual([3, 0, 0, 0, 0, 0, 0, 0, 0, 0]);
  });
  it("never makes the second row eager", () => {
    for (let card = 0; card < 50; card += 1) expect(isEagerPoster(1, card)).toBe(false);
  });
});
