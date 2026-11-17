import type { ReleaseFrame } from "./incremental-compile.ts";

/** Courses and lessons a page actually stitched. Extra frame rows stay, but they may only name these ids. */
export interface PageCourseRef {
  readonly id: string;
  readonly slug: string;
  readonly featured: boolean;
}
export interface PageLessonRef {
  readonly courseId: string;
  readonly slug: string;
}

/**
 * A page catalog is a subset of one release. Home rows, the featured flag and redirects
 * shrink to that subset so `releaseSchema` still holds and other universities stay out of the view.
 */
export function frameForCourses(frame: ReleaseFrame, courses: readonly PageCourseRef[], lessons: readonly PageLessonRef[]): ReleaseFrame {
  const ids = new Set(courses.map((course) => course.id));
  const featured = courses.find((course) => course.featured)?.id ?? null;
  const live = new Set(courses.map((course) => `/c/${course.slug}`));
  for (const lesson of lessons) {
    const course = courses.find((entry) => entry.id === lesson.courseId);
    if (course) live.add(`/c/${course.slug}/${lesson.slug}`);
  }
  return {
    authors: frame.authors,
    home: {
      featuredCourseId: featured,
      rows: frame.home.rows.map((row) => ({ ...row, courseIds: row.courseIds.filter((id) => ids.has(id)) })),
    },
    redirects: frame.redirects.filter((redirect) => live.has(redirect.to) && !live.has(redirect.from)),
    ...(frame.areas ? { areas: frame.areas } : {}),
    ...(frame.subareas ? { subareas: frame.subareas } : {}),
  };
}
