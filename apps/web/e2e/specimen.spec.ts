import sharp from "sharp";
import snapshot from "../design/figma-tokens.snapshot.json" with { type: "json" };
import { test, expect } from "./fixtures/no-video-guard.ts";

test("@fidelity typography matches every Figma role after fonts are ready", async ({ page }) => {
  await page.goto("/specimen");
  await page.evaluate(() => document.fonts.ready);
  for (const role of snapshot.typography) {
    const actual = await page.getByTestId(role.className).evaluate((element, family) => {
      const css = getComputedStyle(element);
      const declared = getComputedStyle(document.documentElement).getPropertyValue(family === "Inter" ? "--tower-font-inter-face" : "--tower-font-caslon-face").trim();
      const primaryFamily = declared.split(",")[0]?.replaceAll('"', "").trim();
      const faceLoaded = Array.from(document.fonts).some((face) => face.family.replaceAll('"', "") === primaryFamily && face.status === "loaded");
      return { family: css.fontFamily, declared, weight: css.fontWeight, size: parseFloat(css.fontSize), lineHeight: css.lineHeight, tracking: parseFloat(css.letterSpacing), synthesis: css.fontSynthesis, loaded: faceLoaded && document.fonts.check(`${css.fontWeight} ${css.fontSize} "${primaryFamily ?? ""}"`) };
    }, role.family);
    expect(actual.declared).not.toBe("");
    expect(actual.family.replaceAll('"', "").toLowerCase()).toBe(`-apple-system, BlinkMacSystemFont, ${actual.declared}, Inter, sans-serif`.replaceAll('"', "").toLowerCase());
    expect(actual.weight).toBe(String(role.weight));
    expect(actual.size).toBe(role.size);
    expect(actual.loaded, role.figmaStyle).toBe(true);
    expect(actual.synthesis).toBe("none");
    if (role.lineHeight === "normal") expect(actual.lineHeight).toBe("normal");
    else expect(parseFloat(actual.lineHeight)).toBeCloseTo(role.lineHeight.endsWith("px") ? parseFloat(role.lineHeight) : parseFloat(role.lineHeight) * role.size, 2);
    expect(actual.tracking || 0).toBeCloseTo(role.letterSpacing * role.size, 2);
  }
});

test("@fidelity solid swatches match the snapshot within 2/255", async ({ page }) => {
  await page.goto("/specimen");
  await page.evaluate(() => document.fonts.ready);
  const variables: Readonly<Record<string, { readonly value: string }>> = snapshot.variables;
  for (const name of ["surface", "surface-raised", "hairline", "ink", "muted", "metal", "silver", "scrim"]) {
    const variable = variables[`tower-${name}`];
    if (!variable) throw new Error(`Missing swatch ${name}.`);
    const expected = variable.value.slice(1);
    const screenshot = await page.getByTestId(`swatch-${name}`).screenshot({ animations: "disabled", scale: "css" });
    const { data, info } = await sharp(screenshot).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
    const center = (Math.floor(info.height / 2) * info.width + Math.floor(info.width / 2)) * 4;
    for (let channel = 0; channel < 3; channel++) {
      expect(Math.abs(data.readUInt8(center + channel) - parseInt(expected.slice(channel * 2, channel * 2 + 2), 16)), `${name} channel ${String(channel)}`).toBeLessThanOrEqual(2);
    }
  }
});
