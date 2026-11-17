import type { GeometryBox } from "./compare.ts";
import type { FidelityFrame } from "./frames.ts";
import type { FidelityRegion } from "./regions.ts";
import type { LocalReferenceSet } from "./references/active.ts";

export interface ResolvedFrame {
  readonly frame: FidelityFrame;
  readonly referenceFile: string;
  readonly regions: readonly { readonly region: FidelityRegion; readonly referenceBox: GeometryBox }[];
}

/** Bind a registered frame to the active set's image and geometry; anything missing fails loudly. */
export function resolveFrame(frame: FidelityFrame, set: LocalReferenceSet): ResolvedFrame {
  const viewport = `${String(frame.viewport)}@${String(frame.dpr)}x`;
  const image = set.images.find((candidate) => candidate.nodeId === frame.figmaNodeId && candidate.viewport === viewport);
  const referenceFile = image ? set.files[image.screenKey] : undefined;
  if (!image || !referenceFile) {
    throw new Error(`Frame ${frame.id}: the active set (Figma ${set.set.figmaVersionId}) has no ${viewport} reference for node ${frame.figmaNodeId}.`);
  }
  if (frame.regions.length === 0) throw new Error(`Frame ${frame.id} has no comparison regions.`);
  return {
    frame,
    referenceFile,
    regions: frame.regions.map((region) => {
      const node = set.nodes.find((candidate) => candidate.rootNodeId === frame.figmaNodeId && (region.figmaChild
        ? candidate.name === region.figmaChild && candidate.nodeId.startsWith(`I${region.figmaNodeId};`) && candidate.nodeId.split(";").length === 2
        : candidate.nodeId === region.figmaNodeId));
      if (!node) throw new Error(`Frame ${frame.id}: node ${region.figmaNodeId} (${region.name}) is not under ${frame.figmaNodeId} in Figma ${set.set.figmaVersionId}.`);
      const padding = region.posterBox ? 2 : 0;
      return { region, referenceBox: { x: node.x, y: node.y + padding, width: node.width, height: node.height - padding } };
    }),
  };
}

export function framesForPhase(frames: readonly FidelityFrame[], phase: string | undefined): readonly FidelityFrame[] {
  if (phase !== undefined && !/^F\d{2}$/.test(phase)) throw new Error("Use --phase FNN, e.g. --phase F05.");
  const ids = new Set<string>();
  for (const frame of frames) {
    if (ids.has(frame.id)) throw new Error(`Duplicate fidelity frame id ${frame.id}.`);
    ids.add(frame.id);
  }
  return phase === undefined ? frames : frames.filter((frame) => frame.phase === phase || frame.gates?.includes(phase));
}
