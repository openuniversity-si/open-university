import sharp from "sharp";
import pixelmatch from "pixelmatch";
import { blockMeanDeltaE, deltaE2000, envelopeDeltaE, erode, labBuffer, rgbToLab } from "./perceptual.ts";

/**
 * Perceptual gate (Daniel, 8 Oct 19:31 BRT): approximation is accepted unless a person would notice it.
 * Antialiasing and subpixel text rendering are ignored; wrong colour, missing/extra elements, misalignment > 2 px
 * and weight/size changes fail. Calibrated in `perceptual.test.ts` / `pnpm fidelity:selftest`.
 */
export const FIDELITY_LIMITS = {
  /** Layout: bounding-box drift, CSS px. */
  geometry: 2,
  /** Solid colour samples: CIEDE2000 just-noticeable difference. */
  solidDeltaE: 2,
  /** Per-pixel ΔE2000 above which a difference counts as visible (after the shift envelope). */
  visibleDeltaE: 3,
  /** Shift envelope radius, CSS px (matches the geometry tolerance). */
  envelopeRadius: 2,
  /** Erosion radius, device px: removes isolated encoder/raster noise. */
  erosionRadius: 1,
  /** Visible area allowed per region, CSS px²; scattered raster noise on thin diagonals (logo hatching) stays below it. Small missing elements are also caught by the block mean. */
  visibleArea: 12,
  /** Mean colour of 16 CSS px windows: catches weight, size and tint changes. */
  blockSize: 16,
  blockDeltaE: 4,
} as const;

