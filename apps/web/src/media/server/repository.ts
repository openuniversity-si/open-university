import { withUnitOfWork, type DbPool, type PooledClient, type Queryable, type UnitOfWork } from "../../platform/db/uow.ts";
import { AppError } from "../../kernel/errors.ts";
import { randomUUID } from "node:crypto";
import { currentEnv } from "../../kernel/env.ts";
import { assetSchema, mediaKey, ownerIdSchema, type AssetInput, type MediaAsset, type MediaOwner } from "../domain/types.ts";
import { mediaPublicHost } from "./public-hosts.ts";
import { clearOrphaned } from "./lifecycle.ts";

/** The deletion would remove an active version or the default variant; nothing was changed. */
export class MediaConflictError extends AppError {
  constructor(message: string) { super("state_conflict", message); this.name = "MediaConflictError"; }
}

export type MediaDatabase = Queryable;
export type MediaClient = PooledClient;
export type MediaPool = DbPool;

export const inTransaction = withUnitOfWork;

export function isParticipant(db: MediaPool | UnitOfWork): db is UnitOfWork {
  return "acquireLock" in db && "onAfterCommit" in db && !("connect" in db);
}

/** Use the caller's open transaction when the journal already started one. */
export function joinTransaction<T>(db: MediaPool | UnitOfWork, work: (tx: UnitOfWork) => Promise<T>): Promise<T> {
  if (isParticipant(db)) return work(db);
  return withUnitOfWork(db, work);
}

/** Maintenance shared, then the owner, then the legacy per-variant key. Table locks are not used. */
function lockedTransaction<T>(pool: MediaPool | UnitOfWork, owner: MediaOwner, ownerId: string, lock: string, work: (tx: MediaDatabase) => Promise<T>): Promise<T> {
  return joinTransaction(pool, async (tx) => {
    await tx.acquireLock({ scope: "media-maintenance", mode: "shared" });
    await tx.acquireLock({ scope: "media-owner", owner, ownerId });
    await tx.acquireLock({ scope: "xact", key: lock });
    return work(tx);
  });
}
function assetSelect(column: string, alias = "a") {
  const host = mediaPublicHost(currentEnv());
  return `${alias}.id, ${alias}.${column} AS "ownerId", ${alias}.kind, ${alias}.variant, CASE WHEN ${alias}.media_sha256 IS NULL THEN ${alias}.url ELSE 'https://${host}/m/' || ${alias}.media_sha256 || '.' || mo.ext END AS url,
    CASE WHEN ${alias}.media_sha256 IS NULL THEN ${alias}.pathname ELSE 'm/' || ${alias}.media_sha256 || '.' || mo.ext END AS pathname,
    ${alias}.width, ${alias}.height, COALESCE(${alias}.media_sha256, ${alias}.sha256) AS sha256, ${alias}.media_sha256 AS "mediaSha256", ${alias}.alt, ${alias}.transform,
    ${alias}.design_status AS "designStatus", ${alias}.version, ${alias}.is_active AS "isActive", ${alias}.created_at AS "createdAt", ${alias}.updated_at AS "updatedAt"`;
}
function assetFrom(table: string, alias = "a") {
  return `FROM ${table} ${alias} LEFT JOIN media_objects mo ON mo.sha256 = ${alias}.media_sha256`;
}
export async function readActiveMedia(db: MediaDatabase, owner: MediaOwner, ownerId: string): Promise<MediaAsset[]> {
  const key = mediaKey(owner, ownerId, owner === "lesson" ? "cover_16x9" : "poster_9x16");
  const result = await db.query(`SELECT ${assetSelect(key.column)} ${assetFrom(key.table)} WHERE a.owner_kind='${key.owner}' AND a.${key.column}=$1 AND a.is_active ORDER BY a.kind, a.variant`, [ownerId]);
  return result.rows.map((row) => assetSchema.parse(row));
}
/** Every active course asset in one query (Home, course page): the caller groups them by `ownerId`. */
export async function readActiveCourseMedia(db: MediaDatabase): Promise<MediaAsset[]> {
  const result = await db.query(`SELECT ${assetSelect("owner_id")} ${assetFrom("catalog_media")} WHERE a.owner_kind='course' AND a.is_active ORDER BY a.owner_id, a.kind, a.variant`);
  return result.rows.map((row) => assetSchema.parse(row));
}
/** Shared descriptors are cached once per subarea; inherited courses never add rows to that cache. */
export async function readActiveSubareaMedia(db: MediaDatabase, subareaId: string): Promise<MediaAsset[]> {
  return readActiveMedia(db, "subarea", subareaId);
}
/** The active assets of one course's lessons in one query (course page, player). */
export async function readActiveLessonMedia(db: MediaDatabase, lessonIds: readonly string[]): Promise<MediaAsset[]> {
  lessonIds.forEach((id) => ownerIdSchema.parse(id));
  if (lessonIds.length === 0) return [];
  const result = await db.query(`SELECT ${assetSelect("owner_id")} ${assetFrom("catalog_media")}
    WHERE a.owner_kind='lesson' AND a.owner_id = ANY($1) AND a.is_active ORDER BY a.owner_id, a.kind, a.variant`, [lessonIds]);
  return result.rows.map((row) => assetSchema.parse(row));
}
/** Active default cover kinds for areas, subareas, and the courses in this batch. Catalog does not read catalog_media. */
export async function activeCoverKinds(db: MediaDatabase, courseIds: readonly string[]): Promise<Map<string, readonly string[]>> {
  const result = await db.query(`SELECT owner_kind || ':' || owner_id AS key, json_agg(DISTINCT kind) AS kinds
    FROM catalog_media
    WHERE is_active AND variant = 'default' AND owner_kind IN ('area', 'subarea', 'course')
      AND (owner_kind <> 'course' OR owner_id = ANY($1::text[]))
    GROUP BY owner_kind, owner_id`, [courseIds]);
  const covers = new Map<string, string[]>();
  for (const row of result.rows) {
    const key = typeof row.key === "string" ? row.key : "";
    const kinds = Array.isArray(row.kinds) ? row.kinds.filter((kind): kind is string => typeof kind === "string") : [];
    if (key) covers.set(key, kinds);
  }
  return covers;
}

