import type pg from "pg";

interface SeedRow { lessonId: string; courseId: string; position: number; duration: number | null; completed: boolean; secondsAgo: number }

function completedThrough(courseId: string, lessonIds: readonly string[], secondsAgo: number): SeedRow[] {
  return lessonIds.map((lessonId, index) => ({ lessonId, courseId, position: 0, duration: null, completed: true, secondsAgo: secondsAgo + lessonIds.length - index }));
}
const range = (prefix: string, from: number, count: number) => Array.from({ length: count }, (_, index) => `${prefix}${String(from + index)}`);

/**
 * Spec 06 (signed-in prototype): Fixture Course 1 lesson 4 at 3134/9128 s with lessons 1–3 done; Continue Watching also holds
 * Fixture Course 2 (Lecture 3 of 12, 58m left, 42%) and Awakening (Episode 12 of 51, 31m left, 42%), in that order.
 */
export const SPEC_06: readonly SeedRow[] = [
  { lessonId: "lesson-54", courseId: "course-2", position: 2520, duration: 6000, completed: false, secondsAgo: 60 },
  ...completedThrough("course-2", ["lesson-52", "lesson-53"], 600),
  { lessonId: "lesson-4", courseId: "course-1", position: 3134, duration: 9128, completed: false, secondsAgo: 120 },
  ...completedThrough("course-1", ["lesson-1", "lesson-2", "lesson-3"], 600),
  { lessonId: "lesson-147", courseId: "course-4", position: 1347, duration: 3207, completed: false, secondsAgo: 180 },
  ...completedThrough("course-4", range("lesson-", 136, 11), 600),
];

export async function seedProgress(pool: pg.Pool, userId: string, rows: readonly SeedRow[] = SPEC_06): Promise<void> {
  for (const row of rows) {
    await pool.query(`INSERT INTO lesson_progress (user_id, lesson_id, course_id, position_seconds, duration_seconds, completed_at, updated_at)
      VALUES ($1, $2, $3, $4, $5, CASE WHEN $6 THEN now() - make_interval(secs => $7) END, now() - make_interval(secs => $7))`,
    [userId, row.lessonId, row.courseId, row.position, row.duration, row.completed, row.secondsAgo]);
  }
}

export async function readLessonProgress(pool: pg.Pool, userId: string, lessonId: string) {
  const result = await pool.query<{ position_seconds: number; completed: boolean }>(
    "SELECT position_seconds, completed_at IS NOT NULL AS completed FROM lesson_progress WHERE user_id = $1 AND lesson_id = $2", [userId, lessonId]);
  return result.rows[0] ?? null;
}