export interface GeometryBox {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

export interface RegionInput {
  readonly name: string;
  readonly reference: string | Buffer;
  readonly site: string | Buffer;
  readonly referenceBox: GeometryBox;
  readonly siteBox: GeometryBox;
  /** Crop at siteBox, but account for the sole approved label-row delta in geometry. */
  readonly siteGeometryBox?: GeometryBox;
  readonly dpr: 1 | 2;
  /** Solid-area coordinates relative to the region, in CSS pixels. */
  readonly colorSamples: readonly { readonly x: number; readonly y: number }[];
  readonly clipToFrame?: boolean | undefined;
  /** Image-layer extents relative to each crop. Exclude only their common rounded footprint. */
  readonly mediaMasks?: readonly { readonly reference: GeometryBox; readonly site: GeometryBox; readonly radius: number }[];
  /** Required companion: same UI with locked artwork under its untouched chrome/text layers. */
  readonly mediaChromeSite?: string | Buffer;
  /** Explicit D1 reference areas, never applied to geometry or media artwork. */
  readonly stateMasks?: readonly GeometryBox[];
  /** Only alpha pixels inherit the approved screen background; opaque pixels stay untouched. */
  readonly referenceBackground?: string;
}

export interface RegionResult {
  readonly name: string;
  readonly pass: boolean;
  readonly geometry: { readonly pass: boolean; readonly maximumDelta: number };
  readonly color: { readonly pass: boolean; readonly maximumDeltaE: number };
  readonly visible: { readonly pass: boolean; readonly areaCssPx: number; readonly maximumBlockDeltaE: number };
  /** Informational only: raw pixelmatch share, not gated. */
  readonly pixels: { readonly differing: number; readonly total: number; readonly percent: number };
  readonly images: { readonly reference: Buffer; readonly site: Buffer; readonly overlay: Buffer; readonly heatmap: Buffer };
}

export async function compareRegion(input: RegionInput): Promise<RegionResult> {
  if (input.colorSamples.length === 0) throw new Error(`Region ${input.name} needs at least one solid color sample.`);
  if (input.mediaMasks?.length && !input.mediaChromeSite) throw new Error(`Region ${input.name}: masked media requires a strict chrome capture.`);
  const delta = Math.max(...(["x", "y", "width", "height"] as const).map((key) => Math.abs(input.referenceBox[key] - (input.siteGeometryBox ?? input.siteBox)[key])));
  let width = Math.round(input.referenceBox.width * input.dpr);
  const height = Math.round(input.referenceBox.height * input.dpr);
  if (input.clipToFrame) {
    // The third mobile poster is cut by the approved 390 px rail/canvas. Its entire geometry
    // still passes the unchanged ≤2 px check; only pixels present in both exports are compared.
    const [reference, site] = await Promise.all([sharp(input.reference).metadata(), sharp(input.site).metadata()]);
    width = Math.min(width, reference.width - Math.round(input.referenceBox.x * input.dpr), site.width - Math.round(input.siteBox.x * input.dpr));
  }
  if (width <= 0 || height <= 0) throw new Error("Region dimensions must be positive.");
  const crop = async (file: string | Buffer, box: GeometryBox, background?: string) => {
    // Compare the same pixel extent; never rescale a capture to hide geometry drift.
    const source = background ? sharp(file).flatten({ background }) : sharp(file);
    return source.toColourspace("srgb").ensureAlpha().extract({ left: Math.round(box.x * input.dpr), top: Math.round(box.y * input.dpr), width, height }).raw().toBuffer();
  };
  const [reference, site] = await Promise.all([crop(input.reference, input.referenceBox, input.referenceBackground), crop(input.site, input.siteBox)]);
  const excluded = new Uint8Array(width * height);
  const inside = (x: number, y: number, box: GeometryBox, radius: number) => {
    if (x < box.x || y < box.y || x >= box.x + box.width || y >= box.y + box.height) return false;
    const r = Math.min(radius, box.width / 2, box.height / 2);
    const cx = Math.max(box.x + r, Math.min(x, box.x + box.width - r));
    const cy = Math.max(box.y + r, Math.min(y, box.y + box.height - r));
    return (x - cx) ** 2 + (y - cy) ** 2 <= r ** 2;
  };
  for (const media of input.mediaMasks ?? []) {
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
      const xx = (x + 0.5) / input.dpr, yy = (y + 0.5) / input.dpr;
      if (inside(xx, yy, media.reference, media.radius) && inside(xx, yy, media.site, media.radius)) excluded[y * width + x] = 1;
    }
  }
  for (const box of input.stateMasks ?? []) {
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
      if (inside((x + 0.5) / input.dpr, (y + 0.5) / input.dpr, box, 0)) excluded[y * width + x] = 1;
    }
  }
  let maximumDeltaE = 0;
  for (const point of input.colorSamples) {
    const x = Math.round(point.x * input.dpr);
    const y = Math.round(point.y * input.dpr);
    if (x < 0 || y < 0 || x >= width || y >= height) throw new Error(`Color sample outside region ${input.name}.`);
    if (excluded[y * width + x]) continue;
    const i = (y * width + x) * 4;
    maximumDeltaE = Math.max(maximumDeltaE, deltaE2000(rgbToLab((reference[i] ?? 0), (reference[i + 1] ?? 0), (reference[i + 2] ?? 0)), rgbToLab((site[i] ?? 0), (site[i + 1] ?? 0), (site[i + 2] ?? 0))));
  }
  const labReference = labBuffer(reference);
  const labSite = labBuffer(site);
  const envelope = envelopeDeltaE(labReference, labSite, width, height, FIDELITY_LIMITS.envelopeRadius * input.dpr, excluded);
  const mask = new Uint8Array(envelope.length);
  for (let index = 0; index < envelope.length; index++) mask[index] = (envelope[index] ?? 0) > FIDELITY_LIMITS.visibleDeltaE ? 1 : 0;
  const eroded = erode(mask, width, height, FIDELITY_LIMITS.erosionRadius);
  let visiblePixels = 0;
  for (const value of eroded) visiblePixels += value;
  const areaCssPx = visiblePixels / (input.dpr * input.dpr);
  const maximumBlockDeltaE = blockMeanDeltaE(labReference, labSite, width, height, FIDELITY_LIMITS.blockSize * input.dpr, excluded);
  const heatmap = Buffer.alloc(reference.length);
  const pixelReference = Buffer.from(reference), pixelSite = Buffer.from(site);
  for (let index = 0; index < excluded.length; index++) if (excluded[index]) {
    pixelReference.fill(0, index * 4, index * 4 + 3);
    pixelSite.fill(0, index * 4, index * 4 + 3);
  }
  const differing = pixelmatch(pixelReference, pixelSite, heatmap, width, height, { threshold: 0.1, includeAA: false });
  // Visible differences are painted red over the pixelmatch heatmap.
  for (let index = 0; index < eroded.length; index++) if (eroded[index]) { heatmap[index * 4] = 255; heatmap[index * 4 + 1] = 0; heatmap[index * 4 + 2] = 0; heatmap[index * 4 + 3] = 255; }
  const overlay = Buffer.alloc(reference.length);
  for (let index = 0; index < reference.length; index++) overlay[index] = Math.round((reference.readUInt8(index) + site.readUInt8(index)) / 2);
  const png = (data: Buffer) => sharp(data, { raw: { width, height, channels: 4 } }).png().toBuffer();
  const [referencePng, sitePng, overlayPng, heatmapPng] = await Promise.all([png(reference), png(site), png(overlay), png(heatmap)]);
  const geometryPass = delta <= FIDELITY_LIMITS.geometry;
  const colorPass = maximumDeltaE <= FIDELITY_LIMITS.solidDeltaE;
  const visiblePass = areaCssPx <= FIDELITY_LIMITS.visibleArea && maximumBlockDeltaE <= FIDELITY_LIMITS.blockDeltaE;
  const result: RegionResult = {
    name: input.name,
    pass: geometryPass && colorPass && visiblePass,
    geometry: { pass: geometryPass, maximumDelta: delta },
    color: { pass: colorPass, maximumDeltaE },
    visible: { pass: visiblePass, areaCssPx, maximumBlockDeltaE },
    pixels: { differing, total: width * height, percent: differing / (width * height) * 100 },
    images: { reference: referencePng, site: sitePng, overlay: overlayPng, heatmap: heatmapPng },
  };
  if (!input.mediaMasks?.length) return result;
  // A flattened PNG cannot separate translucent glass/scrims from the art underneath. Check
  // ALL pixels a second time with the exact locked artwork, so masking cannot hide UI changes.
  if (!input.mediaChromeSite) throw new Error(`Region ${input.name}: missing strict chrome capture.`);
  const chrome = await compareRegion({ ...input, mediaMasks: [], site: input.mediaChromeSite });
  return {
    ...result,
    pass: result.pass && chrome.pass,
    color: { pass: result.color.pass && chrome.color.pass, maximumDeltaE: Math.max(result.color.maximumDeltaE, chrome.color.maximumDeltaE) },
    visible: { pass: result.visible.pass && chrome.visible.pass, areaCssPx: Math.max(result.visible.areaCssPx, chrome.visible.areaCssPx), maximumBlockDeltaE: Math.max(result.visible.maximumBlockDeltaE, chrome.visible.maximumBlockDeltaE) },
    // Show the strict chrome capture when it failed; normal crops retain the live artwork otherwise.
    images: chrome.pass ? result.images : chrome.images,
  };
}
