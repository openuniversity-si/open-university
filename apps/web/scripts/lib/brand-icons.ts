import sharp from "sharp";

/** Icon rasters for the provisional Saturn (D-028). The site background is the chrome color. */
const BACKGROUND = "#0c0c0d";

/**
 * Flatten a transparent white Saturn PNG onto `#0c0c0d` at `size`×`size`.
 * Square sources (`public/icons/saturn-*.png`) already carry the approved padding.
 */
export async function saturnOnBackground(source: Buffer, size: number): Promise<Buffer> {
  if (!Number.isInteger(size) || size < 1 || size > 1024) throw new Error(`Icon size ${String(size)} is out of range.`);
  const mark = await sharp(source).resize(size, size, { fit: "fill" }).ensureAlpha().png().toBuffer();
  return sharp({ create: { width: size, height: size, channels: 4, background: BACKGROUND } }).composite([{ input: mark }]).png().toBuffer();
}

/** ICO container with PNG entries (sizes ≤ 256), as browsers read `favicon.ico`. */
export function icoFromPngs(images: readonly { readonly size: number; readonly png: Buffer }[]): Buffer {
  const header = Buffer.alloc(6 + 16 * images.length);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(images.length, 4);
  let offset = header.length;
  images.forEach(({ size, png }, index) => {
    const entry = 6 + 16 * index;
    header.writeUInt8(size % 256, entry);
    header.writeUInt8(size % 256, entry + 1);
    header.writeUInt16LE(1, entry + 4);
    header.writeUInt16LE(32, entry + 6);
    header.writeUInt32LE(png.length, entry + 8);
    header.writeUInt32LE(offset, entry + 12);
    offset += png.length;
  });
  return Buffer.concat([header, ...images.map((image) => image.png)]);
}
