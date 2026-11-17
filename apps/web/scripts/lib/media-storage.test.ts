import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import sharp from "sharp";
import { describe, expect, it } from "vitest";
import { prepareMedia } from "./media-storage.ts";
import { MEDIA_PUBLIC_HOST, mediaUrlSchema, mediaKey } from "../../src/media/domain/types.ts";
describe("media ingestion", () => {
  it("strips EXIF/GPS and normalizes orientation before hashing", async () => {
    const dir = await mkdtemp(resolve(tmpdir(), "tower-media-test-"));
    try {
      const file = resolve(dir, "fixture.jpg");
      await writeFile(file, await sharp({ create: { width: 16, height: 9, channels: 3, background: "silver" } }).withMetadata({ orientation: 6 }).jpeg().toBuffer());
      const result = await prepareMedia(file);
      expect([result.width, result.height]).toEqual([9, 16]);
      const meta = await sharp(result.bytes).metadata();
      expect(meta.exif).toBeUndefined(); expect(meta.xmp).toBeUndefined(); expect(meta.iptc).toBeUndefined();
      expect(await prepareMedia(file)).toEqual(result);
    } finally { await rm(dir, { recursive: true, force: true }); }
  });
  it("keeps a bare WebP as is and re-encodes one carrying EXIF", async () => {
    const image = sharp({ create: { width: 16, height: 9, channels: 3, background: "silver" } });
    const bare = await image.clone().webp({ quality: 78 }).toBuffer();
    expect(Buffer.compare((await prepareMedia(bare)).bytes, bare)).toBe(0);
    const tagged = await image.clone().withMetadata({ orientation: 6 }).webp({ quality: 78 }).toBuffer();
    const cleaned = await prepareMedia(tagged);
    expect([cleaned.width, cleaned.height, cleaned.extension]).toEqual([9, 16, "webp"]);
    expect((await sharp(cleaned.bytes).metadata()).exif).toBeUndefined();
  });
  it.each(["https://example.com/covers/a.jpg", `https://${MEDIA_PUBLIC_HOST}/private/a.jpg`, `https://${MEDIA_PUBLIC_HOST}/covers/a.jpg?download=1`, `http://${MEDIA_PUBLIC_HOST}/covers/a.jpg`, `https://${MEDIA_PUBLIC_HOST}.evil.com/covers/a.jpg`, "https://legacy-store.example/covers/a.jpg"])("rejects unsafe media URL %s", (url) => { expect(mediaUrlSchema.safeParse(url).success).toBe(false); });
  it("rejects cross-owner kinds and SQL path injection", () => {
    expect(() => mediaKey("course", "course-1", "cover_16x9")).toThrow();
    expect(() => mediaKey("lesson", "lesson-1", "poster_9x16")).toThrow();
    expect(() => mediaKey("course", "';drop-table", "thumb")).toThrow();
  });
});
