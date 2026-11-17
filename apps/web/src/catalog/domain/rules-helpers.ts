import type { CatalogRow, CatalogTables } from "./tables.ts";
import { courseFacts, evaluateRules, type CourseFacts, type RuleOptions, type RuleTarget } from "./rules/status.ts";

/** The tables plus what they leave out (revisions, active cover kinds): what the rules and the listings read. */
export interface CatalogState {
  readonly tables: CatalogTables;
  readonly revisions: ReadonlyMap<string, number>;
  readonly covers: ReadonlyMap<string, ReadonlySet<string>>;
}

export function factsOf(state: CatalogState, courseId: string): CourseFacts | null {
  return courseFacts(state.tables, courseId, state.covers.get(courseId) ?? new Set());
}

/** The target a course moves to next, and what still blocks it. */
export function pendingFor(state: CatalogState, course: CatalogRow<"courses">, options: RuleOptions = {}) {
  const target: RuleTarget | null = course.status === "draft" ? "review" : course.status === "archived" ? null : "published";
  const facts = factsOf(state, course.id);
  return { target, failed: target && facts ? evaluateRules(target, facts, options) : [] };
}

export const coursePath = (slug: string) => `/c/${slug}`;
export const lessonPath = (courseSlug: string, lessonSlug: string) => `/c/${courseSlug}/${lessonSlug}`;

/** The pages the tables would publish now: each published course and its visible lessons. */
export function livePaths(tables: CatalogTables): Set<string> {
  const published = new Map(tables.courses.filter((course) => course.status === "published").map((course) => [course.id, course.slug]));
  const paths = new Set([...published.values()].map(coursePath));
  for (const lesson of tables.lessons) {
    const slug = published.get(lesson.course_id);
    if (slug !== undefined && lesson.visible) paths.add(lessonPath(slug, lesson.slug));
  }
  return paths;
}

/** Per edition: lesson counts by part, visible lessons and duration (GET /courses/:id, ADR-21). */
export function editionCounts(tables: CatalogTables, edition: CatalogRow<"course_editions">) {
  const lessons = tables.lessons.filter((lesson) => lesson.edition_id === edition.id);
  return {
    lessons: lessons.length, visibleLessons: lessons.filter((lesson) => lesson.visible).length,
    parts: { lectures: lessons.filter((lesson) => lesson.part === "lectures").length, labs: lessons.filter((lesson) => lesson.part === "labs").length },
    durationSeconds: lessons.reduce((sum, lesson) => sum + lesson.duration_seconds, 0),
  };
}

/** A timestamptz as pg returns it (Date) or as JSON carries it (string), in ISO form; null otherwise. */
export function iso(value: unknown): string | null {
  if (value instanceof Date) return value.toISOString();
  return typeof value === "string" ? new Date(value).toISOString() : null;
}
