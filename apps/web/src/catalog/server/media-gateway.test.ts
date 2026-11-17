import { describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

import { activeAssetRows as serverActiveAssetRows, activeCourseCovers as serverActiveCourseCovers, activeLessonCovers as serverActiveLessonCovers, activePageAssets as serverActivePageAssets, activeSubareaCovers as serverActiveSubareaCovers, validateObject as serverValidateObject } from "../../media/server/asset-reads.ts";
import { diagnoseMedia as serverDiagnoseMedia } from "../../media/server/diagnose.ts";
import { coverGraph as serverCoverGraph, redundantLessons as serverRedundantLessons } from "../../media/server/inheritance.ts";
import { syncInstitutionCover as serverSyncInstitutionCover } from "../../media/server/institution-cover.ts";
import { lockMediaOwners as serverLockMediaOwners } from "../../media/server/media-locks.ts";
import { countPending as serverCountPending, drainPendingObjects as serverDrainPendingObjects, heldForRetention as serverHeldForRetention, pendingKeys as serverPendingKeys, queuePending as serverQueuePending, usedMediaKeys as serverUsedMediaKeys } from "../../media/server/pending-deletions.ts";
import { attachCoverSet as serverAttachCoverSet } from "../../media/server/attach-set.ts";
import { clearOrphanedMany as serverClearOrphanedMany } from "../../media/server/lifecycle.ts";
import { activeCoverKinds as serverActiveCoverKinds, deleteOwnedMedia as serverDeleteOwnedMedia, ownedMedia as serverOwnedMedia } from "../../media/server/repository.ts";
import { readLessonAssets as serverReadLessonAssets, readPublicOwnerAssets as serverReadPublicOwnerAssets } from "../../media/server/index.ts";
import { readObjects as serverReadObjects } from "../../media/server/objects.ts";
import { activeAssetRows, activeCourseCovers, activeCoverKinds, activeLessonCovers, activePageAssets, activeSubareaCovers, attachCoverSet, catalogMediaGateway, clearOrphanedMany, countPending, coverGraph, deleteOwnedMedia, diagnoseMedia, drainPendingObjects, heldForRetention, lockMediaOwners, ownedMedia, pendingKeys, queuePending, readLessonAssets, readObjects, readPublicOwnerAssets, redundantLessons, syncInstitutionCover, usedMediaKeys, validateObject } from "./media-gateway.ts";

describe("catalog media gateway", () => {
  it("publishes the media server object reader", () => {
    expect(readObjects).toBe(serverReadObjects);
    expect(catalogMediaGateway.readObjects).toBe(serverReadObjects);
  });

  it("publishes the owner and lesson row reads", () => {
    expect(readPublicOwnerAssets).toBe(serverReadPublicOwnerAssets);
    expect(readLessonAssets).toBe(serverReadLessonAssets);
    expect(catalogMediaGateway.readPublicOwnerAssets).toBe(serverReadPublicOwnerAssets);
    expect(catalogMediaGateway.readLessonAssets).toBe(serverReadLessonAssets);
  });

  it("publishes the active subarea cover reader", () => {
    expect(activeSubareaCovers).toBe(serverActiveSubareaCovers);
    expect(catalogMediaGateway.activeSubareaCovers).toBe(serverActiveSubareaCovers);
  });

  it("publishes the active asset readers", () => {
    expect(activeAssetRows).toBe(serverActiveAssetRows);
    expect(activePageAssets).toBe(serverActivePageAssets);
    expect(catalogMediaGateway.activeAssetRows).toBe(serverActiveAssetRows);
    expect(catalogMediaGateway.activePageAssets).toBe(serverActivePageAssets);
  });

  it("publishes the doctor media reads", () => {
    expect(coverGraph).toBe(serverCoverGraph);
    expect(redundantLessons).toBe(serverRedundantLessons);
    expect(diagnoseMedia).toBe(serverDiagnoseMedia);
    expect(catalogMediaGateway.coverGraph).toBe(serverCoverGraph);
    expect(catalogMediaGateway.redundantLessons).toBe(serverRedundantLessons);
    expect(catalogMediaGateway.diagnoseMedia).toBe(serverDiagnoseMedia);
  });

  it("publishes the institution cover writer", () => {
    expect(syncInstitutionCover).toBe(serverSyncInstitutionCover);
    expect(catalogMediaGateway.syncInstitutionCover).toBe(serverSyncInstitutionCover);
  });

  it("publishes the object validator", () => {
    expect(validateObject).toBe(serverValidateObject);
    expect(catalogMediaGateway.validateObject).toBe(serverValidateObject);
  });

  it("publishes course cover reads and the media lock", () => {
    expect(activeCourseCovers).toBe(serverActiveCourseCovers);
    expect(activeLessonCovers).toBe(serverActiveLessonCovers);
    expect(lockMediaOwners).toBe(serverLockMediaOwners);
    expect(catalogMediaGateway.activeCourseCovers).toBe(serverActiveCourseCovers);
    expect(catalogMediaGateway.activeLessonCovers).toBe(serverActiveLessonCovers);
    expect(catalogMediaGateway.lockMediaOwners).toBe(serverLockMediaOwners);
  });

  it("publishes owned-media deletion", () => {
    expect(countPending).toBe(serverCountPending);
    expect(drainPendingObjects).toBe(serverDrainPendingObjects);
    expect(heldForRetention).toBe(serverHeldForRetention);
    expect(pendingKeys).toBe(serverPendingKeys);
    expect(queuePending).toBe(serverQueuePending);
    expect(usedMediaKeys).toBe(serverUsedMediaKeys);
    expect(deleteOwnedMedia).toBe(serverDeleteOwnedMedia);
    expect(ownedMedia).toBe(serverOwnedMedia);
    expect(catalogMediaGateway.deleteOwnedMedia).toBe(serverDeleteOwnedMedia);
    expect(catalogMediaGateway.ownedMedia).toBe(serverOwnedMedia);
  });

  it("publishes batch cover writes", () => {
    expect(activeCoverKinds).toBe(serverActiveCoverKinds);
    expect(attachCoverSet).toBe(serverAttachCoverSet);
    expect(clearOrphanedMany).toBe(serverClearOrphanedMany);
    expect(catalogMediaGateway.activeCoverKinds).toBe(serverActiveCoverKinds);
    expect(catalogMediaGateway.attachCoverSet).toBe(serverAttachCoverSet);
    expect(catalogMediaGateway.clearOrphanedMany).toBe(serverClearOrphanedMany);
  });
});
