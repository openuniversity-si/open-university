// The lesson slug rule applied to a whole course (BRIEF-P7 §1–§2): what `tower-catalog lesson reslug` sends and what
// `doctor` (lesson.slug.quality) compares with. Pure, no I/O; both read it from the catalog tables (slugCourseFromTables).
import { authorKind } from "./schema/fields.ts";
import { baseLessonSlug, cleanLessonSlug, LESSON_SLUG_MAX } from "./lesson-address.ts";
import type { CatalogTables } from "./tables.ts";

/**
 * The 126 lessons of the 5 original courses (2017): their slugs are legacy identity and never change (docs/catalog/slugs.md).
 * Fixed id ranges, the same list as legacyLessonIds in slug.fixtures.json (slug-course.test.ts checks it).
 */
const LEGACY_RANGES: readonly (readonly [number, number])[] = [[1, 17], [52, 63], [116, 212]];
export const LEGACY_LESSON_IDS: ReadonlySet<string> = new Set(LEGACY_RANGES.flatMap(([first, last]) => Array.from({ length: last - first + 1 }, (_, index) => `lesson-${String(first + index)}`)));

export interface SlugCourse {
  readonly slug: string;
  readonly title: string;
  readonly institution: string | null;
  /** In edition order. */
  readonly editions: readonly { readonly id: string; readonly label: string; readonly term: string | null; readonly year: number | null }[];
  /** In course order (edition, then position). */
  readonly lessons: readonly {
    readonly id: string; readonly editionId: string; readonly position: number; readonly kind: string;
    readonly youtubeTitle: string; readonly displayTitle: string | null; readonly slug: string;
  }[];
}

/**
 * A course of the catalog tables (GET /tables) as SlugCourse: the approved displayTitle when there is one, and the
 * author's name as the institution unless the author is a person.
 */
function pushGroup<T>(groups: Map<string, T[]>, key: string, row: T): void {
  const list = groups.get(key);
  if (list) list.push(row);
  else groups.set(key, [row]);
}

interface SlugIndex {
  readonly courses: ReadonlyMap<string, CatalogTables["courses"][number]>;
  readonly authors: ReadonlyMap<string, CatalogTables["authors"][number]>;
  readonly editionsByCourse: ReadonlyMap<string, CatalogTables["course_editions"][number][]>;
  readonly lessonsByCourse: ReadonlyMap<string, CatalogTables["lessons"][number][]>;
  readonly titles: ReadonlyMap<string, string>;
}

/** One pass over the tables. Building this per course rescans every lesson and text. */
function slugIndex(tables: CatalogTables): SlugIndex {
  const editionsByCourse = new Map<string, CatalogTables["course_editions"][number][]>();
  for (const edition of tables.course_editions) pushGroup(editionsByCourse, edition.course_id, edition);
  for (const editions of editionsByCourse.values()) editions.sort((a, b) => a.position - b.position);
  const lessonsByCourse = new Map<string, CatalogTables["lessons"][number][]>();
  for (const lesson of tables.lessons) pushGroup(lessonsByCourse, lesson.course_id, lesson);
  const titles = new Map<string, string>();
  for (const text of tables.catalog_texts) {
    if (text.entity_kind === "lesson" && text.field === "displayTitle" && text.status === "approved") titles.set(text.entity_id, text.text);
  }
  return {
    courses: new Map(tables.courses.map((course) => [course.id, course])),
    authors: new Map(tables.authors.map((author) => [author.id, author])),
    editionsByCourse, lessonsByCourse, titles,
  };
}

