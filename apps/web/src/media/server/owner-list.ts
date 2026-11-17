import type { Queryable } from "../../platform/db/uow.ts";
import type { MediaAsset, MediaOwner } from "../domain/types.ts";
import { listMediaByOwners } from "./repository.ts";

/** One call for many owners. An owner with no rows is an empty `versions` list, not a missing owner. */
export async function readOwnerList(
  db: Queryable,
  owners: readonly { readonly owner: MediaOwner; readonly ownerId: string }[],
  filter: { readonly activeOnly: boolean; readonly kind?: string; readonly variant?: string },
) {
  const groups = await listMediaByOwners(db, owners, filter);
  return {
    owners: groups.map((group) => ({
      owner: group.owner,
      ownerId: group.ownerId,
      versions: group.assets.map(versionView),
    })),
  };
}

function versionView(asset: MediaAsset) {
  return {
    ownerId: asset.ownerId, kind: asset.kind, variant: asset.variant, version: asset.version, url: asset.url,
    width: asset.width, height: asset.height, sha256: asset.sha256, active: asset.isActive, alt: asset.alt,
    designStatus: asset.designStatus, createdAt: asset.createdAt.toISOString(),
  };
}
