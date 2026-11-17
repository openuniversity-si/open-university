import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";
import { generateTokenCss, generateTokenNames, generateTokenValues, generateTypographyCss, type TokenSnapshot } from "./tokens.ts";

const snapshot = JSON.parse(await readFile(new URL("../../design/figma-tokens.snapshot.json", import.meta.url), "utf8")) as TokenSnapshot;

describe("Figma token generation", () => {
  it("matches both committed CSS files byte for byte", async () => {
    expect(await readFile(new URL("../../src/ui/tokens/tokens.css", import.meta.url), "utf8")).toBe(generateTokenCss(snapshot));
    expect(await readFile(new URL("../../src/ui/tokens/values.ts", import.meta.url), "utf8")).toBe(generateTokenValues(snapshot));
    expect(await readFile(new URL("../../src/ui/tokens/names.ts", import.meta.url), "utf8")).toBe(generateTokenNames(snapshot));
    expect(await readFile(new URL("../../src/ui/typography.css", import.meta.url), "utf8")).toBe(generateTypographyCss(snapshot));
  });
  it("rejects legacy colors and invalid codeSyntax", () => {
    expect(() => generateTokenCss({ ...snapshot, variables: { "tower-accent": { value: "#e11d2e", source: "legacy", codeSyntax: "var(--tower-accent)" } } })).toThrow();
    expect(() => generateTokenCss({ ...snapshot, variables: { "tower-surface": { value: "#000", source: "test", codeSyntax: "var(--other)" } } })).toThrow();
  });
  it("D-052: a duplicated foundation literal is generated as a binding", () => {
    const css = generateTokenCss(snapshot);
    expect(css).toContain("--tower-account-name-color: var(--tower-muted);");
    expect(css).toContain("--tower-muted: #a3a3a8;");
    expect(css).toContain("--tower-layout-gutter-tablet: 32px;");
    expect(css).toContain("--tower-accent: #ffffff;");
    expect(css).toContain("--tower-ink: #ffffff;");
    expect(css).toContain("--tower-radius: 12px;");
    expect(css).toContain("--tower-radius-md: 12px;");
    expect(generateTokenValues(snapshot)).toContain('export const towerAccountNameColor = "var(--tower-muted)";');
    expect(css).toContain("--tower-continue-title-size-mobile: var(--tower-card-name-size-mobile);");
    expect(css).toContain("--tower-card-name-size-mobile: 13px;");
    expect(css).toContain("--tower-type-ui-body-small-size: var(--tower-type-ui-body-billboard-mobile-size);");
    expect(css).toContain("--tower-card-name-size-desktop: 15px;");
    expect(css).toContain("--tower-home-rail-gap: var(--tower-home-intro-gap-desktop);");
    expect(css).toContain("--tower-home-intro-gap-desktop: 20px;");
    expect(css).toContain("--tower-topnav-mark-width-desktop: 44.8px;");
    expect(css).toContain("--tower-el-frame-wide: 16 / 9;");
    expect(css).toContain("--tower-el-frame-tall: 9 / 16;");
    expect(css).toContain("--tower-el-object-fit-cover: cover;");
    expect(css).toContain("--tower-el-opacity-dim: 0.55;");
    expect(css).toContain("--tower-el-clear: transparent;");
    expect(css).toContain("--tower-el-scrim-span: 72%;");
    expect(css).toContain("--tower-el-color-scheme: dark;");
    expect(css).toContain("--tower-el-inset-ring: inset 0 0 0;");
    expect(css).toContain("--tower-cta-disabled-opacity: 0.4;");
    expect(generateTokenValues(snapshot)).toContain('export const towerElObjectFitCover = "cover";');
    expect(generateTokenNames(snapshot)).toContain('towerElFrameWide: "tower-el-frame-wide"');
  });
  it("keeps the white accent and explicit translucent alpha", () => {
    expect(snapshot.variables["tower-accent"]?.value).toBe("#ffffff");
    expect(snapshot.variables["tower-select"]?.value).toBe("var(--tower-accent)");
    expect(snapshot.variables["tower-scrubber-track"]?.value).toContain("28%");
    expect(snapshot.variables["tower-veil-panel"]?.value).toContain("72%");
  });
  it("D-050: screen measures are documented keys", () => {
    const keys: Readonly<Record<string, string>> = {
      "tower-breakpoint-narrow": "767px",
      "tower-breakpoint-tablet": "768px",
      "tower-breakpoint-desktop": "1024px",
      "tower-breakpoint-present": "1366px",
      "tower-breakpoint-wide": "1920px",
      "tower-viewport-width": "100vw",
      "tower-viewport-dynamic": "100dvh",
      "tower-viewport-small": "100svh",
      "tower-lesson-stage-inset": "476px",
      "tower-poster-near-margin": "200px",
      "tower-course-thumb-width": "96px",
      "tower-layout-gutter-tablet": "32px",
      "tower-support-blur": "1px",
    };
    for (const [name, value] of Object.entries(keys)) {
      const token = snapshot.variables[name];
      expect(token?.value, name).toBe(value);
      expect(token?.codeSyntax, name).toBe(`var(--${name})`);
      expect(token?.description, name).toBeTruthy();
    }
  });
  it("D-050: capitals and underlines are documented keys", () => {
    const keys: Readonly<Record<string, string>> = {
      "tower-label-transform": "uppercase",
      "tower-transform-none": "none",
      "tower-text-underline": "underline",
      "tower-text-decoration-none": "none",
    };
    for (const [name, value] of Object.entries(keys)) {
      const token = snapshot.variables[name];
      expect(token?.value, name).toBe(value);
      expect(token?.codeSyntax, name).toBe(`var(--${name})`);
      expect(token?.description, name).toBeTruthy();
    }
  });
});
