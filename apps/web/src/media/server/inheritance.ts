import type { CatalogOwnersPort, OwnerGraph } from "../ports/owner.ts";
import { groupByOwner } from "../domain/group.ts";
import { redundantLessons } from "../../catalog/domain/cover-resolve.ts";
import { joinTransaction, listOwnerMedia, type MediaDatabase, type MediaPool } from "./repository.ts";
import type { UnitOfWork } from "../../platform/db/uow.ts";

export { inheritedSources } from "../domain/inheritance.ts";
export { redundantLessons };

/** Actual rows only: shared covers are never materialized once per inherited course. Catalog rows arrive as a snapshot. */
export async function coverGraph(db: MediaDatabase, owners: OwnerGraph) {
  const [courseAssets, lessonAssets, subareaAssets, areaAssets] = await Promise.all([
    listOwnerMedia(db, "course"), listOwnerMedia(db, "lesson"), listOwnerMedia(db, "subarea"), listOwnerMedia(db, "area"),
  ]);
  return { courses: owners.courses, lessons: owners.lessons,
    areaAssets: groupByOwner(areaAssets), courseAssets: groupByOwner(courseAssets), subareaAssets: groupByOwner(subareaAssets), lessonAssets,
  };
}

/** Recompute under write locks: a concurrent cover swap/classification cannot change the fallback between plan and delete. */
export async function pruneInherited(pool: MediaPool | UnitOfWork, apply: boolean, openOwners: (db: UnitOfWork) => CatalogOwnersPort) {
  return joinTransaction(pool, async (db) => {
    const owners = openOwners(db);
    if (apply) {
      await owners.lockGraph();
      await db.acquireLock({ scope: "media-maintenance", mode: "exclusive" });
    }
    const candidates = redundantLessons(await coverGraph(db, await owners.graph()));
    const ids = candidates.map(({ asset }) => asset.id);
    if (apply && ids.length) await db.query("DELETE FROM catalog_media WHERE owner_kind = 'lesson' AND id = ANY($1::text[])", [ids]);
    return { apply, count: candidates.length, bytesDeleted: 0, candidates, courseIds: [...new Set(candidates.map(({ courseId }) => courseId))] };
  });
}
