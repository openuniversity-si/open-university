import type { Queryable } from "../../platform/db/uow.ts";

export async function activeCourseCovers(db: Queryable, courseId: string) {
  return db.query("SELECT kind, variant, version, url, width, height, sha256 FROM catalog_media WHERE owner_kind = 'course' AND owner_id = $1 AND is_active ORDER BY kind, variant", [courseId]);
}
export async function activeLessonCovers(db: Queryable, lessonIds: readonly string[]) {
  if (lessonIds.length === 0) return { rows: [] as Record<string, unknown>[] };
  return db.query("SELECT owner_id AS lesson_id, kind, variant, version, url FROM catalog_media WHERE owner_kind = 'lesson' AND owner_id = ANY($1) AND is_active ORDER BY owner_id, kind, variant", [lessonIds]);
}
/** Active asset kinds of every owner, or only of these courses and subareas (the catalog resolves which). */
export async function activeAssetRows(db: Queryable, owners?: { readonly courseIds: readonly string[]; readonly subareaIds: readonly string[]; readonly areaIds: readonly string[] }) {
  const [own, shared, areas] = await Promise.all(owners === undefined ? [
    db.query("SELECT owner_id, kind, variant FROM catalog_media WHERE owner_kind = 'course' AND is_active"),
    db.query("SELECT owner_id, kind, variant FROM catalog_media WHERE owner_kind = 'subarea' AND is_active"),
    db.query("SELECT owner_id, kind, variant FROM catalog_media WHERE owner_kind = 'area' AND is_active"),
  ] : [
    db.query("SELECT owner_id, kind, variant FROM catalog_media WHERE owner_kind = 'course' AND is_active AND owner_id = ANY($1)", [owners.courseIds]),
    db.query("SELECT owner_id, kind, variant FROM catalog_media WHERE owner_kind = 'subarea' AND is_active AND owner_id = ANY($1)", [owners.subareaIds]),
    db.query("SELECT owner_id, kind, variant FROM catalog_media WHERE owner_kind = 'area' AND is_active AND owner_id = ANY($1)", [owners.areaIds]),
  ]);
  return { own: own.rows, shared: shared.rows, areas: areas.rows };
}
/** One read of the active cover rows for a course page: course, subarea and area owners together. */
export async function activePageAssets(db: Queryable, owners: { readonly courseIds: readonly string[]; readonly subareaIds: readonly string[]; readonly areaIds: readonly string[] }) {
  return db.query(`SELECT owner_kind, owner_id, kind, variant FROM catalog_media
    WHERE is_active AND ((owner_kind = 'course' AND owner_id = ANY($1)) OR (owner_kind = 'subarea' AND owner_id = ANY($2)) OR (owner_kind = 'area' AND owner_id = ANY($3)))`,
  [owners.courseIds, owners.subareaIds, owners.areaIds]);
}

/** Every active subarea cover, one query. Owners with no row are absent. */
export async function activeSubareaCovers(db: Queryable) {
  const { rows } = await db.query("SELECT owner_id, kind, variant, sha256 FROM catalog_media WHERE owner_kind = 'subarea' AND is_active ORDER BY owner_id, kind, variant");
  const covers = new Map<string, { kind: string; variant: string; sha256: string }[]>();
  for (const row of rows) {
    const id = String(row.owner_id);
    const list = covers.get(id) ?? [];
    list.push({ kind: String(row.kind), variant: String(row.variant), sha256: String(row.sha256) });
    covers.set(id, list);
  }
  return covers;
}

export async function validateObject(db: Queryable, sha256: string): Promise<string | null> {
  return (await db.query("SELECT sha256 FROM media_objects WHERE sha256=$1", [sha256])).rows[0]?.sha256 as string | undefined ?? null;
}
