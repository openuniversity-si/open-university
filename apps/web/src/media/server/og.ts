import sharp, { type Sharp } from "sharp";
import { OG_HEIGHT, OG_MAX_BYTES, OG_WIDTH, ogMatte, type OgLayout } from "../domain/og.ts";

/**
 * Link-preview images (Open Graph / Twitter / LinkedIn): 1200×630 baseline JPEG under 300 KB, the format every app shows.
 * Courses: the desktop hero, cropped to fill. Universities: the 9:16 cover centred whole over a dark, blurred fill of
 * itself (the site's dark style), so the building is never cut. Stored as `hero_desktop_16x9/og` (courses) and in the
 * university cover's `og` field.
 */
export { OG_COURSE_KIND, OG_HEIGHT, OG_MAX_BYTES, OG_UNIVERSITY_KIND, OG_VARIANT, OG_WIDTH, type OgLayout } from "../domain/og.ts";
const QUALITIES = [82, 74, 66, 58, 50] as const;

// Low memory: one libvips thread, no operation cache (the box runs many agents).
sharp.concurrency(1);
sharp.cache(false);

async function compose(source: Buffer, layout: OgLayout): Promise<Sharp> {
  if (layout === "cover") return sharp(source).rotate().resize(OG_WIDTH, OG_HEIGHT, { fit: "cover", position: "attention" });
  const backdrop = await sharp(source).rotate().resize(OG_WIDTH, OG_HEIGHT, { fit: "cover" }).blur(40).modulate({ brightness: 0.32, saturation: 0.6 }).toBuffer();
  const front = await sharp(source).rotate().resize({ height: OG_HEIGHT, width: OG_WIDTH, fit: "inside" }).toBuffer();
  return sharp(backdrop).composite([{ input: front, gravity: "centre" }]);
}

/** The preview JPEG: no metadata (stored verbatim by the media store), the best quality that fits OG_MAX_BYTES. */
export async function renderOgImage(source: Buffer, layout: OgLayout): Promise<Buffer> {
  let size = 0;
  for (const quality of QUALITIES) {
    const image = await compose(source, layout);
    const last = await image.flatten({ background: ogMatte }).jpeg({ quality, mozjpeg: true, chromaSubsampling: "4:2:0" }).toBuffer();
    if (last.length <= OG_MAX_BYTES) return last;
    size = last.length;
  }
  throw new Error(`The preview image stays over ${String(OG_MAX_BYTES / 1024)} KiB even at quality ${String(QUALITIES.at(-1))} (${String(Math.ceil(size / 1024))} KiB).`);
}
