import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

/** Top-level rules of the module (outside @media), as selector → body. */
function baseRules(css: string): Map<string, string> {
  const rules = new Map<string, string>();
  let depth = 0;
  let start = 0;
  let selector = "";
  for (let index = 0; index < css.length; index += 1) {
    const char = css[index];
    if (char === "{") {
      if (depth === 0) { selector = css.slice(start, index).replace(/\/\*[\s\S]*?\*\//g, "").trim(); start = index + 1; }
      depth += 1;
    } else if (char === "}") {
      depth -= 1;
      if (depth === 0) { if (!selector.startsWith("@")) rules.set(selector, css.slice(start, index)); start = index + 1; }
    }
  }
  return rules;
}

const css = readFileSync(new URL("Universities.module.css", import.meta.url), "utf8");
const tokens = readFileSync(new URL("../tokens/tokens.css", import.meta.url), "utf8");

describe("Universities layout (regression: area title under the mobile TopNav)", () => {
  const rules = baseRules(css);
  it.each([".page", ".rails", ".area"])("%s defines its gutter outside @media, so its padding shorthand is valid at 390 px", (selector) => {
    const body = rules.get(selector) ?? "";
    expect(body).toMatch(/--tower-u-gutter:\s*var\(--tower-layout-gutter-mobile\)/);
  });
  it("the area page clears the fixed TopNav fade on mobile and desktop", () => {
    expect(rules.get(".area")).toContain("var(--tower-u-area-padding-top)");
    expect(tokens).toMatch(/--tower-u-area-padding-top:\s*calc\(var\(--tower-topnav-fade-height-mobile\)/);
    expect(tokens).toMatch(/--tower-u-area-padding-top-desktop:\s*calc\(var\(--tower-topnav-fade-height-desktop\)/);
  });
});
