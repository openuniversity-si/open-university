import { cleanLessonSlug } from "../../catalog/domain/lesson-address.ts";
import type { CuratedLesson } from "./curated.ts";

export interface BatchLessonLink {
  readonly id: string;
  readonly editionId: string;
  readonly slug: string;
  readonly title: string;
  readonly position: number;
  readonly youtubeId: string;
  readonly durationSeconds: number;
  readonly part: CuratedLesson["part"];
}

/**
 * The lesson's own facts enter the batch here.
 * The address is still the catalog slug; this is the only place a curated lesson is read.
 */
export function lessonLink(
  lesson: CuratedLesson,
  place: { readonly title: string; readonly slug: string; readonly year: number; readonly institution: string },
  editionId: string | null,
  lessonId: string | null,
  taken: Set<string>,
): BatchLessonLink | null {
  const slug = cleanLessonSlug({
    youtubeTitle: lesson.originalTitle,
    courseTitle: place.title,
    courseSlug: place.slug,
    institution: place.institution,
    edition: { label: String(place.year), year: place.year },
    position: lesson.position,
    kind: lesson.part === "labs" ? "lab" : "lecture",
  }, taken);
  taken.add(slug);
  if (lessonId === null || editionId === null) return null;
  return {
    id: lessonId,
    editionId,
    slug,
    title: lesson.originalTitle,
    position: lesson.position,
    youtubeId: lesson.youtubeId,
    durationSeconds: lesson.durationSeconds,
    part: lesson.part,
  };
}
