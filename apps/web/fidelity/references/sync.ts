import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { PRODUCTION_PAGE_IDS, planExportRoots, planImages, pngSize, rootGeometry, type FigmaClient, type FigmaNode, type PlannedImage } from "./figma.ts";
import { activateReferenceSet, deleteReferenceSets, findReferenceSet, insertAndActivateReferenceSet, knownBlobUrls, supersededReferenceSets, type ReferenceImage, type ReferenceNode, type SqlClient } from "./repository.ts";
import { sha256, type ReferenceStorage } from "./storage.ts";

export interface SyncOptions {
  readonly figma: FigmaClient;
  /** Runs `work` in a short database session; exports take minutes and idle sessions get dropped. */
  readonly database: <T>(work: (db: SqlClient) => Promise<T>) => Promise<T>;
  /** Absent on --dry-run: nothing is uploaded and nothing is written to tower_tooling. */
  readonly storage: ReferenceStorage | null;
  readonly fileKey: string;
  /** Local, gitignored staging directory for rendered PNGs (re-runs of the same version reuse it). */
  readonly stagingDirectory: string;
  readonly log: (line: string) => void;
}

export interface SyncResult {
  readonly status: "dry-run" | "created" | "activated-existing" | "already-active";
  readonly figmaVersionId: string;
  readonly lastModified: string;
  readonly setId: string | null;
  readonly images: number;
  readonly roots: Readonly<Record<string, number>>;
  readonly nodes: number;
  readonly bytes: number;
  readonly uploaded: number;
  readonly reused: number;
  readonly pruned: { readonly sets: number; readonly blobs: number };
}

const RENDER_BATCH = 8;
/** Keep the previous set for rollback; older sets are pruned so the private store stays within its quota. */
export const KEEP_INACTIVE_SETS = 1;
const DOWNLOAD_CONCURRENCY = 6;

async function pool<T>(items: readonly T[], limit: number, work: (item: T) => Promise<void>): Promise<void> {
  let next = 0;
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (next < items.length) {
      const item = items[next++];
      if (item !== undefined) await work(item);
    }
  }));
}

function indexTree(nodes: readonly FigmaNode[]): Map<string, FigmaNode> {
  const index = new Map<string, FigmaNode>();
  const walk = (node: FigmaNode) => { index.set(node.id, node); node.children?.forEach(walk); };
  nodes.forEach(walk);
  return index;
}

async function render(options: SyncOptions, version: string, plan: readonly PlannedImage[], tree: ReadonlyMap<string, FigmaNode>): Promise<Map<string, Buffer>> {
  const directory = path.join(options.stagingDirectory, version);
  await mkdir(directory, { recursive: true });
  const files = new Map<string, Buffer>();
  const missing: PlannedImage[] = [];
  for (const image of plan) {
    try {
      files.set(image.screenKey, await readFile(path.join(directory, `${image.screenKey}.png`)));
    } catch {
      missing.push(image);
    }
  }
  options.log(`fidelity:sync: ${String(plan.length - missing.length)} renders staged, ${String(missing.length)} to export.`);
  for (const scale of [1, 2] as const) {
    const pending = missing.filter((image) => image.scale === scale);
    for (let start = 0; start < pending.length; start += RENDER_BATCH) {
      const batch = pending.slice(start, start + RENDER_BATCH);
      const urls = await options.figma.renderUrls(options.fileKey, batch.map((image) => image.root.nodeId), scale, version);
      await pool(batch, DOWNLOAD_CONCURRENCY, async (image) => {
        const url = urls.get(image.root.nodeId);
        if (!url) throw new Error(`No render URL for ${image.screenKey}.`);
        const bytes = await options.figma.download(url);
        pngSize(bytes);
        const target = path.join(directory, `${image.screenKey}.png`);
        await writeFile(`${target}.partial`, bytes);
        await rename(`${target}.partial`, target);
        files.set(image.screenKey, bytes);
      });
      options.log(`fidelity:sync: exported ${String(Math.min(start + RENDER_BATCH, pending.length))}/${String(pending.length)} at ${String(scale)}x.`);
    }
  }
  for (const image of plan) {
    const bytes = files.get(image.screenKey);
    const node = tree.get(image.root.nodeId);
    if (!bytes || !node?.absoluteBoundingBox) throw new Error(`Missing render or geometry for ${image.screenKey}.`);
    const size = pngSize(bytes);
    const expected = { width: Math.round(node.absoluteBoundingBox.width * image.scale), height: Math.round(node.absoluteBoundingBox.height * image.scale) };
    if (Math.abs(size.width - expected.width) > 1 || Math.abs(size.height - expected.height) > 1) {
      throw new Error(`Render ${image.screenKey} is ${String(size.width)}×${String(size.height)}, expected ${String(expected.width)}×${String(expected.height)}.`);
    }
  }
  return files;
}

/**
 * Export the production screens of one Figma version, upload them to the private store as
 * `fidelity/<figma_version_id>/<screen_key>.png`, and record + activate the set atomically.
 * Idempotent per version: an existing set is (re)activated, never duplicated.
 */
