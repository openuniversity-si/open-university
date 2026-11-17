import { mkdir, writeFile, rename } from "node:fs/promises";
import { resolve } from "node:path";
import type { MediaAsset } from "../../src/media/domain/types.ts";
import { MediaToolError } from "./media-cli.ts";
import { fetchMediaBytes, localMediaDirs, mediaGaps, readLocalMedia, verifyMediaBytes } from "./media-check.ts";
import type { MediaObjectStore } from "./media-storage.ts";

/** Publish the manifest only after every required real image passes checksum, dimensions and metadata checks. */
export async function cacheMedia(assets: readonly MediaAsset[], options: { offline?: boolean | undefined; store?: MediaObjectStore | undefined; dirs?: readonly string[] } = {}) {
  if (mediaGaps(assets).length) throw new MediaToolError("Fidelity media setup requires a complete active set.");
  const dirs = options.dirs ?? localMediaDirs();
  const directory = dirs[0];
  if (!directory) throw new MediaToolError("A media cache directory is required.");
  await mkdir(directory, { recursive: true });
  const counts = { active: assets.length, uniqueBytes: 0, cached: 0, seeded: 0, downloaded: 0 };
  const seen = new Set<string>();
  for (const asset of assets) {
    // Validate every descriptor even when two roles share the same bytes.
    const cached = await readLocalMedia(asset.sha256, dirs.slice(0, 1));
    if (cached) {
      await verifyMediaBytes(asset, cached);
      if (!seen.has(asset.sha256)) counts.cached++;
    } else {
      const seeded = await readLocalMedia(asset.sha256, dirs.slice(1));
      if (!seeded && options.offline) throw new MediaToolError(`Offline: ${asset.sha256} is not cached locally.`);
      const bytes = seeded ? await verifyMediaBytes(asset, seeded) : (await fetchMediaBytes(asset, { store: options.store })).bytes;
      await writeFile(resolve(directory, `${asset.sha256}.partial`), bytes);
      await rename(resolve(directory, `${asset.sha256}.partial`), resolve(directory, asset.sha256));
      if (seeded) counts.seeded++; else counts.downloaded++;
    }
    seen.add(asset.sha256);
  }
  counts.uniqueBytes = seen.size;
  await writeFile(resolve(directory, "manifest.tmp"), JSON.stringify(assets));
  await rename(resolve(directory, "manifest.tmp"), resolve(directory, "manifest.json"));
  return counts;
}