export async function listOwnerMedia(db: MediaDatabase, owner: MediaOwner, activeOnly = false): Promise<MediaAsset[]> {
  const key = mediaKey(owner, "inventory", owner === "lesson" ? "cover_16x9" : "poster_9x16");
  const result = await db.query(`SELECT ${assetSelect(key.column)} ${assetFrom(key.table)} WHERE a.owner_kind='${key.owner}'${activeOnly ? " AND a.is_active" : ""} ORDER BY a.${key.column}, a.kind, a.variant, a.version DESC`);
  return result.rows.map((row) => assetSchema.parse(row));
}
async function listInventory(db: MediaDatabase, activeOnly: boolean): Promise<MediaAsset[]> {
  return (await Promise.all((["course", "lesson", "subarea", "area", "institution"] as const).map((owner) => listOwnerMedia(db, owner, activeOnly)))).flat();
}
export const listActiveMedia = (db: MediaDatabase) => listInventory(db, true);
/** Every row of both tables, inactive versions and non-default variants included. */
export const listAllMedia = (db: MediaDatabase) => listInventory(db, false);
/** Columns a public page paints. The Data Cache stores these rows, not the admin asset. */
export interface PublicMediaRow {
  readonly ownerKind: string;
  readonly ownerId: string;
  readonly kind: string;
  readonly variant: string;
  readonly url: string;
  readonly width: number;
  readonly height: number;
  readonly sha256: string;
  readonly alt: string;
  readonly transform: MediaAsset["transform"];
  readonly isActive: boolean;
}

function publicSelect(alias = "a") {
  const host = mediaPublicHost(currentEnv());
  return `${alias}.owner_kind AS "ownerKind", ${alias}.owner_id AS "ownerId", ${alias}.kind, ${alias}.variant,
    CASE WHEN ${alias}.media_sha256 IS NULL THEN ${alias}.url ELSE 'https://${host}/m/' || ${alias}.media_sha256 || '.' || mo.ext END AS url,
    ${alias}.width, ${alias}.height, COALESCE(${alias}.media_sha256, ${alias}.sha256) AS sha256, ${alias}.alt, ${alias}.transform, ${alias}.is_active AS "isActive"`;
}

