import type { Queryable } from "../../platform/db/uow.ts";

/** One declared cover, already resolved to a registered object. The catalog adapter does not write this table. */
export interface CoverAttachRow {
  readonly owner_kind: string;
  readonly owner_id: string;
  readonly kind: string;
  readonly variant: string;
  readonly url: string;
  readonly pathname: string;
  readonly width: number;
  readonly height: number;
  readonly sha256: string;
  readonly alt: string;
  readonly media_sha256: string;
}

const COLUMNS = "owner_kind text, owner_id text, kind text, variant text, url text, pathname text, width int, height int, sha256 text, alt text, media_sha256 text";

/**
 * Every declared cover in two statements (D-035). Deactivate and insert cannot share one
 * statement: Postgres reads both sides of a CTE from the same snapshot, and the partial
 * unique index allows one active row. An unchanged active row is left in place.
 */
export async function attachCoverSet(db: Queryable, rows: readonly CoverAttachRow[]): Promise<void> {
  if (rows.length === 0) return;
  const payload = JSON.stringify(rows);
  await db.query(`UPDATE catalog_media AS a SET is_active = false, updated_at = now()
    FROM jsonb_to_recordset($1::jsonb) AS i(${COLUMNS})
    WHERE a.owner_kind = i.owner_kind AND a.owner_id = i.owner_id AND a.kind = i.kind AND a.variant = i.variant AND a.is_active
      AND (a.sha256 IS DISTINCT FROM i.sha256 OR a.url IS DISTINCT FROM i.url OR a.width IS DISTINCT FROM i.width
        OR a.height IS DISTINCT FROM i.height OR a.alt IS DISTINCT FROM i.alt OR a.design_status IS DISTINCT FROM 'approved' OR a.transform IS NOT NULL)`, [payload]);
  await db.query(`INSERT INTO catalog_media (id, owner_kind, owner_id, kind, variant, url, pathname, width, height, sha256, alt, transform, design_status, version, media_sha256, is_active)
    SELECT gen_random_uuid()::text, i.owner_kind, i.owner_id, i.kind, i.variant, i.url, i.pathname, i.width, i.height, i.sha256, i.alt, NULL, 'approved',
      coalesce((SELECT max(a.version) FROM catalog_media a WHERE a.owner_kind = i.owner_kind AND a.owner_id = i.owner_id AND a.kind = i.kind AND a.variant = i.variant), 0) + 1,
      i.media_sha256, true
    FROM jsonb_to_recordset($1::jsonb) AS i(${COLUMNS})
    WHERE NOT EXISTS (
      SELECT 1 FROM catalog_media a
      WHERE a.owner_kind = i.owner_kind AND a.owner_id = i.owner_id AND a.kind = i.kind AND a.variant = i.variant AND a.is_active
        AND a.sha256 = i.sha256 AND a.url = i.url AND a.width = i.width AND a.height = i.height AND a.alt = i.alt
        AND a.design_status = 'approved' AND a.transform IS NULL)`, [payload]);
}