function slugCourseFromIndex(index: SlugIndex, courseId: string): SlugCourse | null {
  const course = index.courses.get(courseId);
  if (!course) return null;
  const author = index.authors.get(course.author_id);
  const editions = index.editionsByCourse.get(courseId) ?? [];
  const rank = new Map(editions.map((edition, position) => [edition.id, position]));
  return {
    slug: course.slug, title: course.title, institution: author && author.kind !== authorKind.person ? author.name : null,
    editions: editions.map((edition) => ({ id: edition.id, label: edition.label, term: edition.term, year: edition.year })),
    lessons: [...(index.lessonsByCourse.get(courseId) ?? [])]
      .sort((a, b) => (rank.get(a.edition_id) ?? 0) - (rank.get(b.edition_id) ?? 0) || a.position - b.position)
      .map((lesson) => ({ id: lesson.id, editionId: lesson.edition_id, position: lesson.position, kind: lesson.kind, youtubeTitle: lesson.youtube_title, displayTitle: index.titles.get(lesson.id) ?? null, slug: lesson.slug })),
  };
}

export function slugCourseFromTables(tables: CatalogTables, courseId: string): SlugCourse | null {
  return slugCourseFromIndex(slugIndex(tables), courseId);
}

/** Every course, from one index. Doctor checks the whole catalog; one `slugCourseFromTables` per course does not. */
export function slugCoursesFromTables(tables: CatalogTables): Map<string, SlugCourse> {
  const index = slugIndex(tables);
  const courses = new Map<string, SlugCourse>();
  for (const course of tables.courses) {
    const slugCourse = slugCourseFromIndex(index, course.id);
    if (slugCourse) courses.set(course.id, slugCourse);
  }
  return courses;
}

export interface Reslug {
  readonly lessonId: string;
  readonly before: string;
  readonly after: string;
  /** `rule`, `rule, disambiguated` (a `-2`… suffix), `kept` (already the rule's slug), `excluded` or `legacy`. */
  readonly reason: "rule" | "rule, disambiguated" | "kept" | "excluded" | "legacy";
}

/**
 * The slug the rule gives each lesson, generated in course order as a fresh import would (each slug taken by the ones
 * before it). Legacy and excluded lessons keep theirs, and their slugs are taken first so nothing collides with them.
 */
export function reslugCourse(course: SlugCourse, exclude: ReadonlySet<string> = new Set()): Reslug[] {
  const held = (id: string) => LEGACY_LESSON_IDS.has(id) || exclude.has(id);
  const taken = new Set(course.lessons.filter((lesson) => held(lesson.id)).map((lesson) => lesson.slug));
  const editions = new Map(course.editions.map((edition) => [edition.id, edition]));
  return course.lessons.map((lesson) => {
    if (held(lesson.id)) return { lessonId: lesson.id, before: lesson.slug, after: lesson.slug, reason: LEGACY_LESSON_IDS.has(lesson.id) ? "legacy" : "excluded" };
    const input = {
      youtubeTitle: lesson.youtubeTitle, displayTitle: lesson.displayTitle, courseTitle: course.title, courseSlug: course.slug, institution: course.institution,
      edition: editions.get(lesson.editionId) ?? null, position: lesson.position, kind: lesson.kind,
    };
    const after = cleanLessonSlug(input, taken);
    taken.add(after);
    const reason = after === lesson.slug ? "kept" : after === baseLessonSlug(input) ? "rule" : "rule, disambiguated";
    return { lessonId: lesson.id, before: lesson.slug, after, reason };
  });
}

const EDITION_TAG = /(?:^|-)(?:(?:fall|spring|summer|winter|autumn)-?(?:\d{4}|\d{2})|(?:fa|sp|su|wi)\d{2})(?:-|$)/;

/** Why a non-legacy lesson slug is not clean (doctor lesson.slug.quality); empty when it is. */
export function slugQualityIssues(slug: string, expected: string, courseSlug: string): string[] {
  return [
    ...(slug.length > LESSON_SLUG_MAX ? [`longer than ${String(LESSON_SLUG_MAX)}`] : []),
    ...(EDITION_TAG.test(slug) ? ["edition tag"] : []),
    ...(courseSlug.length > 0 && slug.includes(courseSlug) ? ["course name"] : []),
    ...(slug !== expected ? [`rule gives ${expected}`] : []),
  ];
}
