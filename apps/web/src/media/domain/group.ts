import type { MediaAsset, MediaKind } from "./types.ts";

/** Assets by owner id; the Data Cache stores arrays (JSON), so grouping happens after the read. */
export function groupByOwner(assets: readonly MediaAsset[]): ReadonlyMap<string, readonly MediaAsset[]> {
  const groups = new Map<string, MediaAsset[]>();
  for (const asset of assets) groups.set(asset.ownerId, [...(groups.get(asset.ownerId) ?? []), asset]);
  return groups;
}

/** The stored asset of one kind and variant. The cover decision is not made here. */
export function pickAsset(assets: readonly MediaAsset[] | undefined, kind: MediaKind, variant = "default"): MediaAsset | undefined {
  return assets?.find((asset) => asset.isActive && asset.kind === kind && asset.variant === variant);
}