/** Active rows for the named owners only. One unnest, no full-table read. */
export async function listPublicMediaRows(db: MediaDatabase, owners: readonly { readonly owner: MediaOwner; readonly ownerId: string }[]): Promise<PublicMediaRow[]> {
  if (owners.length === 0) return [];
  const result = await db.query(`SELECT ${publicSelect()} ${assetFrom("catalog_media")}
    WHERE a.is_active AND (a.owner_kind, a.owner_id) IN (SELECT * FROM unnest($1::text[], $2::text[]) AS pair(kind, id))
    ORDER BY a.owner_kind, a.owner_id, a.kind, a.variant`, [owners.map((owner) => owner.owner), owners.map((owner) => owner.ownerId)]);
  return result.rows.flatMap((row) => {
    if (typeof row.ownerKind !== "string" || typeof row.ownerId !== "string" || typeof row.kind !== "string" || typeof row.variant !== "string" || typeof row.url !== "string" || typeof row.sha256 !== "string" || typeof row.alt !== "string" || typeof row.width !== "number" || typeof row.height !== "number") return [];
    return [{
      ownerKind: row.ownerKind, ownerId: row.ownerId, kind: row.kind, variant: row.variant, url: row.url,
      width: row.width, height: row.height, sha256: row.sha256, alt: row.alt, transform: row.transform as MediaAsset["transform"], isActive: row.isActive === true,
    }];
  });
}

/** Active (or every) asset of many owners in one query. Missing owners are absent from the rows; the caller keeps their place. */
export async function listMediaByOwners(
  db: MediaDatabase,
  owners: readonly { readonly owner: MediaOwner; readonly ownerId: string }[],
  filter: { readonly activeOnly: boolean; readonly kind?: string; readonly variant?: string },
): Promise<{ owner: MediaOwner; ownerId: string; assets: MediaAsset[] }[]> {
  if (owners.length === 0) return [];
  const result = await db.query(`SELECT a.owner_kind AS "ownerKind", ${assetSelect("owner_id")} ${assetFrom("catalog_media")}
    WHERE (a.owner_kind, a.owner_id) IN (SELECT * FROM unnest($1::text[], $2::text[]) AS pair(kind, id))
    AND ($3::boolean OR a.is_active)
    AND ($4::text IS NULL OR a.kind = $4)
    AND ($5::text IS NULL OR a.variant = $5)
    ORDER BY a.kind, a.variant, a.version DESC`,
  [owners.map((owner) => owner.owner), owners.map((owner) => owner.ownerId), !filter.activeOnly, filter.kind ?? null, filter.variant ?? null]);
  const buckets = new Map<string, MediaAsset[]>();
  for (const row of result.rows) {
    const ownerKind = typeof row.ownerKind === "string" ? row.ownerKind : "";
    const asset = assetSchema.parse(row);
    const key = `${ownerKind}:${asset.ownerId}`;
    const list = buckets.get(key) ?? [];
    list.push(asset);
    buckets.set(key, list);
  }
  return owners.map((owner) => ({ owner: owner.owner, ownerId: owner.ownerId, assets: buckets.get(`${owner.owner}:${owner.ownerId}`) ?? [] }));
}

