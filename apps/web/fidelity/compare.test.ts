import sharp from "sharp";
import { compareRegion } from "./compare.ts";
import { describe, expect, it } from "vitest";
import { deltaE2000 } from "./perceptual.ts";
import { runFidelitySelftest } from "./selftest.ts";

describe("perceptual fidelity gate", () => {
  it("computes CIEDE2000 against the Sharma reference pair", () => {
    expect(deltaE2000([50, 2.6772, -79.7751], [50, 0, -82.7485])).toBeCloseTo(2.0425, 3);
  });
  it("passes imperceptible rendering noise and fails visible differences", async () => {
    await expect(runFidelitySelftest(".reports/fidelity-selftest")).resolves.toBeUndefined();
  }, 60_000);
  it("clips only offscreen pixels while preserving the full card geometry gate", async () => {
    const image = await sharp({ create: { width: 100, height: 100, channels: 4, background: "#0c0c0d" } }).png().toBuffer();
    const box = { x: 80, y: 0, width: 40, height: 100 };
    const input = { name: "clipped rail", reference: image, site: image, referenceBox: box, siteBox: box, dpr: 1 as const, colorSamples: [{ x: 4, y: 4 }], clipToFrame: true };
    const result = await compareRegion(input);
    expect(result.pass).toBe(true);
    expect(result.pixels.total).toBe(20 * 100);
    expect((await compareRegion({ ...input, siteBox: { ...box, x: 83 } })).geometry.pass).toBe(false);
  });

  it("D1 masks only elapsed time, checks or scrubber pixels, preserving geometry and other chrome", async () => {
    const make = async (fill: string, outside = "#0c0c0d") => sharp({ create: { width: 80, height: 80, channels: 4, background: outside } })
      .composite([{ input: Buffer.from(`<svg width="80" height="80"><rect x="8" y="8" width="16" height="16" fill="${fill}"/></svg>`) }]).png().toBuffer();
    const reference = await make("#ffffff");
    const site = await make("#0c0c0d");
    const box = { x: 0, y: 0, width: 80, height: 80 };
    const input = { name: "D1", reference, site, referenceBox: box, siteBox: box, dpr: 1 as const, colorSamples: [{ x: 4, y: 4 }], stateMasks: [{ x: 8, y: 8, width: 16, height: 16 }] };
    expect((await compareRegion(input)).pass).toBe(true);
    expect((await compareRegion({ ...input, stateMasks: [] })).pass).toBe(false);
    expect((await compareRegion({ ...input, site: await make("#0c0c0d", "#555555") })).pass).toBe(false);
    expect((await compareRegion({ ...input, siteBox: { ...box, width: 83 } })).geometry.pass).toBe(false);
  });

  it("transparent Scroll content inherits its screen fill without altering opaque reference pixels", async () => {
    const reference = await sharp({ create: { width: 80, height: 80, channels: 4, background: "#00000000" } }).png().toBuffer();
    const site = await sharp({ create: { width: 80, height: 80, channels: 4, background: "#0c0c0d" } }).png().toBuffer();
    const box = { x: 0, y: 0, width: 80, height: 80 };
    const input = { name: "inherited screen fill", reference, site, referenceBox: box, siteBox: box, dpr: 1 as const, colorSamples: [{ x: 4, y: 4 }], referenceBackground: "#0c0c0d" };
    expect((await compareRegion(input)).pass).toBe(true);
    const opaque = await sharp({ create: { width: 80, height: 80, channels: 4, background: "#555555" } }).png().toBuffer();
    expect((await compareRegion({ ...input, reference: opaque })).pass).toBe(false);
  });

  for (const dpr of [1, 2] as const) {
    it(`masks image swaps at DPR ${String(dpr)} while retaining chrome, text and geometry`, async () => {
      const size = 80 * dpr;
      const image = async (art: string, chrome = "#252525", text = "#ffffff") => sharp({ create: { width: size, height: size, channels: 4, background: chrome } })
        .composite([{ input: Buffer.from(`<svg width="${String(size)}" height="${String(size)}"><rect x="${String(8 * dpr)}" y="${String(8 * dpr)}" width="${String(64 * dpr)}" height="${String(48 * dpr)}" fill="${art}"/><rect x="${String(8 * dpr)}" y="${String(64 * dpr)}" width="${String(48 * dpr)}" height="${String(8 * dpr)}" fill="${text}"/></svg>`) }]).png().toBuffer();
      const reference = await image("#880000");
      const site = await image("#0088ff");
      const box = { x: 0, y: 0, width: 80, height: 80 };
      const artwork = { x: 8, y: 8, width: 64, height: 48 };
      const input = { name: "mutable artwork", reference, site, referenceBox: box, siteBox: box, dpr, colorSamples: [{ x: 16, y: 16 }, { x: 4, y: 4 }], mediaMasks: [{ reference: artwork, site: artwork, radius: 0 }], mediaChromeSite: reference };
      expect((await compareRegion(input)).pass).toBe(true);
      expect((await compareRegion({ ...input, mediaMasks: [] })).pass).toBe(false);
      const chromeChange = await compareRegion({ ...input, site: await image("#0088ff", "#555555") });
      expect(chromeChange.color.pass).toBe(false);
      expect(chromeChange.visible.pass).toBe(false);
      const textChange = await compareRegion({ ...input, site: await image("#0088ff", "#252525", "#999999") });
      expect(textChange.visible.pass).toBe(false);
      // A translucent tint/scrim over artwork must still fail the companion, even INSIDE the mask.
      expect((await compareRegion({ ...input, mediaChromeSite: await image("#bb0000") })).visible.pass).toBe(false);
      expect((await compareRegion({ ...input, siteBox: { ...box, width: 83 } })).geometry.pass).toBe(false);
      await expect(compareRegion({ ...input, mediaChromeSite: "" })).rejects.toThrow(/requires a strict chrome capture/);
    });
  }
});
