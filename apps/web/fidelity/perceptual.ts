/** Perceptual colour and structure helpers for the fidelity gate (Daniel, 8 Oct 19:31 BRT: only differences a person would notice fail). */

/** sRGB 0–255 → CIE L*a*b* (D65). */
export function rgbToLab(r: number, g: number, b: number): [number, number, number] {
  const lin = (c: number) => { const v = c / 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
  const R = lin(r), G = lin(g), B = lin(b);
  const x = (0.4124564 * R + 0.3575761 * G + 0.1804375 * B) / 0.95047;
  const y = 0.2126729 * R + 0.7151522 * G + 0.072175 * B;
  const z = (0.0193339 * R + 0.119192 * G + 0.9503041 * B) / 1.08883;
  const f = (t: number) => (t > 216 / 24389 ? Math.cbrt(t) : (24389 / 27 * t + 16) / 116);
  const fx = f(x), fy = f(y), fz = f(z);
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
}

/** CIEDE2000 colour difference (Sharma, Wu & Dalal 2005). */
export function deltaE2000(lab1: readonly [number, number, number], lab2: readonly [number, number, number]): number {
  const [L1, a1, b1] = lab1; const [L2, a2, b2] = lab2;
  const rad = Math.PI / 180;
  const C1 = Math.hypot(a1, b1), C2 = Math.hypot(a2, b2);
  const Cm = (C1 + C2) / 2;
  const G = 0.5 * (1 - Math.sqrt(Cm ** 7 / (Cm ** 7 + 25 ** 7)));
  const a1p = (1 + G) * a1, a2p = (1 + G) * a2;
  const C1p = Math.hypot(a1p, b1), C2p = Math.hypot(a2p, b2);
  const hue = (b: number, a: number) => { if (a === 0 && b === 0) return 0; const h = Math.atan2(b, a) / rad; return h < 0 ? h + 360 : h; };
  const h1p = hue(b1, a1p), h2p = hue(b2, a2p);
  const dLp = L2 - L1, dCp = C2p - C1p;
  let dhp = 0;
  if (C1p * C2p !== 0) { dhp = h2p - h1p; if (dhp > 180) dhp -= 360; else if (dhp < -180) dhp += 360; }
  const dHp = 2 * Math.sqrt(C1p * C2p) * Math.sin((dhp / 2) * rad);
  const Lpm = (L1 + L2) / 2, Cpm = (C1p + C2p) / 2;
  let hpm = h1p + h2p;
  if (C1p * C2p !== 0) { if (Math.abs(h1p - h2p) > 180) hpm = h1p + h2p < 360 ? (h1p + h2p + 360) / 2 : (h1p + h2p - 360) / 2; else hpm = (h1p + h2p) / 2; }
  const T = 1 - 0.17 * Math.cos((hpm - 30) * rad) + 0.24 * Math.cos(2 * hpm * rad) + 0.32 * Math.cos((3 * hpm + 6) * rad) - 0.2 * Math.cos((4 * hpm - 63) * rad);
  const dTheta = 30 * Math.exp(-(((hpm - 275) / 25) ** 2));
  const Rc = 2 * Math.sqrt(Cpm ** 7 / (Cpm ** 7 + 25 ** 7));
  const Sl = 1 + (0.015 * (Lpm - 50) ** 2) / Math.sqrt(20 + (Lpm - 50) ** 2);
  const Sc = 1 + 0.045 * Cpm, Sh = 1 + 0.015 * Cpm * T;
  const Rt = -Math.sin(2 * dTheta * rad) * Rc;
  return Math.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh));
}

/** Binary erosion with a square structuring element of the given radius: thin edges (antialiasing, subpixel text) vanish. */
export function erode(mask: Uint8Array, width: number, height: number, radius: number): Uint8Array {
  if (radius <= 0) return mask;
  const horizontal = new Uint8Array(mask.length);
  for (let y = 0; y < height; y++) {
    let run = 0;
    const left = new Int32Array(width);
    for (let x = 0; x < width; x++) { run = mask[y * width + x] ? run + 1 : 0; left[x] = run; }
    run = 0;
    for (let x = width - 1; x >= 0; x--) {
      run = mask[y * width + x] ? run + 1 : 0;
      horizontal[y * width + x] = (left[x] ?? 0) > radius && run > radius ? 1 : 0;
    }
  }
  const out = new Uint8Array(mask.length);
  for (let x = 0; x < width; x++) {
    let run = 0;
    const up = new Int32Array(height);
    for (let y = 0; y < height; y++) { run = horizontal[y * width + x] ? run + 1 : 0; up[y] = run; }
    run = 0;
    for (let y = height - 1; y >= 0; y--) {
      run = horizontal[y * width + x] ? run + 1 : 0;
      out[y * width + x] = (up[y] ?? 0) > radius && run > radius ? 1 : 0;
    }
  }
  return out;
}

