import { universities, universityAreas } from "../domain/universities.ts";
import { lessonsForCourse } from "../domain/queries.ts";
import type { PublicCatalog } from "../domain/release.ts";
import type { PublicRouteSnapshot } from "../../site/domain/route-registry.ts";

/**
 * The public route snapshot of one release. Institutions and areas appear only when they have published courses,
 * matching the universities projection. Redirects are the release's `slug_redirects`.
 */
export function publicRouteSnapshot(catalog: PublicCatalog): PublicRouteSnapshot {
  return {
    courses: catalog.courses.map((course) => ({ slug: course.slug, lessonSlugs: lessonsForCourse(catalog, course.id).map((lesson) => lesson.slug) })),
    institutions: universities(catalog).map((entry) => ({ slug: entry.slug, areaIds: universityAreas(catalog, entry.courses).map((area) => area.id) })),
    redirects: catalog.redirects.map((redirect) => ({ from: redirect.from, to: redirect.to })),
  };
}
