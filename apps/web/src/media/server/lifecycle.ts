import { createHash } from "node:crypto";
import { PAGINATION } from "../../kernel/pagination.ts";
import type { Queryable } from "../../platform/db/uow.ts";
import { RETENTION_MS } from "../domain/figure-exit.ts";

export interface CatalogLifecycleRef {
  readonly sha256: string;
  readonly retainedRelease: boolean;
}

export interface LifecycleRow {
  readonly sha256: string;
  readonly bytesPresent: boolean;
  readonly referenced: boolean;
  readonly retainedRelease: boolean;
  readonly orphanedAt: string | null;
}

const SHA = /^[a-f0-9]{64}$/;

function text(value: unknown): string | null {
  if (typeof value === "string") return value;
  if (typeof value === "number" || value instanceof Date) return value instanceof Date ? value.toISOString() : String(value);
  return null;
}

/** Asset refs only. Catalog shas (authors, home, releases) are passed in. */
export async function listLifecycleRows(db: Queryable, catalog: readonly CatalogLifecycleRef[]): Promise<LifecycleRow[]> {
  const objects = await db.query("SELECT sha256, orphaned_at FROM media_objects ORDER BY sha256");
  const assets = await db.query(`SELECT media_sha256 AS sha256 FROM catalog_media WHERE media_sha256 IS NOT NULL`);
  const referenced = new Set(assets.rows.map((row) => String(row.sha256)));
  const retained = new Map<string, boolean>();
  for (const ref of catalog) {
    if (!SHA.test(ref.sha256)) continue;
    referenced.add(ref.sha256);
    if (ref.retainedRelease) retained.set(ref.sha256, true);
  }
  const rows = new Map<string, LifecycleRow>();
  for (const row of objects.rows) {
    const sha256 = String(row.sha256);
    rows.set(sha256, {
      sha256,
      bytesPresent: true,
      referenced: referenced.has(sha256),
      retainedRelease: retained.get(sha256) === true,
      orphanedAt: text(row.orphaned_at) === null ? null : new Date(text(row.orphaned_at) ?? "").toISOString(),
    });
  }
  for (const sha256 of referenced) {
    if (rows.has(sha256)) continue;
    rows.set(sha256, { sha256, bytesPresent: false, referenced: true, retainedRelease: retained.get(sha256) === true, orphanedAt: null });
  }
  return [...rows.values()].sort((a, b) => (a.sha256 < b.sha256 ? -1 : 1));
}

/** Sets the marker only while it is still null, so a repeat mark does not move the window. */
export async function markOrphaned(db: Queryable, sha256: string): Promise<"marked" | "already" | "referenced"> {
  const assets = await db.query(`SELECT 1 AS hit FROM catalog_media WHERE media_sha256 = $1 LIMIT 1`, [sha256]);
  if (assets.rows.length > 0) return "referenced";
  const updated = await db.query("UPDATE media_objects SET orphaned_at = now() WHERE sha256 = $1 AND orphaned_at IS NULL RETURNING sha256", [sha256]);
  if (updated.rows.length > 0) return "marked";
  const existing = await db.query("SELECT orphaned_at FROM media_objects WHERE sha256 = $1", [sha256]);
  return existing.rows[0]?.orphaned_at == null ? "referenced" : "already";
}

export async function clearOrphaned(db: Queryable, sha256: string): Promise<void> {
  await db.query("UPDATE media_objects SET orphaned_at = NULL WHERE sha256 = $1", [sha256]);
}

/** The ship clears every attached object in one statement. An empty list writes nothing. */
export async function clearOrphanedMany(db: Queryable, shas: readonly string[]): Promise<void> {
  if (shas.length === 0) return;
  await db.query("UPDATE media_objects SET orphaned_at = NULL WHERE sha256 = ANY($1::text[])", [shas]);
}

export async function deleteOrphanedRow(db: Queryable, sha256: string): Promise<boolean> {
  const deleted = await db.query("DELETE FROM media_objects WHERE sha256 = $1 AND orphaned_at IS NOT NULL RETURNING sha256", [sha256]);
  return deleted.rows.length > 0;
}

