import { PROGRESS_THROTTLE_SECONDS, type ProgressRow } from "../domain/rules.ts";
import type { ProgressRepositoryPort, ProgressWrite } from "../ports/repo.ts";

export interface ProgressDatabase {
  query(sql: string, values?: unknown[]): Promise<{ rows: Record<string, unknown>[] }>;
}

export type { ProgressWrite };

export async function readProgress(db: ProgressDatabase, userId: string): Promise<(ProgressRow & { readonly courseId: string })[]> {
  const result = await db.query(`SELECT lesson_id, course_id, position_seconds, duration_seconds, completed_at IS NOT NULL AS completed, updated_at
    FROM lesson_progress WHERE user_id = $1`, [userId]);
  return result.rows.map((row) => ({
    lessonId: String(row.lesson_id), courseId: String(row.course_id), positionSeconds: Number(row.position_seconds),
    durationSeconds: row.duration_seconds === null ? null : Number(row.duration_seconds), completed: row.completed === true,
    updatedAt: (row.updated_at as Date).getTime(),
  }));
}

/**
 * One upsert per write; the database clock orders writers, so the last writer wins across devices.
 * Returns false when a position checkpoint arrived inside the throttle window (nothing changed).
 */
export async function saveProgress(db: ProgressDatabase, write: ProgressWrite): Promise<boolean> {
  const { userId, courseId, lessonId, durationSeconds, positionSeconds, completed } = write;
  if (completed === undefined) {
    if (positionSeconds === undefined) throw new Error("A progress write needs a position or a completion.");
    const result = await db.query(`INSERT INTO lesson_progress AS p (user_id, lesson_id, course_id, position_seconds, duration_seconds)
      VALUES ($1, $2, $3, $4, $5)
      ON CONFLICT (user_id, lesson_id) DO UPDATE SET position_seconds = excluded.position_seconds, duration_seconds = excluded.duration_seconds, updated_at = now()
      WHERE p.updated_at <= now() - make_interval(secs => $6)
      RETURNING 1`, [userId, lessonId, courseId, positionSeconds, durationSeconds, PROGRESS_THROTTLE_SECONDS]);
    return result.rows.length > 0;
  }
  // Completing keeps the first completion time; unchecking clears it. A completion without a position keeps the saved one.
  await db.query(`INSERT INTO lesson_progress AS p (user_id, lesson_id, course_id, position_seconds, duration_seconds, completed_at)
    VALUES ($1, $2, $3, COALESCE($4, 0), $5, CASE WHEN $6 THEN now() END)
    ON CONFLICT (user_id, lesson_id) DO UPDATE SET position_seconds = COALESCE($4, p.position_seconds), duration_seconds = excluded.duration_seconds,
      completed_at = CASE WHEN $6 THEN COALESCE(p.completed_at, now()) END, updated_at = now()`,
  [userId, lessonId, courseId, positionSeconds ?? null, durationSeconds, completed]);
  return true;
}

/** SQL stays in this adapter. Callers that should not see `ProgressDatabase` use the port. */
export function progressRepository(db: ProgressDatabase): ProgressRepositoryPort {
  return {
    read: (userId) => readProgress(db, userId),
    save: (write) => saveProgress(db, write),
  };
}
