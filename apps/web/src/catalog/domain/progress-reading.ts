import type { ProgressViewCourse } from "../../progress/domain/view.ts";
import { lessonLabel, lessonsForCourse, type Course } from "./queries.ts";
import type { PublicCatalog } from "./release.ts";

/** Structural course the progress domain can score without importing the catalog. */
export function progressViewCourse(catalog: PublicCatalog, course: Course): ProgressViewCourse {
  return {
    id: course.id,
    slug: course.slug,
    lessons: lessonsForCourse(catalog, course.id).map((lesson) => ({
      id: lesson.id, slug: lesson.slug, order: lesson.order, durationSeconds: lesson.durationSeconds,
      editionId: lesson.editionId, label: lessonLabel(course, lesson),
    })),
  };
}