/** Every version (active or not) for an owner, optionally narrowed to one kind/variant. */
export async function listMediaVersions(db: MediaDatabase, owner: MediaOwner, ownerId: string, kind?: string, variant?: string): Promise<MediaAsset[]> {
  const key = mediaKey(owner, ownerId, kind ?? (owner === "lesson" ? "cover_16x9" : "poster_9x16"), variant);
  const filters = [`a.owner_kind='${key.owner}'`, `a.${key.column}=$1`, ...(kind ? ["a.kind=$2"] : []), ...(variant ? [`a.variant=$${kind ? "3" : "2"}`] : [])];
  const result = await db.query(`SELECT ${assetSelect(key.column)} ${assetFrom(key.table)} WHERE ${filters.join(" AND ")} ORDER BY a.kind, a.variant, a.version DESC`, [ownerId, ...(kind ? [kind] : []), ...(variant ? [variant] : [])]);
  return result.rows.map((row) => assetSchema.parse(row));
}
export async function swapMedia(pool: MediaPool | UnitOfWork, owner: MediaOwner, input: AssetInput): Promise<MediaAsset> {
  // Validate the complete descriptor before starting a transaction or deactivating anything.
  const asset = assetSchema.parse({ ...input, id: randomUUID(), version: 1, isActive: true, createdAt: new Date(), updatedAt: new Date() });
  const key = mediaKey(owner, asset.ownerId, asset.kind, asset.variant);
  return lockedTransaction(pool, owner, asset.ownerId, `media:${owner}:${asset.ownerId}:${asset.kind}:${asset.variant}`, async (db) => {
    const current = (await db.query(`SELECT ${assetSelect(key.column)} ${assetFrom(key.table)} WHERE a.owner_kind='${key.owner}' AND a.${key.column}=$1 AND a.kind=$2 AND a.variant=$3 AND a.is_active`, [asset.ownerId, asset.kind, asset.variant])).rows[0];
    if (current) {
      const existing = assetSchema.parse(current);
      if (["url", "sha256", "width", "height", "alt", "designStatus"].every((field) => existing[field as keyof MediaAsset] === asset[field as keyof MediaAsset]) && JSON.stringify(existing.transform) === JSON.stringify(asset.transform)) {
        return existing;
      }
    }
    const version = (await db.query(`SELECT COALESCE(MAX(version), 0)::int + 1 AS version FROM ${key.table} WHERE owner_kind='${key.owner}' AND ${key.column}=$1 AND kind=$2 AND variant=$3`, [asset.ownerId, asset.kind, asset.variant])).rows[0]?.version;
    await db.query(`UPDATE ${key.table} SET is_active=false, updated_at=now() WHERE owner_kind='${key.owner}' AND ${key.column}=$1 AND kind=$2 AND variant=$3 AND is_active`, [asset.ownerId, asset.kind, asset.variant]);
    await db.query(`INSERT INTO ${key.table} (id, owner_kind, ${key.column}, kind, variant, url, pathname, width, height, sha256, alt, transform, design_status, version, media_sha256)
      VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb,$13,$14,$15) RETURNING id`,
    [asset.id, key.owner, asset.ownerId, asset.kind, asset.variant, asset.url, asset.pathname, asset.width, asset.height, asset.sha256, asset.alt, JSON.stringify(asset.transform), asset.designStatus, version, asset.mediaSha256 ?? null]);
    if (asset.mediaSha256) await clearOrphaned(db, asset.mediaSha256);
    const result = await db.query(`SELECT ${assetSelect(key.column)} ${assetFrom(key.table)} WHERE a.id=$1`, [asset.id]);
    return assetSchema.parse(result.rows[0]);
  });
}
export async function rollbackMedia(pool: MediaPool | UnitOfWork, owner: MediaOwner, ownerId: string, kind: string, variant: string, version: number): Promise<MediaAsset> {
  const key = mediaKey(owner, ownerId, kind, variant);
  if (!Number.isSafeInteger(version) || version < 1) throw new Error("A positive --version is required.");
  return lockedTransaction(pool, owner, ownerId, `media:${owner}:${ownerId}:${kind}:${variant}`, async (db) => {
    const values = [ownerId, kind, variant, version];
    const result = await db.query(`SELECT ${assetSelect(key.column)} ${assetFrom(key.table)} WHERE a.owner_kind='${key.owner}' AND a.${key.column}=$1 AND a.kind=$2 AND a.variant=$3 AND a.version=$4`, values);
    const target = assetSchema.parse(result.rows[0]);
    await db.query(`UPDATE ${key.table} SET is_active=false, updated_at=now() WHERE owner_kind='${key.owner}' AND ${key.column}=$1 AND kind=$2 AND variant=$3 AND is_active`, values.slice(0, 3));
    await db.query(`UPDATE ${key.table} SET is_active=true, updated_at=now() WHERE id=$1`, [target.id]);
    if (target.mediaSha256) await clearOrphaned(db, target.mediaSha256);
    return { ...target, isActive: true };
  });
}
/** The pathnames still referenced by a row of this database other than `ids`: their bytes must stay. */
async function sharedPathnames(db: MediaDatabase, pathnames: readonly string[], ids: readonly string[]): Promise<Set<string>> {
  const shared = new Set<string>(pathnames.filter((key) => key.startsWith("m/")));
  if (pathnames.length) {
    const result = await db.query(`SELECT pathname FROM catalog_media WHERE pathname=ANY($1) AND id<>ALL($2)`, [pathnames, ids]);
    result.rows.forEach((row) => shared.add(String(row.pathname)));
  }
  return shared;
}
export interface MediaDeletion {
  /** Rows the request names (removed unless it is a dry-run). */
  readonly targets: readonly MediaAsset[];
  /** Pathnames of `targets` still referenced by another row of this database. */
  readonly shared: ReadonlySet<string>;
  readonly activeAfter: MediaAsset | null;
}
/**
 * Removes one inactive version, or a whole non-default variant when `version` is undefined, serialized like swapMedia.
 * Dry-run unless `apply`. `beforeCommit` runs after the DELETE; if it throws, the rows are restored.
 */
