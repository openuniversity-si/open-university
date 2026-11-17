import { createHash } from "node:crypto";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import sharp from "sharp";
import { afterEach, describe, expect, it, vi } from "vitest";
import inventory from "../../content/media-fixtures.json" with { type: "json" };
import { assetSchema } from "../../src/media/domain/types.ts";
import { mediaGaps } from "./media-check.ts";
import { cacheMedia } from "./media-cache.ts";

const fixtures = assetSchema.array().parse(inventory);
const dirs: string[] = [];
afterEach(async () => { vi.unstubAllGlobals(); await Promise.all(dirs.splice(0).map((dir) => rm(dir, { recursive: true, force: true }))); });
const directory = async () => { const dir = await mkdtemp(join(tmpdir(), "tower-media-cache-")); dirs.push(dir); return dir; };

describe("public browser media setup", () => {
  it("pins a complete, active real-image inventory for the versioned catalog", () => {
    expect(mediaGaps(fixtures)).toEqual([]);
    expect(fixtures.every((asset) => asset.isActive)).toBe(true);
  });
  it("hydrates an empty cache from public URLs without storage/DB credentials, then works offline", async () => {
    const bytes = await sharp({ create: { width: 16, height: 9, channels: 3, background: "#123456" } }).png().toBuffer();
    const sha256 = createHash("sha256").update(bytes).digest("hex");
    const assets = fixtures.map((asset) => ({ ...asset, sha256, width: 16, height: 9 }));
    const dir = await directory();
    const fetcher = vi.fn(() => Promise.resolve(new Response(new Uint8Array(bytes))));
    vi.stubGlobal("fetch", fetcher);
    expect(await cacheMedia(assets, { dirs: [dir] })).toMatchObject({ downloaded: 1, uniqueBytes: 1 });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(JSON.parse(await readFile(join(dir, "manifest.json"), "utf8"))).toHaveLength(fixtures.length);
    fetcher.mockRejectedValue(new Error("offline"));
    expect(await cacheMedia(assets, { dirs: [dir], offline: true })).toMatchObject({ cached: 1, downloaded: 0 });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("rejects corrupt public bytes, missing roles and contradictory duplicate dimensions before publishing a manifest", async () => {
    const dir = await directory();
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response("corrupt"))));
    await expect(cacheMedia(fixtures, { dirs: [dir] })).rejects.toThrow();
    await expect(readFile(join(dir, "manifest.json"))).rejects.toThrow();
    await expect(cacheMedia([], { dirs: [dir] })).rejects.toThrow("complete active set");
    const bytes = await sharp({ create: { width: 16, height: 9, channels: 3, background: "#123456" } }).png().toBuffer();
    const sha256 = createHash("sha256").update(bytes).digest("hex");
    await writeFile(join(dir, sha256), bytes);
    const assets = fixtures.map((asset, index) => ({ ...asset, sha256, width: index === 1 ? 17 : 16, height: 9 }));
    await expect(cacheMedia(assets, { dirs: [dir], offline: true })).rejects.toThrow("checksum or dimensions");
    await expect(readFile(join(dir, "manifest.json"))).rejects.toThrow();
  });
});
