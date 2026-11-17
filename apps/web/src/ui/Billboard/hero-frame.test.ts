import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const tokens = `${read("../tokens/tokens.css")}\n${read("../tokens/home.css")}`;
interface Frame { frameWidth: number; frameHeight: number; aspect: number; appBarBottom: number; scrimClearUntil: number; scrimStrongAt: number; scrimOpaqueAt: number; subjectBand: { top: number; bottom: number; centerMin: number; centerMax: number } }
const frame = JSON.parse(read("../../../docs/media/hero-mobile-frame.json")) as Frame;
const px = (name: string) => Number(new RegExp(`--tower-${name}:\\s*(\\d+)px`).exec(tokens)?.[1]);

/**
 * The mobile hero is cropped to a fixed 390x620 frame and the course page fades it to the page colour from the scrim top down
 * (Billboard.module.css). A hero whose subject sits below the fade is invisible, which is how the 19 imported courses shipped
 * (MIT Game Theory showed a black hero). docs/media/hero-mobile-frame.json states the visible band; this keeps it true to the CSS.
 */
describe("mobile hero frame contract", () => {
  const height = px("billboard-height-mobile");
  const scrimTop = px("billboard-scrim-top-mobile");
  const stops = [...(/--tower-billboard-scrim-mobile-strong:([^;]*);/.exec(tokens)?.[1] ?? "").matchAll(/\/\s*(\d+)%\)\s+(\d+)%/g)].map(([, alpha = "0", at = "0"]) => ({ alpha: Number(alpha), at: Number(at) }));

  it("keeps the frame height and the scrim start", () => {
    expect(frame.frameHeight).toBe(height);
    expect(frame.scrimClearUntil).toBe(scrimTop);
    expect(frame.frameWidth / frame.frameHeight).toBeCloseTo(frame.aspect, 2);
  });

  it("derives where the strong course scrim is nearly and fully opaque", () => {
    const strongPct = stops.find((stop) => stop.alpha === 98)?.at;
    const opaquePct = stops.find((stop) => stop.alpha === 100)?.at;
    expect(strongPct).toBeDefined();
    expect(opaquePct).toBeDefined();
    const span = height - scrimTop;
    expect(Math.round(scrimTop + (Number(strongPct) / 100) * span)).toBe(frame.scrimStrongAt);
    expect(Math.round(scrimTop + (Number(opaquePct) / 100) * span)).toBe(frame.scrimOpaqueAt);
  });

  it("keeps the subject band inside the visible part of the frame", () => {
    const band = frame.subjectBand;
    expect(band.top).toBeGreaterThanOrEqual(frame.appBarBottom);
    expect(band.bottom).toBeLessThanOrEqual(frame.scrimStrongAt);
    expect(band.centerMin).toBeGreaterThanOrEqual(band.top);
    expect(band.centerMax).toBeLessThanOrEqual(band.bottom);
  });
});
