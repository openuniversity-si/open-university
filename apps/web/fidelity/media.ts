import type { GeometryBox } from "./compare.ts";
import type { FidelityFrame } from "./frames.ts";
import type { LocalReferenceSet } from "./references/active.ts";

export const MEDIA_ART_MANIFEST = ".reports/fidelity/media-art.json";

export interface ReferenceMediaLayer {
  readonly nodeId: string;
  readonly selector: string;
  readonly box: GeometryBox;
  readonly kind: "hero" | "poster" | "thumbnail";
  /** PlayerFrame owns its image fill; export that raster alone, without its children. */
  readonly imageFill?: boolean;
}

/** Artwork-only nodes from the SAME locked set. Never export glass, scrims or text as artwork. */
export function referenceMediaLayers(frame: FidelityFrame, set: LocalReferenceSet): readonly ReferenceMediaLayer[] {
  if (frame.phase === "F08" || (frame.phase === "F11" && frame.id.startsWith("player-"))) {
    const nodes = set.nodes.filter((node) => node.rootNodeId === frame.figmaNodeId);
    const poster = nodes.find((node) => node.name.startsWith("PlayerFrame ("));
    if (!poster) throw new Error(`Missing locked Player poster for ${frame.id}.`);
    const layers: ReferenceMediaLayer[] = [{ nodeId: poster.nodeId, selector: '[data-testid="player-poster"] img', box: poster, kind: "poster", imageFill: true }];
    const thumbs = nodes.filter((node) => node.name === "Thumb");
    const rail = nodes.find((node) => node.name.startsWith("PlaylistPanel"));
    if (!rail) throw new Error(`Missing locked Player rail for ${frame.id}.`);
    for (const [index, thumb] of thumbs.filter((node) => node.y < rail.y + rail.height).entries()) {
      layers.push({ nodeId: thumb.nodeId, selector: `[data-testid^="playlist-item-"]:nth-child(${String(index + 1)}) [data-testid="playlist-thumb"] img`, box: thumb, kind: "thumbnail", imageFill: true });
    }
    return layers;
  }
  // F05's Home TopNav captures also composite over this mutable hero. Footer fixtures have
  // no media; account-menu references are standalone panels on the solid surface.
  if (frame.phase !== "F11" && frame.phase !== "F10" && frame.phase !== "F07" && frame.phase !== "F06" && !(frame.phase === "F05" && frame.capture === "viewport")) return [];
  if (frame.regions.every((region) => region.name === "AccountMenu")) return [];
  const nodes = set.nodes.filter((node) => node.rootNodeId === frame.figmaNodeId);
  const layers: ReferenceMediaLayer[] = [];
  const hero = nodes.find((node) => node.name === "Image (16:9 still)");
  if (!hero) {
    if (frame.phase === "F10" && frame.authState === "continuing") return [];
    throw new Error(`Missing locked hero artwork node for ${frame.id}.`);
  }
  layers.push({ nodeId: hero.nodeId, selector: '[data-testid="tower-billboard"] img', box: hero, kind: "hero" });
  for (const region of frame.regions.filter((region) => region.posterBox)) {
    const image = nodes.find((node) => node.name === "Image" && node.nodeId.startsWith(`I${region.figmaNodeId};`));
    if (!image) throw new Error(`Missing locked poster artwork node for ${frame.id}/${region.name}.`);
    layers.push({ nodeId: image.nodeId, selector: `${region.selector} img`, box: image, kind: "poster" });
  }
  for (const region of frame.regions.filter((region) => region.figmaChild === "Cover 9:16")) {
    const image = nodes.find((node) => node.name === "Image" && node.nodeId.startsWith(`I${region.figmaNodeId};`));
    if (!image) throw new Error(`Missing locked Continue artwork node for ${frame.id}/${region.name}.`);
    layers.push({ nodeId: image.nodeId, selector: `${region.selector} img`, box: image, kind: "poster" });
  }
  if (frame.phase === "F11" && frame.id.startsWith("course-content-")) {
    // Watched, Current and default rows each own a Thumb (image fill only), in list order.
    const thumbs = nodes.filter((node) => node.name === "Thumb").sort((a, b) => a.y - b.y);
    for (const [index, thumb] of (frame.viewport === 390 ? thumbs : thumbs.slice(0, 9)).entries()) layers.push({ nodeId: thumb.nodeId, selector: `[data-testid^="playlist-item-"]:nth-child(${String(index + 1)}) [data-testid="playlist-thumb"] img`, box: thumb, kind: "thumbnail" });
  }
  if (frame.phase === "F07" && frame.capture === "fullPage") {
    // The Thumb node is an image fill only; export no playlist text or selection chrome.
    const thumbs = nodes.filter((node) => node.name === "Thumb" && node.nodeId.endsWith(";39:45"));
    const visible = frame.viewport === 390 ? thumbs : thumbs.slice(0, 9);
    for (const [index, thumb] of visible.entries()) layers.push({ nodeId: thumb.nodeId, selector: `[data-testid^="playlist-item-"]:nth-child(${String(index + 1)}) [data-testid="playlist-thumb"] img`, box: thumb, kind: "thumbnail" });
  }
  return layers;
}

export const mediaArtKey = (nodeId: string, dpr: number) => `${nodeId}@${String(dpr)}x`;
