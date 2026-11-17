import { authorOf, courseBySlug, lessonAbout, lessonBySlug } from "../domain/queries.ts";
import type { PublicCatalog } from "../domain/release.ts";
import type { CourseMetadataInput, LessonMetadataInput } from "../../site/domain/metadata.ts";

interface ArtLike { readonly kind?: string; readonly variant?: string; readonly url: string; readonly width: number; readonly height: number }

function artOf(assets: readonly ArtLike[] | undefined): CourseMetadataInput["art"] {
  return (assets ?? []).map((entry) => ({ kind: entry.kind ?? "", variant: entry.variant ?? "", url: entry.url, width: entry.width, height: entry.height }));
}

/** Course page metadata input, or null when the slug or its author is not in the release. */
export function courseMetadataInput(catalog: PublicCatalog, courseSlug: string, courseArt?: readonly ArtLike[]): CourseMetadataInput | null {
  const course = courseBySlug(catalog, courseSlug);
  const author = course ? authorOf(catalog, course) : undefined;
  if (!course || !author) return null;
  return { slug: course.slug, displayTitle: course.displayTitle, description: course.description, authorName: author.name, art: artOf(courseArt) };
}

/** Lesson page metadata input, or null when the course or lesson is not in the release. */
export function lessonMetadataInput(catalog: PublicCatalog, courseSlug: string, lessonSlug: string, courseArt?: readonly ArtLike[]): LessonMetadataInput | null {
  const course = courseBySlug(catalog, courseSlug);
  const lesson = course ? lessonBySlug(catalog, course.id, lessonSlug) : undefined;
  if (!course || !lesson) return null;
  const author = authorOf(catalog, course);
  return {
    course: { slug: course.slug, displayTitle: course.displayTitle, description: course.description, authorName: author?.name ?? "", art: artOf(courseArt) },
    slug: lesson.slug, displayTitle: lesson.displayTitle, about: lessonAbout(lesson),
  };
}
