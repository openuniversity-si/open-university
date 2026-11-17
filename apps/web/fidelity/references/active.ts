import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { pngSize } from "./figma.ts";
import { loadActiveReferenceSet, type ActiveReferenceSet, type ReferenceImage, type SqlClient } from "./repository.ts";
import { sha256, type ReferenceStorage } from "./storage.ts";

/** The active set as the harness consumes it: every image verified and present in the local cache. */
export interface LocalReferenceSet extends ActiveReferenceSet {
  /** screen_key → cached PNG path. */
  readonly files: Readonly<Record<string, string>>;
}

export const DEFAULT_CACHE_DIRECTORY = ".fidelity-cache/images";
export const LOCAL_SET_MANIFEST = ".reports/fidelity/reference-set.json";

/** Content-addressed cache: `<sha256>.png`, re-verified on every use, downloaded only on a miss. */
export async function cacheReferenceImage(image: ReferenceImage, storage: ReferenceStorage, directory: string): Promise<{ readonly file: string; readonly downloaded: boolean }> {
  const file = path.join(directory, `${image.sha256}.png`);
  try {
    if (sha256(await readFile(file)) === image.sha256) return { file, downloaded: false };
  } catch {
    // Cache miss: download below.
  }
  const bytes = await storage.get(image.blobUrl);
  if (!bytes) throw new Error(`Reference ${image.screenKey} is missing from the fidelity store.`);
  if (sha256(bytes) !== image.sha256) throw new Error(`Reference ${image.screenKey} does not match its recorded sha256.`);
  const size = pngSize(bytes);
  if (size.width !== image.width || size.height !== image.height) throw new Error(`Reference ${image.screenKey} dimensions differ from tower_tooling.`);
  await mkdir(directory, { recursive: true });
  const partial = `${file}.${randomUUID()}.partial`;
  await writeFile(partial, bytes);
  await rename(partial, file);
  return { file, downloaded: true };
}

export async function materializeActiveSet(db: SqlClient, storage: ReferenceStorage, directory: string, log: (line: string) => void): Promise<LocalReferenceSet> {
  const active = await loadActiveReferenceSet(db);
  // Identical renders share one sha256: fetch each distinct digest once.
  const unique = [...new Map(active.images.map((image) => [image.sha256, image])).values()];
  const cached = new Map<string, string>();
  let downloaded = 0;
  let next = 0;
  await Promise.all(Array.from({ length: 6 }, async () => {
    while (next < unique.length) {
      const image = unique[next++];
      if (!image) continue;
      const result = await cacheReferenceImage(image, storage, directory);
      cached.set(image.sha256, result.file);
      if (result.downloaded) downloaded++;
    }
  }));
  const files: Record<string, string> = {};
  for (const image of active.images) {
    const file = cached.get(image.sha256);
    if (!file) throw new Error(`Reference ${image.screenKey} was not cached.`);
    files[image.screenKey] = file;
  }
  log(`fidelity: active reference set ${active.set.id} = Figma ${active.set.figmaFileKey} version ${active.set.figmaVersionId}; ${String(active.images.length)} images (${String(unique.length)} distinct) verified by sha256 (${String(downloaded)} downloaded, ${String(unique.length - downloaded)} from cache); ${String(active.nodes.length)} geometry nodes.`);
  return { ...active, files };
}

export async function writeLocalSet(set: LocalReferenceSet, file = LOCAL_SET_MANIFEST): Promise<void> {
  await mkdir(path.dirname(file), { recursive: true });
  await writeFile(file, `${JSON.stringify(set)}\n`);
}

export async function readLocalSet(file = LOCAL_SET_MANIFEST): Promise<LocalReferenceSet> {
  try {
    return JSON.parse(await readFile(file, "utf8")) as LocalReferenceSet;
  } catch {
    throw new Error(`${file} is missing: run \`pnpm fidelity:references\` first (it reads the active set from tower_tooling).`);
  }
}
