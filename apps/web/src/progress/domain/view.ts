import { courseProgress, lessonHref, remainingLabel, type ProgressLesson, type ProgressRow } from "./rules.ts";

export interface ProgressViewLesson extends ProgressLesson {
  readonly editionId: string;
  /** Ready label ("Lecture", "Lab", "Trailer", "Background"), computed by the catalog. */
  readonly label: string;
}
export interface ProgressViewCourse { readonly id: string; readonly slug: string; readonly lessons: readonly ProgressViewLesson[] }

/** What the signed-in surfaces render for one course; plain data so it can cross into client components. */
export interface CourseProgressView {
  /** Primary CTA: Resume at the saved second, or Start at lesson 1 (not started, or D4 all done). */
  readonly cta: { readonly kind: "start" | "resume"; readonly href: string; readonly lesson: string };
  /** Continue Watching card (CourseCard Continue 22:78); null when the course isn't in the rail. */
  readonly card: { readonly label: string; readonly remaining: string; readonly fraction: number; readonly href: string } | null;
  readonly watched: { readonly count: number; readonly total: number; readonly percent: string; readonly fraction: number };
  readonly watchedIds: readonly string[];
  /** The Current row in the lesson lists, with its "1h 40m left". */
  readonly current: { readonly lessonId: string; readonly remaining: string } | null;
  readonly lastActivity: number;
}

export function courseProgressView(course: ProgressViewCourse, rows: readonly ProgressRow[]): CourseProgressView {
  const lessons = course.lessons;
  const progress = courseProgress(lessons, rows);
  const named = (id: string) => {
    const lesson = lessons.find((entry) => entry.id === id);
    return lesson ? `${lesson.label} ${String(lesson.order)}` : "";
  };
  const editionSize = (id: string) => {
    const editionId = lessons.find((entry) => entry.id === id)?.editionId;
    return lessons.filter((entry) => entry.editionId === editionId).length;
  };
  const { current } = progress;
  return {
    cta: { kind: progress.cta.kind, href: lessonHref(course.slug, progress.cta.lesson.slug, progress.cta.seconds), lesson: named(progress.cta.lesson.id) },
    // "Lecture 4 of 26" counts inside the lesson's edition (ADR-21); one edition: the course.
    card: current ? {
      label: `${named(current.lesson.id)} of ${String(editionSize(current.lesson.id))}`, remaining: remainingLabel(current.remainingSeconds),
      fraction: current.fraction, href: lessonHref(course.slug, current.lesson.slug, current.positionSeconds),
    } : null,
    watched: { count: progress.completedCount, total: progress.total, percent: progress.percent, fraction: progress.fraction },
    watchedIds: [...progress.completedIds],
    current: current ? { lessonId: current.lesson.id, remaining: remainingLabel(current.remainingSeconds) } : null,
    lastActivity: progress.lastActivity,
  };
}

/** The watched counts over some of the course's lessons (one edition's list, ADR-21), rounded as the course's are. */
export function watchedAmong(view: CourseProgressView, lessonIds: readonly string[]): CourseProgressView["watched"] {
  const count = lessonIds.filter((id) => view.watchedIds.includes(id)).length;
  const fraction = lessonIds.length === 0 ? 0 : count / lessonIds.length;
  return { count, total: lessonIds.length, percent: `${String(Math.round(fraction * 100))}%`, fraction };
}
