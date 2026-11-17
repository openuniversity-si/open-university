import type { Queryable } from "../../platform/db/uow.ts";

async function sampled(db: Queryable, sql: string, values: unknown[] = []): Promise<{ count: number; sample: unknown[] }> {
  const { rows } = await db.query(sql, values);
  return { count: rows.length, sample: rows.slice(0, 10).map((row) => (Object.keys(row).length === 1 ? Object.values(row)[0] : row)) };
}

/** Media-owned integrity. Catalog ids and cover descriptors arrive as data; this module never reads catalog tables. */
export async function diagnoseMedia(db: Queryable, catalog: { readonly courseIds: readonly string[]; readonly lessonIds: readonly string[]; readonly covers: readonly { readonly id: string; readonly table: string; readonly sha256: string | null; readonly width: number | null; readonly height: number | null; readonly url: string | null }[] }): Promise<{ code: string; count: number; sample: unknown[] }[]> {
  const findings: { code: string; count: number; sample: unknown[] }[] = [];
  const hashes = catalog.covers.map((cover) => cover.sha256).filter((hash): hash is string => typeof hash === "string" && hash !== "");
  const [orphans, missing, objectRows, pending] = await Promise.all([
    sampled(db, `SELECT owner_kind || ':' || owner_id || '/' || kind || '/' || variant || '@' || version AS ref FROM catalog_media a
    WHERE (a.owner_kind = 'course' AND NOT (a.owner_id = ANY($1))) OR (a.owner_kind = 'lesson' AND NOT (a.owner_id = ANY($2))) ORDER BY 1`, [catalog.courseIds, catalog.lessonIds]),
    sampled(db, `SELECT a.id AS ref FROM catalog_media a LEFT JOIN media_objects o ON o.sha256=a.media_sha256 WHERE (a.media_sha256 IS NOT NULL OR a.pathname LIKE 'm/%') AND (o.sha256 IS NULL OR o.sha256<>a.sha256 OR o.width<>a.width OR o.height<>a.height)`),
    hashes.length === 0 ? Promise.resolve([] as Record<string, unknown>[]) : db.query("SELECT sha256, width, height FROM media_objects WHERE sha256 = ANY($1)", [hashes]).then(({ rows }) => rows),
    sampled(db, "SELECT key || ' (' || owner_kind || ':' || owner_id || ', ' || attempts || ' attempt(s))' AS ref FROM r2_pending_deletions ORDER BY created_at, key"),
  ]);
  if (orphans.count > 0) findings.push({ code: "assets.orphan", ...orphans });
  if (missing.count > 0) findings.push({ code: "media.registry.catalog_media.missing", ...missing });
  const objects = new Map(objectRows.map((row) => [String(row.sha256), row]));
  for (const coverTable of ["authors", "home_rows"] as const) {
    const broken = catalog.covers.filter((cover) => cover.table === coverTable).filter((cover) => {
      const addressed = cover.sha256 !== null || (cover.url ?? "").includes("/m/");
      if (!addressed) return false;
      const object = cover.sha256 ? objects.get(cover.sha256) : undefined;
      return !object || Number(object.width) !== cover.width || Number(object.height) !== cover.height;
    }).map((cover) => cover.id);
    if (broken.length > 0) findings.push({ code: "media.registry." + coverTable + ".missing", count: broken.length, sample: broken.slice(0, 10) });
  }
  if (pending.count > 0) findings.push({ code: "r2.pending", ...pending });
  return findings;
}
