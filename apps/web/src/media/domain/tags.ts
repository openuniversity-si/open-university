import type { MediaOwner } from "./types.ts";

/** Every cached media read carries it; only a release activation or a manual full flush expires it, never an upload. */
export const MEDIA_TAG = "media";
/** Chunks of the public media read. An upload of list art still expires every chunk. */
export const COURSE_LIST_MEDIA_TAG = "media:courses";
/** One course's course and lesson assets (course and lesson pages). */
export const courseMediaTag = (courseId: string) => `media:course:${courseId}`;

export const subareaMediaTag = (id: string) => `media:subarea:${id}`;
export const areaMediaTag = (id: string) => `media:area:${id}`;

export interface MediaInvalidation {
  readonly tags: readonly string[];
  /** Static pages purged by path as well (the tag alone did not refresh a prerendered page on the previous host, ADR-16). */
  readonly paths: readonly string[];
}
export const NOTHING: MediaInvalidation = { tags: [], paths: [] };

/**
 * What a media change (upload, rollback, delete) expires (ADR-16/17, docs/media/README.md):
 * - a course outside the active release: nothing; no page shows it, and activating a release expires every media read;
 * - a lesson asset of a published course: that course's lesson covers (`media:course:<id>`) only;
 * - a course asset of a published course (default poster and hero kinds shown by cards/rails): the course-list read (only the kinds actually shown by lists).
 */
export function mediaInvalidation(change: { readonly owner: MediaOwner; readonly courseId: string; readonly published: boolean; readonly kind?: string; readonly variant?: string }): MediaInvalidation {
  if (!change.published) return NOTHING;
  if (change.owner === "lesson" || (change.variant ?? "default") !== "default" || !["poster_9x16", "hero_desktop_16x9", "hero_present", "hero_mobile_9x16"].includes(change.kind ?? "")) return { tags: [courseMediaTag(change.courseId)], paths: [] };
  return { tags: [courseMediaTag(change.courseId), COURSE_LIST_MEDIA_TAG], paths: [] };
}

/** An area cover expires its descriptor and the courses that may inherit it (D-015). */
export function areaInvalidation(id: string, courses: readonly { readonly courseId: string; readonly published: boolean }[], kind: string, variant = "default"): MediaInvalidation {
  const published = courses.filter((course) => course.published);
  const tags = [areaMediaTag(id), ...published.map((course) => courseMediaTag(course.courseId))];
  if (published.length && variant === "default" && kind !== "lesson_default") tags.push(COURSE_LIST_MEDIA_TAG);
  return { tags: [...new Set(tags)], paths: [] };
}

/** A shared cover expires its own descriptor and only the courses/lists that may display it. */
export function subareaInvalidation(id: string, courses: readonly { readonly courseId: string; readonly published: boolean }[], kind: string, variant = "default"): MediaInvalidation {
  const published = courses.filter((course) => course.published);
  const tags = [subareaMediaTag(id), ...published.map((course) => courseMediaTag(course.courseId))];
  if (published.length && variant === "default" && kind !== "lesson_default") tags.push(COURSE_LIST_MEDIA_TAG);
  return { tags: [...new Set(tags)], paths: [] };
}
