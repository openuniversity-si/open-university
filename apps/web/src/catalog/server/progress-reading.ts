import { courseProgressView, type CourseProgressView } from "../../progress/domain/view.ts";
import type { ProgressRow } from "../../progress/domain/rules.ts";
import { progressViewCourse } from "../domain/progress-reading.ts";
import type { Course } from "../domain/queries.ts";
import type { PublicCatalog } from "../domain/release.ts";

/** The one reading progress delivers for a course. Home, the poster, the course page and the lesson page place it. */
export function courseReading(catalog: PublicCatalog, course: Course, rows: readonly ProgressRow[]): CourseProgressView {
  return courseProgressView(progressViewCourse(catalog, course), rows);
}

/** Every course's reading for a signed-in viewer, keyed by course id. Rows of lessons no longer in the release are ignored. */
export function catalogProgressViews(catalog: PublicCatalog, rows: readonly ProgressRow[]): ReadonlyMap<string, CourseProgressView> {
  return new Map(catalog.courses.map((course) => [course.id, courseReading(catalog, course, rows)]));
}
