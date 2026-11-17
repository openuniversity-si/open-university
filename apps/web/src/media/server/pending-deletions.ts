import { errorSummary } from "../../kernel/errors.ts";
import type { Queryable } from "../../platform/db/uow.ts";
import { retentionEligible } from "./lifecycle.ts";
import { StorageError } from "./storage-error.ts";

export async function queuePending(tx: Queryable, keys: readonly string[], media: readonly { readonly pathname: string; readonly owner?: string; readonly ownerId?: string }[], courseId: string, requestId: string): Promise<void> {
  for (const key of keys) {
    const row = media.find((entry) => entry.pathname === key);
    await tx.query(`INSERT INTO r2_pending_deletions (key, owner_kind, owner_id, course_id, request_id) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (key) DO NOTHING`,
      [key, row?.owner ?? "course", row?.ownerId ?? courseId, courseId, requestId]);
  }
}

/** Asset pathnames only. Catalog JSON references are unioned by the caller. */
export async function usedMediaKeys(db: Queryable, keys: readonly string[]): Promise<string[]> {
  if (keys.length === 0) return [];
  const { rows } = await db.query(`SELECT pathname FROM catalog_media WHERE pathname = ANY($1) ORDER BY 1`, [keys]);
  return rows.map((row) => String(row.pathname));
}

export async function pendingKeys(db: Queryable, filter: { readonly courseId?: string; readonly lessonId?: string }): Promise<string[]> {
  if (filter.courseId) return (await db.query("SELECT key FROM r2_pending_deletions WHERE course_id = $1 ORDER BY key", [filter.courseId])).rows.map((row) => String(row.key));
  if (filter.lessonId) return (await db.query("SELECT key FROM r2_pending_deletions WHERE owner_kind = 'lesson' AND owner_id = $1 ORDER BY key", [filter.lessonId])).rows.map((row) => String(row.key));
  return [];
}

export async function heldForRetention(db: Queryable, keys: readonly string[]): Promise<boolean> {
  if (keys.length === 0) return true;
  const { rows } = await db.query("SELECT last_error FROM r2_pending_deletions WHERE key = ANY($1)", [keys]);
  return rows.length === keys.length && rows.every((row) => row.last_error === "retention");
}

export async function countPending(db: Queryable, filter: { readonly courseId?: string; readonly lessonId?: string }): Promise<number> {
  const keys = await pendingKeys(db, filter);
  return keys.length;
}

export async function drainPendingObjects(db: Queryable, store: () => { delete(key: string): Promise<void> }, filter: { courseId: string } | { lessonId: string }, checkedKeys: readonly string[] = [], referenced: ReadonlySet<string> = new Set(), now: Date = new Date()): Promise<{ deleted: string[]; pending: string[] }> {
  if (checkedKeys.length === 0) return { deleted: [], pending: [] };
  const { rows } = "courseId" in filter
    ? await db.query("SELECT key FROM r2_pending_deletions WHERE course_id = $1 AND key = ANY($2) ORDER BY key", [filter.courseId, checkedKeys])
    : await db.query("SELECT key FROM r2_pending_deletions WHERE owner_kind = 'lesson' AND owner_id = $1 AND key = ANY($2) ORDER BY key", [filter.lessonId, checkedKeys]);
  const result = { deleted: [] as string[], pending: [] as string[] };
  let bucket: { delete(key: string): Promise<void> } | null = null;
  for (const { key } of rows) {
    if (referenced.has(String(key))) continue;
    if (!await retentionEligible(db, String(key), now)) {
      await db.query("UPDATE r2_pending_deletions SET attempts = attempts + 1, last_error = $2 WHERE key = $1", [key, "retention"]);
      result.pending.push(String(key));
      continue;
    }
    try {
      bucket ??= store();
      await bucket.delete(String(key));
      await db.query("DELETE FROM r2_pending_deletions WHERE key = $1", [key]);
      result.deleted.push(String(key));
    } catch (error) {
      const reason = error instanceof StorageError ? error.message : errorSummary(error);
      await db.query("UPDATE r2_pending_deletions SET attempts = attempts + 1, last_error = $2 WHERE key = $1", [key, reason]);
      result.pending.push(String(key));
    }
  }
  return result;
}
