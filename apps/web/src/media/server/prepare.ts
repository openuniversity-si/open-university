import { createHash } from "node:crypto";
import sharp from "sharp";
import { AppError } from "../../kernel/errors.ts";
import { readUploadBytes } from "./fs-store.ts";

/** The upload is not an acceptable image (nothing was stored). */
export class MediaInputError extends AppError {
  constructor(message: string) { super("unsupported_media", message); this.name = "MediaInputError"; }
}
/** A still WebP whose RIFF chunks are only image data (VP8/VP8L/VP8X/ALPH): no EXIF, XMP or ICC to strip. */
function isBareWebp(bytes: Buffer) {
  if (bytes.length < 12 || bytes.toString("latin1", 0, 4) !== "RIFF" || bytes.toString("latin1", 8, 12) !== "WEBP") return false;
  for (let offset = 12; offset < bytes.length;) {
    if (offset + 8 > bytes.length) return false;
    const size = bytes.readUInt32LE(offset + 4);
    if (!["VP8 ", "VP8L", "VP8X", "ALPH"].includes(bytes.toString("latin1", offset, offset + 4))) return false;
    offset += 8 + size + (size % 2);
  }
  return true;
}
const hashed = (bytes: Buffer, width: number, height: number, extension: string) => ({ bytes, width, height, extension, sha256: createHash("sha256").update(bytes).digest("hex") });
/**
 * Sharp deliberately drops EXIF/XMP/IPTC/GPS; animated, SVG and unknown inputs are rejected.
 * A bare WebP (pre-optimized at the origin) is stored byte for byte: re-encoding it at q95 only made it heavier.
 */
export async function prepareMedia(file: string | Uint8Array) {
  const source = typeof file === "string" ? await readUploadBytes(file) : Buffer.from(file);
  const metadata = await sharp(source).metadata().catch(() => { throw new MediaInputError("Use a single-frame JPEG, PNG, WebP or AVIF."); });
  if (!["jpeg", "png", "webp", "avif", "heif"].includes(metadata.format) || (metadata.pages ?? 1) !== 1) throw new MediaInputError("Use a single-frame JPEG, PNG, WebP or AVIF.");
  if (metadata.format === "webp" && isBareWebp(source)) return hashed(source, metadata.width, metadata.height, "webp");
  // A metadata-free, upright JPEG (e.g. a link-preview image from og.ts) is stored as is: a q95 re-encode only grew it.
  if (metadata.format === "jpeg" && !metadata.exif && !metadata.xmp && !metadata.iptc && !metadata.icc && (metadata.orientation ?? 1) === 1) return hashed(source, metadata.width, metadata.height, "jpg");
  const image = sharp(source).rotate();
  const extension = metadata.format === "jpeg" ? "jpg" : metadata.format === "heif" ? "avif" : metadata.format;
  const { data, info } = await (extension === "jpg" ? image.jpeg({ quality: 95, mozjpeg: true }) : extension === "png" ? image.png() : extension === "webp" ? image.webp({ quality: 95 }) : image.avif({ quality: 90 })).toBuffer({ resolveWithObject: true });
  return hashed(data, info.width, info.height, extension);
}
