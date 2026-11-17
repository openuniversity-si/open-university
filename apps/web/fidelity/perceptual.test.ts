import { describe, expect, it } from "vitest";
import { deltaE2000, envelopeDeltaE, labBuffer } from "./perceptual.ts";

/** The exhaustive envelope as first written: every pixel scans its whole neighbourhood, identical or not. */
function exhaustiveEnvelopeDeltaE(reference: Float32Array, site: Float32Array, width: number, height: number, radius: number, excluded?: Uint8Array): Float32Array {
  const one = (from: Float32Array, to: Float32Array) => {
    const out = new Float32Array(width * height);
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
      if (excluded?.[y * width + x]) continue;
      const p = (y * width + x) * 3;
      const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
      for (let dy = -radius; dy <= radius; dy++) { const yy = y + dy; if (yy < 0 || yy >= height) continue;
        for (let dx = -radius; dx <= radius; dx++) { const xx = x + dx; if (xx < 0 || xx >= width) continue;
          if (excluded?.[yy * width + xx]) continue;
          const q = (yy * width + xx) * 3;
          for (let c = 0; c < 3; c++) { const v = (to[q + c] ?? 0); if (v < (lo[c] ?? 0)) lo[c] = v; if (v > (hi[c] ?? 0)) hi[c] = v; } } }
      const own: [number, number, number] = [(from[p] ?? 0), (from[p + 1] ?? 0), (from[p + 2] ?? 0)];
      const clamped: [number, number, number] = [0, 0, 0];
      for (let c = 0; c < 3; c++) clamped[c] = Math.min((hi[c] ?? 0), Math.max((lo[c] ?? 0), (own[c] ?? 0)));
      out[y * width + x] = clamped[0] === own[0] && clamped[1] === own[1] && clamped[2] === own[2] ? 0 : deltaE2000(own, clamped);
    }
    return out;
  };
  const a = one(reference, site), b = one(site, reference);
  for (let i = 0; i < a.length; i++) a[i] = Math.max((a[i] ?? 0), (b[i] ?? 0));
  return a;
}

/** Deterministic xorshift, so a failure reproduces. */
function random(seed: number) {
  let state = seed;
  return () => { state ^= state << 13; state ^= state >>> 17; state ^= state << 5; return (state >>> 0) / 2 ** 32; };
}

describe("envelope ΔE2000", () => {
  it("equals the exhaustive neighbourhood scan bit for bit (identical-pixel fast path)", () => {
    const next = random(0x5eed);
    for (const [width, height] of [[1, 1], [7, 5], [33, 21]] as const) {
      const base = Buffer.alloc(width * height * 4);
      for (let i = 0; i < base.length; i++) base[i] = i % 4 === 3 ? 255 : Math.floor(next() * 256);
      // Mostly identical pixels with small noise, scattered visible changes and a shifted block, as captures look.
      const changed = Buffer.from(base);
      for (let i = 0; i < changed.length; i += 4) {
        const roll = next();
        if (roll < 0.15) changed[i] = Math.min(255, (changed[i] ?? 0) + 2);
        else if (roll < 0.2) changed.fill(Math.floor(next() * 256), i, i + 3);
      }
      changed.copyWithin(0, 4, Math.min(changed.length, 4 * width));
      const reference = labBuffer(base), site = labBuffer(changed);
      const masks = [undefined, Uint8Array.from({ length: width * height }, () => (next() < 0.3 ? 1 : 0))];
      for (const radius of [0, 1, 2, 4]) for (const excluded of masks) {
        const fast = envelopeDeltaE(reference, site, width, height, radius, excluded);
        expect(Buffer.from(fast.buffer)).toEqual(Buffer.from(exhaustiveEnvelopeDeltaE(reference, site, width, height, radius, excluded).buffer));
        expect(Buffer.from(envelopeDeltaE(reference, reference, width, height, radius, excluded).buffer)).toEqual(Buffer.alloc(width * height * 4));
      }
    }
  });
});