export async function deleteMedia(pool: MediaPool | UnitOfWork, owner: MediaOwner, ownerId: string, kind: string, variant: string, version: number | undefined,
  options: { apply: boolean; beforeCommit?: (deletion: MediaDeletion) => Promise<void> }): Promise<MediaDeletion> {
  const key = mediaKey(owner, ownerId, kind, variant);
  if (version === undefined && variant === "default") throw new MediaConflictError("The default variant is never deleted: pass an inactive version.");
  return lockedTransaction(pool, owner, ownerId, `media:${owner}:${ownerId}:${kind}:${variant}`, async (db) => {
    const rows = (await db.query(`SELECT ${assetSelect(key.column)} ${assetFrom(key.table)} WHERE a.owner_kind='${key.owner}' AND a.${key.column}=$1 AND a.kind=$2 AND a.variant=$3 ORDER BY a.version DESC`, [ownerId, kind, variant])).rows.map((row) => assetSchema.parse(row));
    const targets = version === undefined ? rows : rows.filter((asset) => asset.version === version);
    if (version !== undefined && targets.some((asset) => asset.isActive)) throw new MediaConflictError("Active version: roll back first or delete the whole variant.");
    const ids = targets.map((asset) => asset.id);
    const pathnames = [...new Set(targets.map((asset) => asset.pathname))];
    const shared = await sharedPathnames(db, pathnames, ids);
    const deletion = { targets, shared, activeAfter: version === undefined ? null : rows.find((asset) => asset.isActive) ?? null };
    if (options.apply && ids.length) {
      await db.query(`DELETE FROM ${key.table} WHERE id=ANY($1)`, [ids]);
      await options.beforeCommit?.(deletion);
    }
    return deletion;
  });
}

export interface OwnedMediaRow {
  readonly id: string;
  readonly owner: MediaOwner;
  readonly ownerId: string;
  readonly kind: string;
  readonly variant: string;
  readonly version: number;
  readonly isActive: boolean;
  readonly pathname: string;
}
/**
 * Every row (any kind, variant or version) of these owners, and which of their pathnames another row still uses.
 * Read inside the caller's transaction, after the owners are locked: the catalog purge of a course or a lesson (ADR-18).
 */
export async function ownedMedia(db: MediaDatabase, owners: { readonly courses: readonly string[]; readonly lessons: readonly string[] }): Promise<{ rows: OwnedMediaRow[]; shared: Set<string> }> {
  const rows: OwnedMediaRow[] = [];
  for (const [owner, ids] of [["course", owners.courses], ["lesson", owners.lessons]] as const) {
    if (ids.length === 0) continue;
    const key = mediaKey(owner, "inventory", owner === "lesson" ? "cover_16x9" : "poster_9x16");
    const result = await db.query(`SELECT id, ${key.column} AS owner_id, kind, variant, version, is_active, pathname FROM ${key.table} WHERE owner_kind='${key.owner}' AND ${key.column}=ANY($1) ORDER BY ${key.column}, kind, variant, version`, [ids]);
    rows.push(...result.rows.map((row) => ({ id: String(row.id), owner, ownerId: String(row.owner_id), kind: String(row.kind), variant: String(row.variant), version: Number(row.version), isActive: row.is_active === true, pathname: String(row.pathname) })));
  }
  return { rows, shared: await sharedPathnames(db, [...new Set(rows.map((row) => row.pathname))], rows.map((row) => row.id)) };
}
/** Deletes rows listed by ownedMedia, in the caller's transaction (the bytes are the caller's job, after its commit). */
export async function deleteOwnedMedia(db: MediaDatabase, rows: readonly OwnedMediaRow[]): Promise<void> {
  for (const owner of ["course", "lesson"] as const) {
    const ids = rows.filter((row) => row.owner === owner).map((row) => row.id);
    if (ids.length) await db.query(`DELETE FROM catalog_media WHERE owner_kind=$1 AND id=ANY($2)`, [owner, ids]);
  }
}