export async function syncFidelityReferences(options: SyncOptions): Promise<SyncResult> {
  const { fileKey, database, storage, log } = options;
  const file = await options.figma.file(fileKey);
  const version = file.version;
  log(`fidelity:sync: Figma ${fileKey} version ${version} (lastModified ${file.lastModified}).`);
  const existing = await database((db) => findReferenceSet(db, fileKey, version));
  const empty = { figmaVersionId: version, lastModified: file.lastModified, images: 0, roots: {}, nodes: 0, bytes: 0, uploaded: 0, reused: 0, pruned: { sets: 0, blobs: 0 } };
  if (existing) {
    if (!storage) return { ...empty, status: "dry-run", setId: existing.id };
    if (existing.isActive) return { ...empty, status: "already-active", setId: existing.id };
    const pruned = await database(async (db) => {
      await activateReferenceSet(db, existing.id);
      return prune(db, storage, log);
    });
    return { ...empty, status: "activated-existing", setId: existing.id, pruned };
  }

  const pages = [...(await options.figma.nodes(fileKey, PRODUCTION_PAGE_IDS, version)).values()];
  const roots = planExportRoots(pages);
  const plan = planImages(roots);
  const tree = indexTree(pages);
  const nodes: ReferenceNode[] = roots.flatMap((root) => {
    const node = tree.get(root.nodeId);
    if (!node) throw new Error(`Export root ${root.nodeId} is missing from the page read.`);
    return rootGeometry(node);
  });
  const counts: Record<string, number> = {};
  for (const root of roots) counts[root.kind] = (counts[root.kind] ?? 0) + 1;
  log(`fidelity:sync: ${String(roots.length)} roots (${Object.entries(counts).map(([kind, count]) => `${kind} ${String(count)}`).join(", ")}), ${String(plan.length)} images, ${String(nodes.length)} geometry nodes.`);

  const files = await render(options, version, plan, tree);
  const known = await database((db) => knownBlobUrls(db, fileKey));
  const images: ReferenceImage[] = [];
  let uploaded = 0;
  let reused = 0;
  let bytes = 0;
  // One upload per distinct digest: identical renders in this set share a blob.
  const blobs = new Map<string, Promise<string>>();
  const store = (digest: string, pathname: string, body: Buffer): Promise<string> => {
    const knownUrl = known.get(digest);
    if (knownUrl) { reused++; return Promise.resolve(knownUrl); }
    uploaded++;
    if (!storage) return Promise.resolve(`dry-run:${pathname}`);
    return (async () => {
      const present = await storage.head(pathname);
      const stored = present ? await storage.get(present.url) : null;
      return stored && present && sha256(stored) === digest ? present.url : (await storage.put(pathname, body)).url;
    })();
  };
  await pool(plan, DOWNLOAD_CONCURRENCY, async (image) => {
    const body = files.get(image.screenKey);
    if (!body) throw new Error(`Missing render for ${image.screenKey}.`);
    const digest = sha256(body);
    const size = pngSize(body);
    bytes += body.length;
    let blobUrl = blobs.get(digest);
    if (!blobUrl) {
      blobUrl = store(digest, `fidelity/${version}/${image.screenKey}.png`, body);
      blobs.set(digest, blobUrl);
    }
    images.push({ nodeId: image.root.nodeId, screenKey: image.screenKey, viewport: image.viewport, blobUrl: await blobUrl, sha256: digest, ...size });
  });
  const result = { ...empty, images: images.length, roots: counts, nodes: nodes.length, bytes, uploaded, reused };
  if (!storage) return { ...result, status: "dry-run", setId: null };
  images.sort((a, b) => a.screenKey.localeCompare(b.screenKey));
  const note = `fidelity:sync of Figma ${version} (lastModified ${file.lastModified}): ${Object.entries(counts).map(([kind, count]) => `${String(count)} ${kind}`).join(", ")} roots at 1x and 2x.`;
  return database(async (db) => {
    const setId = await insertAndActivateReferenceSet(db, { figmaFileKey: fileKey, figmaVersionId: version, note, images, nodes });
    return { ...result, status: "created" as const, setId, pruned: await prune(db, storage, log) };
  });
}

/** Delete blobs referenced only by superseded sets, then the sets themselves (images and nodes cascade). */
async function prune(db: SqlClient, storage: ReferenceStorage, log: (line: string) => void): Promise<{ sets: number; blobs: number }> {
  const { setIds, blobUrls } = await supersededReferenceSets(db, KEEP_INACTIVE_SETS);
  if (setIds.length === 0) return { sets: 0, blobs: 0 };
  await storage.delete(blobUrls);
  await deleteReferenceSets(db, setIds);
  log(`fidelity:sync: pruned ${String(setIds.length)} superseded set(s) and ${String(blobUrls.length)} blob(s); kept the active set and ${String(KEEP_INACTIVE_SETS)} previous.`);
  return { sets: setIds.length, blobs: blobUrls.length };
}