/** Convert an RGBA buffer to packed L*a*b* triples. */
export function labBuffer(data: Buffer): Float32Array {
  const out = new Float32Array((data.length / 4) * 3);
  for (let p = 0, i = 0; i < data.length; p += 3, i += 4) { const [L, a, b] = rgbToLab((data[i] ?? 0), (data[i + 1] ?? 0), (data[i + 2] ?? 0)); out[p] = L; out[p + 1] = a; out[p + 2] = b; }
  return out;
}

/**
 * Envelope ΔE2000: a pixel differs only if its colour lies outside the per-channel L*a*b* range of the other image's
 * neighbourhood within `radius` (both directions, worst of the two). Antialiasing, subpixel glyph placement and
 * offsets up to `radius` vanish, because shifted edges interpolate between neighbours; changed glyphs, missing or
 * extra elements and colour changes remain.
 */
export function envelopeDeltaE(reference: Float32Array, site: Float32Array, width: number, height: number, radius: number, excluded?: Uint8Array): Float32Array {
  const one = (from: Float32Array, to: Float32Array) => {
    const out = new Float32Array(width * height);
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
      if (excluded?.[y * width + x]) continue;
      const p = (y * width + x) * 3;
      const own0 = from[p] ?? 0, own1 = from[p + 1] ?? 0, own2 = from[p + 2] ?? 0;
      // Fast path, exact: the neighbourhood contains this very pixel, so an identical colour is inside its envelope (ΔE 0).
      if (own0 === (to[p] ?? 0) && own1 === (to[p + 1] ?? 0) && own2 === (to[p + 2] ?? 0)) continue;
      let lo0 = Infinity, lo1 = Infinity, lo2 = Infinity, hi0 = -Infinity, hi1 = -Infinity, hi2 = -Infinity;
      for (let yy = Math.max(0, y - radius); yy <= Math.min(height - 1, y + radius); yy++) {
        for (let xx = Math.max(0, x - radius); xx <= Math.min(width - 1, x + radius); xx++) {
          if (excluded?.[yy * width + xx]) continue;
          const q = (yy * width + xx) * 3;
          const v0 = to[q] ?? 0, v1 = to[q + 1] ?? 0, v2 = to[q + 2] ?? 0;
          if (v0 < lo0) lo0 = v0; if (v0 > hi0) hi0 = v0;
          if (v1 < lo1) lo1 = v1; if (v1 > hi1) hi1 = v1;
          if (v2 < lo2) lo2 = v2; if (v2 > hi2) hi2 = v2;
        }
      }
      const clamped: [number, number, number] = [Math.min(hi0, Math.max(lo0, own0)), Math.min(hi1, Math.max(lo1, own1)), Math.min(hi2, Math.max(lo2, own2))];
      out[y * width + x] = clamped[0] === own0 && clamped[1] === own1 && clamped[2] === own2 ? 0 : deltaE2000([own0, own1, own2], clamped);
    }
    return out;
  };
  const a = one(reference, site), b = one(site, reference);
  for (let i = 0; i < a.length; i++) a[i] = Math.max((a[i] ?? 0), (b[i] ?? 0));
  return a;
}

/** Largest ΔE2000 between mean L*a*b* colours of `block`×`block` windows (stride block/2): catches weight, size and broad tint changes. */
export function blockMeanDeltaE(reference: Float32Array, site: Float32Array, width: number, height: number, block: number, excluded?: Uint8Array): number {
  const size = Math.max(1, Math.min(block, width, height)); const stride = Math.max(1, Math.floor(size / 2));
  let worst = 0;
  for (let y = 0; y + size <= height; y += stride) for (let x = 0; x + size <= width; x += stride) {
    let aL = 0, aA = 0, aB = 0, bL = 0, bA = 0, bB = 0, n = 0;
    for (let j = 0; j < size; j++) for (let i = 0; i < size; i++) {
      if (excluded?.[(y + j) * width + x + i]) continue;
      n++;
      const q = ((y + j) * width + x + i) * 3;
      aL += reference[q] ?? 0; aA += reference[q + 1] ?? 0; aB += reference[q + 2] ?? 0;
      bL += site[q] ?? 0; bA += site[q + 1] ?? 0; bB += site[q + 2] ?? 0;
    }
    if (n === 0) continue;
    worst = Math.max(worst, deltaE2000([aL / n, aA / n, aB / n], [bL / n, bA / n, bB / n]));
  }
  return worst;
}