/** Legacy queue keys without a 30-day marker stay queued. A timeout is not eligibility. */
export async function listObjectKeys(db: Queryable, cursor: string): Promise<{ keys: string[]; cursor: string | null; complete: boolean }> {
  const result = await db.query(`SELECT sha256, ext FROM media_objects WHERE sha256 > $1 ORDER BY sha256 LIMIT ${String(PAGINATION.objectListPage)}`, [cursor]);
  const keys = result.rows.flatMap((row) => {
    const hash = text(row.sha256);
    const extension = text(row.ext);
    return hash && extension ? [`m/${hash}.${extension}`] : [];
  });
  const last = text(result.rows.at(-1)?.sha256);
  return { keys, cursor: result.rows.length === PAGINATION.objectListPage && last ? last : null, complete: result.rows.length < PAGINATION.objectListPage };
}

export async function objectExtension(db: Queryable, sha256: string): Promise<string | null> {
  const result = await db.query("SELECT media_objects.ext AS ext FROM media_objects WHERE sha256 = $1", [sha256]);
  return text(result.rows[0]?.ext);
}

export async function retentionEligible(db: Queryable, key: string, now: Date): Promise<boolean> {
  const sha256 = /^m\/([a-f0-9]{64})\.[a-z0-9]+$/.exec(key)?.[1];
  if (!sha256) return false;
  const { rows } = await db.query("SELECT orphaned_at FROM media_objects WHERE sha256 = $1", [sha256]);
  const marked = text(rows[0]?.orphaned_at);
  if (marked === null) return false;
  return now.getTime() - new Date(marked).getTime() >= RETENTION_MS;
}

interface PendingKey {
  readonly key: string;
  readonly owner_kind: string;
  readonly owner_id: string;
  readonly course_id: string;
  readonly request_id: string;
}

const previewSnapshots = new Map<string, { readonly checksum: string; readonly keys: readonly PendingKey[] }>();

async function pendingManifest(db: Queryable, courses: number): Promise<{ checksum: string; rows: number; keys: PendingKey[] }> {
  const listed = await db.query("SELECT key, owner_kind, owner_id, course_id, request_id FROM r2_pending_deletions ORDER BY key");
  const keys = listed.rows.map((row) => ({
    key: String(row.key), owner_kind: String(row.owner_kind), owner_id: String(row.owner_id), course_id: String(row.course_id), request_id: String(row.request_id),
  }));
  const checksum = createHash("sha256").update(`${String(courses)}:${String(keys.length)}:${keys.map((row) => row.key).join(",")}`).digest("hex");
  return { checksum, rows: courses + keys.length, keys };
}

export async function capturePreviewSnapshot(db: Queryable, courses: number): Promise<{ id: string; checksum: string; rows: number } | null> {
  const current = await pendingManifest(db, courses);
  if (!current.checksum) return null;
  previewSnapshots.set(current.checksum, { checksum: current.checksum, keys: current.keys });
  return { id: current.checksum, checksum: current.checksum, rows: current.rows };
}

export async function rehearsePreviewSnapshot(db: Queryable, snapshotId: string, courses: number): Promise<boolean> {
  const stored = previewSnapshots.get(snapshotId);
  if (!stored) return false;
  const again = await pendingManifest(db, courses);
  return again.checksum === stored.checksum;
}

/** Drops the legacy queue. Object bytes and media_objects stay. */
export async function resetPreviewQueue(db: Queryable, snapshotId: string): Promise<boolean> {
  if (!previewSnapshots.has(snapshotId)) return false;
  await db.query("DELETE FROM r2_pending_deletions");
  return true;
}

export async function restorePreviewSnapshot(db: Queryable, snapshotId: string): Promise<boolean> {
  const stored = previewSnapshots.get(snapshotId);
  if (!stored) return false;
  for (const row of stored.keys) {
    await db.query("INSERT INTO r2_pending_deletions (key, owner_kind, owner_id, course_id, request_id) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (key) DO NOTHING", [row.key, row.owner_kind, row.owner_id, row.course_id, row.request_id]);
  }
  return true;
}
