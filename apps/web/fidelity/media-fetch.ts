import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import sharp from "sharp";
import { FIDELITY_FRAMES } from "./frames.ts";
import { MEDIA_ART_MANIFEST, mediaArtKey, referenceMediaLayers, type ReferenceMediaLayer } from "./media.ts";
import { readLocalSet } from "./references/active.ts";
import { referenceStorageFromEnv } from "./references/storage.ts";

// GET-only, artwork-only exports for the companion chrome capture. The reference set and PNGs
// remain unchanged. These private, disposable files never enter git or the production app.
const set = await readLocalSet();
const directory = ".fidelity-cache/media-masks";
await mkdir(directory, { recursive: true });
const files: Record<string, string> = {};
// Local copies first (CI restores this directory from actions/cache keyed by the reference set); storage only on a miss.
const storage = referenceStorageFromEnv(process.env, "ro") ?? undefined;
const origin = new URL(set.images[0]?.blobUrl ?? "https://invalid.example").origin;
let downloaded = 0;
for (const dpr of [1, 2] as const) {
  const layers = [...new Map(FIDELITY_FRAMES.filter((frame) => frame.dpr === dpr).flatMap((frame) => referenceMediaLayers(frame, set)).map((layer) => [layer.nodeId, layer])).values()];
  const missing: ReferenceMediaLayer[] = [];
  for (const layer of layers) {
    const key = mediaArtKey(layer.nodeId, dpr);
    const digest = createHash("sha256").update(`${set.set.figmaFileKey}/${set.set.figmaVersionId}/${key}`).digest("hex");
    const file = `${directory}/${digest}.png`;
    files[key] = file;
    try {
      const metadata = await sharp(await readFile(file)).metadata();
      if (metadata.width !== Math.round(layer.box.width * dpr) || metadata.height !== Math.round(layer.box.height * dpr)) throw new Error("Invalid cached artwork dimensions.");
    } catch {
      // Miss: read the private companion cache with the read-only storage credential.
      const bytes = await storage?.get(`${origin}/media-mask-art/${digest}.png`);
      const metadata = bytes ? await sharp(bytes).metadata() : undefined;
      if (bytes && metadata?.width === Math.round(layer.box.width * dpr) && metadata.height === Math.round(layer.box.height * dpr)) {
        await writeFile(file, bytes);
        downloaded++;
      } else missing.push(layer);
    }
  }
  if (missing.length === 0) continue;
  const token = process.env.FIGMA_TOKEN;
  if (!token) throw new Error("FIGMA_TOKEN is required to GET locked artwork layers for strict chrome comparison.");
  // A PlayerFrame's fill is a plain bitmap. Its node export would include controls;
  // resolve the original image fill and apply Figma's centered FILL crop instead.
  const fills = missing.filter((layer) => layer.imageFill);
  if (fills.length) {
    const nodeParams = new URLSearchParams({ ids: fills.map((layer) => layer.nodeId).join(","), version: set.set.figmaVersionId });
    const [nodeResponse, fillResponse] = await Promise.all([
      fetch(`https://api.figma.com/v1/files/${set.set.figmaFileKey}/nodes?${nodeParams}`, { headers: { "X-Figma-Token": token } }),
      fetch(`https://api.figma.com/v1/files/${set.set.figmaFileKey}/images`, { headers: { "X-Figma-Token": token } }),
    ]);
    if (!nodeResponse.ok || !fillResponse.ok) throw new Error("Figma image-fill GET failed.");
    const nodes = await nodeResponse.json() as { nodes: Record<string, { document: { fills: { type: string; imageRef?: string; scaleMode?: string }[] } }> };
    const images = await fillResponse.json() as { meta: { images: Record<string, string> } };
    for (const layer of fills) {
      const fill = nodes.nodes[layer.nodeId]?.document.fills.find((entry) => entry.type === "IMAGE");
      const url = fill?.imageRef ? images.meta.images[fill.imageRef] : undefined;
      if (!url || fill?.scaleMode !== "FILL") throw new Error(`Missing centered Player image fill for ${layer.nodeId}.`);
      const response = await fetch(url);
      if (!response.ok) throw new Error("Player artwork download failed.");
      const bytes = await sharp(Buffer.from(await response.arrayBuffer())).resize(Math.round(layer.box.width * dpr), Math.round(layer.box.height * dpr), { fit: "cover", position: "centre" }).png().toBuffer();
      const file = files[mediaArtKey(layer.nodeId, dpr)];
      if (!file) throw new Error("Missing Player artwork cache path.");
      await writeFile(file, bytes);
      downloaded++;
    }
  }
  const exports = missing.filter((layer) => !layer.imageFill);
  if (exports.length === 0) continue;
  const params = new URLSearchParams({ ids: exports.map((layer) => layer.nodeId).join(","), version: set.set.figmaVersionId, scale: String(dpr), format: "png", use_absolute_bounds: "true" });
  const response = await fetch(`https://api.figma.com/v1/images/${set.set.figmaFileKey}?${params}`, { headers: { "X-Figma-Token": token } });
  if (!response.ok) throw new Error(`Figma artwork GET failed (${String(response.status)}).`);
  const body = await response.json() as { images: Record<string, string | null> };
  // Bounded downloads; never log private URLs or request headers.
  let next = 0;
  await Promise.all(Array.from({ length: 4 }, async () => {
    while (next < exports.length) {
      const layer = exports[next++];
      if (!layer) continue;
      const url = body.images[layer.nodeId];
      if (!url) throw new Error(`No artwork export for ${layer.nodeId}.`);
      const image = await fetch(url);
      if (!image.ok) throw new Error(`Artwork download failed (${String(image.status)}).`);
      const bytes = Buffer.from(await image.arrayBuffer());
      const metadata = await sharp(bytes).metadata();
      if (metadata.width !== Math.round(layer.box.width * dpr) || metadata.height !== Math.round(layer.box.height * dpr)) throw new Error(`Artwork dimensions differ for ${layer.nodeId}.`);
      const file = files[mediaArtKey(layer.nodeId, dpr)];
      if (!file) throw new Error(`Missing artwork cache path for ${layer.nodeId}.`);
      await writeFile(file, bytes);
      downloaded++;
    }
  }));
}
await writeFile(MEDIA_ART_MANIFEST, JSON.stringify(files));
console.log(`fidelity: ${String(Object.keys(files).length)} locked artwork-only layers cached (${String(downloaded)} downloaded); reference set unchanged.`);
