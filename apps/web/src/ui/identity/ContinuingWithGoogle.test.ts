import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("./ContinuingWithGoogle.module.css", import.meta.url), "utf8");

describe("ContinuingWithGoogle", () => {
  it("dims without blurring and reuses the account-menu shade", () => {
    expect(css).not.toMatch(/backdrop-filter/);
    expect(css).toContain("var(--tower-account-veil-background)");
    expect(css).toContain("var(--tower-account-veil-mask-image)");
  });
});
