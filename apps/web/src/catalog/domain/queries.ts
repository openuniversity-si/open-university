import { lessonKind } from "./lesson-kind.ts";
import type { PublicCatalog, ReleaseCourse as Course, ReleaseEdition as Edition, ReleaseLesson as Lesson } from "./release.ts";
import { editionJoin, fill, labsNoun, lessonBackgroundLabel, lessonLabLabel, lessonTrailerLabel, nounPluralTemplate } from "../../site/domain/reader-copy.ts";

export type { Course, Edition, Lesson };

export function courseBySlug(catalog: PublicCatalog, slug: string): Course | undefined {
  return catalog.courses.find((course) => course.slug === slug);
}

export function authorOf(catalog: PublicCatalog, course: Course): PublicCatalog["authors"][number] | undefined {
  return catalog.authors.find((author) => author.id === course.authorId);
}

/** The course's editions, newest first: position 1 is the default one, open when the course opens (ADR-21). */
export function editionsForCourse(course: Course): readonly Edition[] {
  return course.editions;
}

/** Position 1. Every course of a release has one (releaseSchema). */
export function defaultEdition(course: Course): Edition {
  const [first] = course.editions;
  if (!first) throw new Error(`Course ${course.id} has no edition.`);
  return first;
}

/** One edition's lessons in order (1..N). */
export function lessonsForEdition(catalog: PublicCatalog, editionId: string): Lesson[] {
  return catalog.lessons.filter((lesson) => lesson.editionId === editionId).sort((a, b) => a.order - b.order);
}

/** Every lesson of the course: edition by edition (newest first), each in its order. */
export function lessonsForCourse(catalog: PublicCatalog, courseId: string): Lesson[] {
  const course = catalog.courses.find((entry) => entry.id === courseId);
  return (course?.editions ?? []).flatMap((edition) => lessonsForEdition(catalog, edition.id));
}

export function editionOf(catalog: PublicCatalog, lesson: Lesson): Edition | undefined {
  return catalog.courses.find((course) => course.id === lesson.courseId)?.editions.find((edition) => edition.id === lesson.editionId);
}

export function lessonBySlug(catalog: PublicCatalog, courseId: string, slug: string): Lesson | undefined {
  return catalog.lessons.find((lesson) => lesson.courseId === courseId && lesson.slug === slug);
}

/** Previous and next lesson inside the lesson's edition; never across editions or courses. */
export function lessonNeighbors(catalog: PublicCatalog, lessonId: string): { previous: Lesson | undefined; next: Lesson | undefined } {
  const lesson = catalog.lessons.find((entry) => entry.id === lessonId);
  if (!lesson) return { previous: undefined, next: undefined };
  const lessons = lessonsForEdition(catalog, lesson.editionId);
  return { previous: lessons.find((entry) => entry.order === lesson.order - 1), next: lessons.find((entry) => entry.order === lesson.order + 1) };
}

/** A lesson of the Labs part reads "Lab"; numbers ("Lecture 4 of 26") count inside the edition (ADR-21). */
export function lessonLabel(course: Course, lesson: Lesson): string {
  return lesson.kind === lessonKind.background ? lessonBackgroundLabel : lesson.kind === lessonKind.trailer ? lessonTrailerLabel : lesson.part === "labs" ? lessonLabLabel : course.lessonNoun;
}

/** "25 lectures", or "12 lectures + 14 labs" for an edition with both parts (ADR-21). */
export function editionCount(course: Course, edition: Edition): string {
  const noun = fill(nounPluralTemplate, { noun: course.lessonNoun.toLowerCase() });
  const { lectures, labs } = edition.parts;
  const labsLabel = `${String(labs)} ${labsNoun}`;
  if (labs === 0) return `${String(edition.lessonCount)} ${noun}`;
  return lectures === 0 ? labsLabel : `${String(lectures)} ${noun}${editionJoin}${labsLabel}`;
}

/** The release carries only approved Abouts (a draft one is null). */
export function lessonAbout(lesson: Lesson): string | null {
  return lesson.about;
}

/** Where an old path moved to (`slug_redirects`), if anywhere; trailing slashes are ignored. */
export function redirectFor(catalog: PublicCatalog, path: string): string | undefined {
  const clean = path.replace(/\/+$/, "");
  return catalog.redirects.find((redirect) => redirect.from === clean)?.to;
}
