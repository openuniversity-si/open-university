import "server-only";
import { activeAssetRows, activeCourseCovers, activeLessonCovers, activePageAssets, activeSubareaCovers, validateObject } from "../../media/server/asset-reads.ts";
import { diagnoseMedia } from "../../media/server/diagnose.ts";
import { readLessonAssets, readPublicOwnerAssets } from "../../media/server/index.ts";
import { coverGraph, redundantLessons } from "../../media/server/inheritance.ts";
import { syncInstitutionCover } from "../../media/server/institution-cover.ts";
import { lockMediaOwners } from "../../media/server/media-locks.ts";
import { readObjects } from "../../media/server/objects.ts";
import { countPending, drainPendingObjects, heldForRetention, pendingKeys, queuePending, usedMediaKeys } from "../../media/server/pending-deletions.ts";
import { attachCoverSet } from "../../media/server/attach-set.ts";
import { clearOrphanedMany } from "../../media/server/lifecycle.ts";
import { activeCoverKinds, deleteOwnedMedia, ownedMedia } from "../../media/server/repository.ts";

/**
 * Catalog server reaches media server only through here.
 * `catalog/server/deps.ts` and `admin/deps.ts` publish the same object.
 */
export const catalogMediaGateway = {
  readObjects, readPublicOwnerAssets, readLessonAssets, activeSubareaCovers, activeAssetRows, activePageAssets, coverGraph, redundantLessons, diagnoseMedia, syncInstitutionCover, validateObject, activeCourseCovers, activeLessonCovers, lockMediaOwners,
  countPending, drainPendingObjects, heldForRetention, pendingKeys, queuePending, usedMediaKeys, deleteOwnedMedia, ownedMedia, activeCoverKinds, attachCoverSet, clearOrphanedMany,
};

export { activeAssetRows, activeCourseCovers, activeCoverKinds, activeLessonCovers, activePageAssets, activeSubareaCovers, attachCoverSet, clearOrphanedMany, countPending, coverGraph, deleteOwnedMedia, diagnoseMedia, drainPendingObjects, heldForRetention, lockMediaOwners, ownedMedia, pendingKeys, queuePending, readLessonAssets, readObjects, readPublicOwnerAssets, redundantLessons, syncInstitutionCover, usedMediaKeys, validateObject };
export type { CoverAttachRow } from "../../media/server/attach-set.ts";
export type { OwnedMediaRow } from "../../media/server/repository.ts";
