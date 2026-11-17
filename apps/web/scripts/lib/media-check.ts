import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import sharp from "sharp";
import "../../src/media/server/public-hosts.ts";
import { mediaUrlSchema, type MediaAsset } from "../../src/media/domain/types.ts";
import { syntheticCatalog as catalog } from "../../src/catalog/testing/synthetic.ts";
import { MediaToolError } from "./media-cli.ts";
import type { MediaObjectStore } from "./media-storage.ts";

export function mediaGaps(assets: readonly MediaAsset[]) {
  const gaps: string[] = [];
  for (const course of catalog.courses) for (const kind of ["poster_9x16", "hero_desktop_16x9", "hero_present", "hero_mobile_9x16"]) {
    if (!assets.some((asset) => asset.ownerId === course.id && asset.kind === kind && asset.variant === "default")) gaps.push(`${course.id}:${kind}`);
  }
  for (const lesson of catalog.lessons) if (!assets.some((asset) => asset.ownerId === lesson.id && asset.kind === "cover_16x9" && asset.variant === "default")) gaps.push(`${lesson.id}:cover_16x9`);
  return gaps;
}
/** Throws unless `bytes` are exactly the recorded asset (sha256, dimensions, no embedded metadata). */
export async function verifyMediaBytes(asset: MediaAsset, bytes: Buffer) {
  const metadata = await sharp(bytes).metadata();
  if (createHash("sha256").update(bytes).digest("hex") !== asset.sha256 || metadata.width !== asset.width || metadata.height !== asset.height) throw new MediaToolError("Active media checksum or dimensions differ.");
  if (metadata.exif || metadata.xmp || metadata.iptc) throw new MediaToolError("Active media contains embedded metadata.");
  return bytes;
}
/** Content-addressed local copies: `<dir>/<sha256>`. `TOWER_MEDIA_SEED_DIRS` (colon-separated) adds box caches. */
export function localMediaDirs(env: Readonly<Record<string, string | undefined>> = process.env) {
  return [resolve(process.cwd(), ".fidelity-cache/media"), ...(env.TOWER_MEDIA_SEED_DIRS ?? "").split(":").filter(Boolean).map((dir) => resolve(dir))];
}
export async function readLocalMedia(sha256: string, dirs: readonly string[]) {
  for (const dir of dirs) {
    try {
      const bytes = await readFile(resolve(dir, sha256));
      if (createHash("sha256").update(bytes).digest("hex") === sha256) return bytes;
    } catch { /* not in this cache */ }
  }
  return null;
}
/** Local cache first (no network), then the storage API (read-only credential), then the public URL. `live` checks only the public URL. */
export async function fetchMediaBytes(asset: MediaAsset, options: { dirs?: readonly string[]; store?: MediaObjectStore | undefined; live?: boolean } = {}): Promise<{ bytes: Buffer; source: "local" | "storage" | "public" }> {
  mediaUrlSchema.parse(asset.url);
  if (!options.live) {
    const local = await readLocalMedia(asset.sha256, options.dirs ?? []);
    if (local) return { bytes: await verifyMediaBytes(asset, local), source: "local" };
    if (options.store) {
      const stored = await options.store.get(asset.pathname);
      if (!stored) throw new MediaToolError(`Active media object is missing from storage: ${asset.pathname}`);
      return { bytes: await verifyMediaBytes(asset, stored), source: "storage" };
    }
  }
  const response = await fetch(asset.url, { redirect: "error", signal: AbortSignal.timeout(30000) });
  if (!response.ok) throw new MediaToolError(`Active media is unavailable at its public URL (HTTP ${String(response.status)}).`);
  return { bytes: await verifyMediaBytes(asset, Buffer.from(await response.arrayBuffer())), source: "public" };
}
/** CI cache key: hash of the sorted unique active sha256 list (DB-only, no storage access). */
export function mediaManifestHash(assets: readonly MediaAsset[]) {
  return createHash("sha256").update([...new Set(assets.map((asset) => asset.sha256))].sort().join("\n")).digest("hex");
}
