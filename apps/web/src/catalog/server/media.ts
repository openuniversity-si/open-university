import "server-only";
import type { PublicCatalog } from "../domain/release.ts";
import { courseCoverAssets, lessonCoverAssets, ownerRefsForCourses } from "../domain/cover-read.ts";
import { coverOwner } from "../domain/cover-resolve.ts";
import type { MediaAsset } from "../../media/domain/types.ts";
import { readLessonAssets, readPublicOwnerAssets } from "./media-gateway.ts";
import { readPageCatalog } from "./page-reads.ts";

function entryOf(catalog: PublicCatalog) {
  return {
    courses: catalog.courses.map((course) => ({ id: course.id, areaId: course.areaId, subareaId: course.subareaId, coverFrom: course.coverFrom })),
    lessons: catalog.lessons.map((lesson) => ({ id: lesson.id, courseId: lesson.courseId })),
  };
}

/** Public read. Storage returns the declared owner's rows; `resolveCover` chooses the figure. */
export async function getCourseMedia(courseIds: readonly string[] | undefined, catalog?: PublicCatalog) {
  if (courseIds === undefined) throw new Error("courseIds are required");
  if (courseIds.length === 0) return new Map<string, readonly MediaAsset[]>();
  const entry = entryOf(catalog ?? await readPageCatalog({ kind: "release" }));
  const rows = await readPublicOwnerAssets(ownerRefsForCourses(entry.courses, courseIds));
  return courseCoverAssets(entry.courses, courseIds, rows);
}
export async function getLessonMedia(courseId: string, catalog?: PublicCatalog) {
  const entry = entryOf(catalog ?? await readPageCatalog({ kind: "release" }));
  const course = entry.courses.find((item) => item.id === courseId);
  const lessonIds = entry.lessons.filter((lesson) => lesson.courseId === courseId).map((lesson) => lesson.id);
  const declared = course?.coverFrom ? coverOwner(course.coverFrom, courseId) : undefined;
  const [lessons, inherited] = await Promise.all([
    readLessonAssets(courseId, lessonIds),
    declared ? readPublicOwnerAssets([{ owner: declared.kind, ownerId: declared.id }]) : Promise.resolve([]),
  ]);
  return lessonCoverAssets(entry.lessons, courseId, lessons, inherited.map((row) => row.asset), course?.coverFrom);
}
