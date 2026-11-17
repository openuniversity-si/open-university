import "server-only";
import { remember } from "../../platform/freshness/next.ts";
import { appPool as database } from "../../platform/db/pool.ts";
import { listPublicMediaRows, readActiveLessonMedia, type PublicMediaRow } from "./repository.ts";
import { areaMediaTag, COURSE_LIST_MEDIA_TAG, courseMediaTag, MEDIA_TAG, subareaMediaTag } from "../domain/tags.ts";
import { CACHE } from "../../kernel/cache.ts";
import { sha256Hex } from "../../kernel/canonical.ts";
import { assertCacheEntry, loadWithinBudget } from "../../kernel/cache-budget.ts";
import { buildWithoutDatabase } from "../../platform/db/database-env.ts";
import { type MediaAsset, type MediaOwner } from "../domain/types.ts";

export { database };
const noDatabase = () => buildWithoutDatabase();

export interface PublicOwnerRef { readonly owner: MediaOwner; readonly ownerId: string }

function mediaTag(owner: MediaOwner, ownerId: string): string {
  if (owner === "subarea") return subareaMediaTag(ownerId);
  if (owner === "area") return areaMediaTag(ownerId);
  return courseMediaTag(ownerId);
}

function uniqueOwners(owners: readonly PublicOwnerRef[]): PublicOwnerRef[] {
  const seen = new Set<string>();
  return owners.filter((owner) => {
    const key = `${owner.owner}:${owner.ownerId}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/** The fields the cards paint. Admin columns stay out of the Data Cache. */
function expandPublicRow(row: PublicMediaRow): MediaAsset {
  return {
    id: row.sha256, ownerId: row.ownerId, kind: row.kind as MediaAsset["kind"], variant: row.variant, url: row.url,
    pathname: `m/${row.sha256}.webp`, width: row.width, height: row.height, sha256: row.sha256, alt: row.alt,
    transform: row.transform, designStatus: "approved", version: 1, isActive: row.isActive, createdAt: new Date(0), updatedAt: new Date(0),
  };
}

/** One batched read for this call, stored in chunks under the cache budget. Each chunk carries the list tag and its owners. */
async function cachedPublicRows(owners: readonly PublicOwnerRef[]): Promise<PublicMediaRow[]> {
  if (owners.length === 0) return [];
  let pending: Promise<PublicMediaRow[]> | undefined;
  const readAll = () => (pending ??= listPublicMediaRows(database(), owners));
  const parts = await loadWithinBudget(owners, (slice) => {
    const hash = sha256Hex(slice.map((owner) => `${owner.owner}:${owner.ownerId}`).join("\n"));
    const tags = [MEDIA_TAG, COURSE_LIST_MEDIA_TAG, ...slice.map((owner) => mediaTag(owner.owner, owner.ownerId))];
    return remember(async () => {
      const loaded = await readAll();
      const wanted = new Set(slice.map((owner) => `${owner.owner}:${owner.ownerId}`));
      const rows = loaded.filter((row) => wanted.has(`${row.ownerKind}:${row.ownerId}`));
      assertCacheEntry(rows);
      return rows;
    }, ["media", "public", hash], { tags, revalidate: CACHE.mediaReadSeconds })();
  });
  return parts.flat();
}

/** Cached public rows for owners the catalog already named. This read does not choose a cover. */
export async function readPublicOwnerAssets(owners: readonly PublicOwnerRef[]): Promise<{ owner: MediaOwner; asset: MediaAsset }[]> {
  if (owners.length === 0 || noDatabase()) return [];
  const rows = await cachedPublicRows(uniqueOwners(owners));
  return rows.map((row) => ({ owner: row.ownerKind as MediaOwner, asset: expandPublicRow(row) }));
}

/** One cached array of actual lesson rows. The declared owner's frame is not chosen here. */
export async function readLessonAssets(courseId: string, lessonIds: readonly string[]): Promise<MediaAsset[]> {
  if (noDatabase()) return [];
  return remember(() => readActiveLessonMedia(database(), lessonIds), ["media", "lesson", courseId], { tags: [MEDIA_TAG, courseMediaTag(courseId)], revalidate: CACHE.mediaReadSeconds })();
}
