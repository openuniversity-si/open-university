import sharp from "sharp";
import { describe, expect, it } from "vitest";
import { OG_HEIGHT, OG_MAX_BYTES, OG_WIDTH, renderOgImage } from "./og.ts";
import { prepareMedia } from "./prepare.ts";

// A noisy source (worst case for JPEG size): random pixels at the given size.
const noisy = (width: number, height: number) => sharp(Buffer.from(Array.from({ length: width * height * 3 }, () => Math.floor(Math.random() * 256))), { raw: { width, height, channels: 3 } }).webp().toBuffer();

describe("link-preview images (og:image for every app, LinkedIn included)", () => {
  it("course: a 16:9 hero becomes a 1200×630 baseline JPEG under 300 KB, without metadata", async () => {
    const out = await renderOgImage(await noisy(1920, 1080), "cover");
    const meta = await sharp(out).metadata();
    expect([meta.format, meta.width, meta.height]).toEqual(["jpeg", OG_WIDTH, OG_HEIGHT]);
    expect(out.length).toBeLessThanOrEqual(OG_MAX_BYTES);
    expect(meta.exif).toBeUndefined();
  }, 30_000);

  it("university: a 9:16 cover is letterboxed whole on a dark fill", async () => {
    const white = await sharp({ create: { width: 1080, height: 1920, channels: 3, background: "#ffffff" } }).png().toBuffer();
    const out = await renderOgImage(white, "letterbox");
    const { data, info } = await sharp(out).raw().toBuffer({ resolveWithObject: true });
    expect([info.width, info.height]).toEqual([OG_WIDTH, OG_HEIGHT]);
    const pixel = (x: number, y: number) => data[(y * info.width + x) * info.channels] ?? 0;
    expect(pixel(600, 315)).toBeGreaterThan(240); // the cover, whole, in the centre
    expect(pixel(20, 315)).toBeLessThan(110); // the dark fill at the sides
  });

  it("the media store keeps a metadata-free JPEG byte for byte (a q95 re-encode only grew it), and re-encodes one with EXIF", async () => {
    const og = await renderOgImage(await noisy(1920, 1080), "cover");
    const kept = await prepareMedia(og);
    expect(Buffer.compare(kept.bytes, og)).toBe(0);
    expect(kept.extension).toBe("jpg");
    const withExif = await sharp(og).withMetadata({ exif: { IFD0: { Copyright: "x" } } }).jpeg().toBuffer();
    const cleaned = await prepareMedia(withExif);
    expect((await sharp(cleaned.bytes).metadata()).exif).toBeUndefined();
  }, 30_000);
});
