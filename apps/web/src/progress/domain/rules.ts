/**
 * F11 progress rules: pure, no I/O. Inputs are the course's lessons (catalog order) and the viewer's
 * `lesson_progress` rows for that course; outputs are what every surface shows (Home, Billboard, Course, Player).
 */
/** Position checkpoints for one lesson are applied at most once per 5 s; completion changes always apply. */
export const PROGRESS_THROTTLE_SECONDS = 5;

export interface ProgressLesson {
  readonly id: string;
  readonly slug: string;
  readonly order: number;
  readonly durationSeconds: number;
}

export interface ProgressRow {
  readonly lessonId: string;
  readonly positionSeconds: number;
  /** Duration recorded with the row; preferred over the catalog's when present. */
  readonly durationSeconds: number | null;
  readonly completed: boolean;
  /** Epoch milliseconds of the last write (last writer wins across devices). */
  readonly updatedAt: number;
}

export interface CurrentLesson {
  readonly lesson: ProgressLesson;
  readonly positionSeconds: number;
  readonly durationSeconds: number;
  readonly remainingSeconds: number;
  /** Position ÷ duration in [0, 1]; 0 when D5 advanced the card to the next unfinished lesson. */
  readonly fraction: number;
}

export interface CourseProgress {
  readonly started: boolean;
  /** D4: every lesson is done; the course leaves Continue Watching and the CTA restarts at lesson 1. */
  readonly allDone: boolean;
  readonly completedIds: ReadonlySet<string>;
  readonly completedCount: number;
  readonly total: number;
  /** Completed ÷ total, for the course progress bar. */
  readonly fraction: number;
  /** Rounded percent label, e.g. "18%". */
  readonly percent: string;
  /** The lesson Resume/Continue points at; null when not started or all done. */
  readonly current: CurrentLesson | null;
  readonly cta: { readonly kind: "start" | "resume"; readonly lesson: ProgressLesson; readonly seconds: number };
  readonly lastActivity: number;
  readonly continueWatching: boolean;
}

const clamp = (value: number, max: number) => Math.min(Math.max(Math.floor(value), 0), max);

function durationOf(lesson: ProgressLesson, row: ProgressRow | undefined): number {
  return row?.durationSeconds && row.durationSeconds > 0 ? row.durationSeconds : lesson.durationSeconds;
}

/** Lessons must be in catalog order and non-empty (a published course always has a first lesson). */
export function courseProgress(lessons: readonly ProgressLesson[], rows: readonly ProgressRow[]): CourseProgress {
  const first = lessons[0];
  if (!first) throw new Error("A course needs at least one lesson.");
  const ids = new Set(lessons.map((lesson) => lesson.id));
  const own = rows.filter((row) => ids.has(row.lessonId));
  const byLesson = new Map(own.map((row) => [row.lessonId, row]));
  const completedIds = new Set(own.filter((row) => row.completed).map((row) => row.lessonId));
  const total = lessons.length;
  const fraction = completedIds.size / total;
  const allDone = completedIds.size === total;
  const latest = own.reduce<ProgressRow | undefined>((best, row) => (!best || row.updatedAt > best.updatedAt ? row : best), undefined);
  const base = { started: latest !== undefined, allDone, completedIds, completedCount: completedIds.size, total, fraction,
    percent: `${String(Math.round(fraction * 100))}%`, lastActivity: latest?.updatedAt ?? 0 };
  // From the most recent lesson onwards (wrapping): itself if unfinished, else D5's next unfinished, from its start.
  // None left is D4 (all done).
  const index = lessons.findIndex((lesson) => lesson.id === latest?.lessonId);
  const lesson = latest && [...lessons.slice(index), ...lessons.slice(0, index)].find((entry) => !completedIds.has(entry.id));
  if (!latest || !lesson) return { ...base, current: null, cta: { kind: "start", lesson: first, seconds: 0 }, continueWatching: false };
  const row = byLesson.get(lesson.id);
  const durationSeconds = durationOf(lesson, row);
  const positionSeconds = latest.completed || !row ? 0 : clamp(row.positionSeconds, durationSeconds);
  const current = { lesson, positionSeconds, durationSeconds, remainingSeconds: durationSeconds - positionSeconds, fraction: positionSeconds / durationSeconds };
  return { ...base, current, cta: { kind: "resume", lesson, seconds: positionSeconds }, continueWatching: true };
}

/** Continue Watching: started, unfinished courses, most recent activity first. */
export function continueWatching<T extends { readonly progress: CourseProgress }>(courses: readonly T[]): T[] {
  return courses.filter((course) => course.progress.continueWatching).sort((a, b) => b.progress.lastActivity - a.progress.lastActivity);
}

/** Where a lesson's Player opens for this viewer: an explicit `?t=` wins, then the saved position unless done. */
export function lessonStartSecond(row: ProgressRow | undefined, requested: number | null, durationSeconds: number): number {
  if (requested !== null) return clamp(requested, durationSeconds);
  return row && !row.completed ? clamp(row.positionSeconds, durationSeconds) : 0;
}

/** "2h 32m", "1h 03m", "58m"; minutes are floored like the catalog's lesson lengths. */
export function durationLabel(seconds: number): string {
  const minutes = Math.floor(Math.max(seconds, 0) / 60);
  return minutes >= 60 ? `${String(Math.floor(minutes / 60))}h ${String(minutes % 60).padStart(2, "0")}m` : `${String(minutes)}m`;
}

/** "1h 40m left": remaining time rounds up, so a started minute still counts and nothing reads "0m left". */
export function remainingLabel(seconds: number): string {
  const minutes = Math.max(Math.ceil(seconds / 60), 1);
  return `${durationLabel(minutes * 60)} left`;
}

/** Decision 2: resume links carry the saved second; zero opens the lesson from its start. */
export function lessonHref(courseSlug: string, lessonSlug: string, seconds = 0): string {
  const path = `/c/${courseSlug}/${lessonSlug}`;
  return seconds > 0 ? `${path}?t=${String(Math.floor(seconds))}` : path;
}
