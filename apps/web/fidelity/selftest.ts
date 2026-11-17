import assert from "node:assert/strict";
import sharp from "sharp";
import { compareRegion, type RegionInput } from "./compare.ts";
import { writeFidelityReport } from "./report.ts";

const WIDTH = 320;
const HEIGHT = 60;

/** Synthetic region: dark background, a card, a pill and a text line (sans-serif). */
export function syntheticRegion(options: { readonly dx?: number; readonly text?: string; readonly fill?: string; readonly weight?: number; readonly extra?: string } = {}): Buffer {
  return Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="${String(WIDTH)}" height="${String(HEIGHT)}"><rect width="100%" height="100%" fill="#0C0C0D"/><rect x="200" y="12" width="100" height="36" rx="12" fill="#1A1A1C"/><rect x="230" y="20" width="40" height="20" rx="10" fill="${options.fill ?? "#6A6A70"}"/><text x="${String(10 + (options.dx ?? 0))}" y="38" font-family="sans-serif" font-size="16" font-weight="${String(options.weight ?? 400)}" fill="#F2F3F5">${options.text ?? "Maps of Meaning · 12 lectures"}</text>${options.extra ?? ""}</svg>`);
}

/** One-time comparator sanity check: imperceptible rendering noise passes; real differences fail. */
export async function runFidelitySelftest(directory = "fidelity/report"): Promise<void> {
  const box = { x: 0, y: 0, width: WIDTH, height: HEIGHT };
  const render = (svg: Buffer, dpr: 1 | 2) => sharp(svg, { density: 72 * dpr }).png().toBuffer();
  const results = [];
  for (const dpr of [1, 2] as const) {
    const reference = await render(syntheticRegion(), dpr);
    const base: RegionInput = { name: `DPR ${String(dpr)} identity`, reference, site: reference, referenceBox: box, siteBox: box, dpr, colorSamples: [{ x: 4, y: 4 }, { x: 250, y: 30 }] };
    const run = async (name: string, site: Buffer, siteBox = box) => compareRegion({ ...base, name: `DPR ${String(dpr)} ${name}`, site: siteBox === box ? site : await sharp(site).extend({ left: siteBox.x * dpr, top: 0, right: 0, bottom: 0, background: "#0C0C0D" }).png().toBuffer(), siteBox });
    const identity = await run("identity", reference);
    const subpixel = await run("text 0.5 px subpixel shift (antialiasing)", await render(syntheticRegion({ dx: 0.5 }), dpr));
    const swap = await run("pill colour swap", await render(syntheticRegion({ fill: "#C9A86A" }), dpr));
    const missing = await run("missing pill", await render(syntheticRegion({ fill: "#1A1A1C" }), dpr));
    const extra = await run("extra 6 px dot", await render(syntheticRegion({ extra: '<circle cx="190" cy="30" r="3" fill="#F2F3F5"/>' }), dpr));
    const shifted = await run("text shifted 4 px", await render(syntheticRegion({ dx: 4 }), dpr));
    const weight = await run("text weight 400 → 700", await render(syntheticRegion({ weight: 700 }), dpr));
    const layout = await run("region moved 3 px", reference, { ...box, x: 3 });
    for (const result of [identity, subpixel]) assert.equal(result.pass, true, `${result.name} should pass`);
    for (const result of [swap, missing, extra, shifted, weight, layout]) assert.equal(result.pass, false, `${result.name} should fail`);
    assert.equal(layout.geometry.pass, false);
    assert.equal(swap.color.pass, false);
    results.push(identity, subpixel, swap, missing, extra, shifted, weight, layout);
  }
  await writeFidelityReport(results, directory, "Synthetic comparator sanity check only. These are not Figma references or site fidelity results.");
  console.log(`fidelity:selftest: ${String(results.length)} scenarios OK at DPR 1/2; identity and subpixel antialiasing pass; colour swap, missing pill, extra dot, 4 px text shift, weight change and 3 px layout drift fail.`);
}
