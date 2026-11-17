import type { Queryable } from "../../platform/db/uow.ts";
import type { ProgressMaintenancePort } from "../ports/maintenance.ts";

export function progressMaintenance(db: Queryable): ProgressMaintenancePort {
  return {
    async countForLessons(lessonIds) {
      if (lessonIds.length === 0) return 0;
      const { rows } = await db.query("SELECT count(*)::int AS n FROM lesson_progress WHERE lesson_id = ANY($1)", [lessonIds]);
      return Number(rows[0]?.n ?? 0);
    },
    async orphanedLessons(knownLessonIds) {
      const { rows } = await db.query("SELECT count(*)::int AS n, (array_agg(DISTINCT lesson_id ORDER BY lesson_id))[1:10] AS sample FROM lesson_progress WHERE NOT (lesson_id = ANY($1))", [knownLessonIds]);
      return { count: Number(rows[0]?.n ?? 0), sample: ((rows[0]?.sample ?? []) as unknown[]).map(String) };
    },
  };
}

export async function countLessonProgress(db: Queryable, lessonIds: readonly string[]): Promise<number> {
  return progressMaintenance(db).countForLessons(lessonIds);
}
