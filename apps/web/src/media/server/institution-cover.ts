import type { UnitOfWork } from "../../platform/db/uow.ts";
import { validateObject } from "./asset-reads.ts";
import { swapMedia } from "./repository.ts";

interface Cover { readonly url: string; readonly width: number; readonly height: number; readonly sha256: string; readonly alt: string; readonly mediaSha256?: string | undefined }
/** The catalog journal's cover descriptors and their active attachments change in the same transaction. */
export async function syncInstitutionCover(tx: UnitOfWork, ownerId: string, kind: "author_cover_9x16" | "university_cover_9x16" | "poster_9x16", cover: Cover | null): Promise<void> {
  if (!cover) {
    await tx.query("UPDATE catalog_media SET is_active = false, updated_at = now() WHERE owner_kind = 'institution' AND owner_id = $1 AND kind = $2 AND variant = 'default' AND is_active", [ownerId, kind]);
    return;
  }
  const mediaSha256 = cover.mediaSha256 ?? await validateObject(tx, cover.sha256);
  await swapMedia(tx, "institution", {
    ownerId, kind, variant: "default", url: cover.url, pathname: new URL(cover.url).pathname.slice(1), width: cover.width, height: cover.height,
    sha256: cover.sha256, mediaSha256, alt: cover.alt, transform: null, designStatus: "approved",
  });
}
