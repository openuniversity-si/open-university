import { courseDeleteBlockers, editionDeleteBlockers, lessonDeleteBlockers } from "../domain/rules/lifecycle.ts";
import type { RuleBlocker } from "../domain/rules/registry.ts";
import type { Queryable } from "../../platform/db/uow.ts";
import { countPending, deleteOwnedMedia, drainPendingObjects as drainQueued, heldForRetention, lockMediaOwners, ownedMedia, pendingKeys, queuePending, usedMediaKeys, type OwnedMediaRow } from "./media-gateway.ts";
import { countLessonProgress } from "../../progress/server/maintenance.ts";
import type { MediaObjectStore } from "../../media/ports/storage.ts";
import { mediaInvalidation } from "../../media/domain/tags.ts";
import type { CourseDeleteQuery, EditionDeleteQuery, MediaReferencesBody } from "../domain/contracts.ts";
import { lockRow, touchCourse, type Outcome, type Tx } from "./mutation.ts";
import { AppError, invalid, notFound, preconditionsFailed, stateConflict } from "../../kernel/errors.ts";
import type { HandlerContext } from "./http.ts";
import { addRedirect, compactPositions, coursePath, iso, lessonPath, redirectsInto } from "./common.ts";
import { courseView, unpublishInTx } from "./courses.ts";
import { editionView, writeEditionPositions } from "./editions.ts";
import { scheduleActivation, type Publication } from "./releases.ts";
import { archiveCourseRow, countCourseAndLessonTexts, countCourseEditions, countHomeItemsForCourse, countLessonTexts, countOtherVisibleLessons, countTextsForLessons, countVideosForLessons, countVisibleLessonsOutsideEdition, deleteCourseAndLessonTextRows, deleteCourseById, deleteEditionById, deleteEditionsByCourse, deleteHomeItemsForCourse, deleteLessonById, deleteLessonTextRows, deleteLessonsByCourse, deleteLessonsByEdition, deleteRedirectsUnder, deleteTextsForLessonIds, deleteVideoForLesson, deleteVideosForLessons, selectCatalogCoverReferences, selectCoursePurgeOwners, selectCourseRow, selectCourseSlugStatus, selectEditionIds, selectEditionLessonRows, selectEditionRow, selectLessonIdsByCourse, selectLessonIdsOfCourse, selectLessonRow } from "./table-io.ts";

type Blocker = RuleBlocker;

/**
 * R2 keys of these rows no other row of THIS database uses. The bucket is shared with the other environment, which this
 * server cannot see, so they are only candidates: the caller checks them there (POST /media/references on the other
 * target, as `tower-catalog … --delete-bytes` does) and asks for `deleteBytes`.
 */
function candidateKeys(media: { rows: readonly OwnedMediaRow[]; shared: ReadonlySet<string> }): string[] {
  return [...new Set(media.rows.map((row) => row.pathname))].filter((key) => !media.shared.has(key)).sort();
}
/** The keys this request deletes: none unless `deleteBytes` (the default keeps every byte, docs/catalog/cli.md). */
function deletableKeys(media: { rows: readonly OwnedMediaRow[]; shared: ReadonlySet<string> }, deleteBytes: boolean, checkedKeys: readonly string[] = []): string[] {
  return deleteBytes ? candidateKeys(media).filter((key) => checkedKeys.includes(key)) : [];
}

/**
 * After a commit: deletes the queued R2 keys (idempotent per key), dropping each from r2_pending_deletions once gone.
 * A failed key stays queued with its attempt count and a secret-free error; re-running the same DELETE finishes it.
 */
export async function drainPendingObjects(db: Queryable, store: () => MediaObjectStore, filter: { courseId: string } | { lessonId: string }, checkedKeys: readonly string[] = []): Promise<{ deleted: string[]; pending: string[] }> {
  const referenced = new Set(await usedKeys(db, checkedKeys));
  return drainQueued(db, store, filter, checkedKeys, referenced);
}

/** 502 after a committed purge whose bytes could not all be removed; the DELETE can simply be re-run. */
function r2Failure(bytes: { deleted: string[]; pending: string[] }): AppError {
  return new AppError("upstream_failed", `R2 kept ${String(bytes.pending.length)} object(s); the rows are gone. Re-run the same DELETE to finish.`, { committed: true, deletedKeys: bytes.deleted, pendingKeys: bytes.pending });
}

async function finishBytes(context: HandlerContext<unknown, { deleteBytes?: boolean; checkedKeys?: string[] }, unknown>, filter: { courseId: string } | { lessonId: string }, entity: { kind: string; id: string; action: string }, rerun: boolean) {
  const bytes = await drainPendingObjects(context.db, context.deps.store, filter, context.query.deleteBytes === true ? context.query.checkedKeys ?? [] : []);
  if (rerun || bytes.pending.length > 0) {
    await context.mutate(async (tx) => {
      await tx.audit({ action: entity.action, entityKind: entity.kind, entityId: entity.id, after: { r2Completed: bytes.deleted, r2Pending: bytes.pending } });
      return { data: null };
    });
  }
  if (bytes.pending.length > 0 && !await heldForRetention(context.db, bytes.pending)) throw r2Failure(bytes);
  return bytes;
}

/** Deleted lesson covers expire their course's cached read only when the course is published (src/media/domain/tags.ts). */
function invalidateLessonMedia(context: HandlerContext<unknown, unknown, unknown>, courseId: string, published: boolean) {
  const plan = mediaInvalidation({ owner: "lesson", courseId, published });
  if (plan.tags.length) context.deps.invalidateMedia(plan);
}

// ---- POST /media/references ----

/** Which of `keys` a media row of this database uses (any version, active or not): R2 bytes another environment needs stay. */
async function catalogCoverReferences(db: Queryable, keys: readonly string[]): Promise<string[]> {
  return selectCatalogCoverReferences(db, keys);
}
async function usedKeys(db: Queryable, keys: readonly string[]): Promise<string[]> {
  return [...new Set([...(await usedMediaKeys(db, keys)), ...(await catalogCoverReferences(db, keys))])].sort();
}
export async function mediaReferences(context: HandlerContext<unknown, unknown, MediaReferencesBody>): Promise<Outcome> {
  return { data: { used: await usedKeys(context.db, context.body.keys) } };
}

// ---- DELETE /courses/:id?mode=archive|purge ----

async function courseReport(db: Queryable, course: Record<string, unknown>, query: CourseDeleteQuery) {
  const id = String(course.id);
  const lessons = (await selectLessonIdsByCourse(db, id)).map((row) => String(row.id));
  const media = await ownedMedia(db, { courses: [id], lessons });
  const status = String(course.status);
  const blockedBy: Blocker[] = courseDeleteBlockers({ mode: query.mode, status, publishedBefore: course.published_at !== null, featured: course.featured === true, replacementGiven: query.replacementFeaturedId !== undefined });
  return {
    mode: query.mode,
    course: { id, slug: String(course.slug), status, publishedAt: iso(course.published_at), featured: course.featured === true, revision: Number(course.revision) },
    editions: await countCourseEditions(db, id),
    lessons: lessons.length,
    videos: await countVideosForLessons(db, lessons),
    texts: await countCourseAndLessonTexts(db, id, lessons),
    homeRowItems: await countHomeItemsForCourse(db, id),
    coverAssets: media.rows.filter((row) => row.owner === "course").length,
    lessonAssets: media.rows.filter((row) => row.owner === "lesson").length,
    r2Candidates: query.mode === "purge" ? candidateKeys(media) : [],
    r2Objects: query.mode === "purge" ? deletableKeys(media, query.deleteBytes === true, query.checkedKeys) : [],
    keptBytes: query.mode === "purge" ? [...new Set(media.rows.map((row) => row.pathname))].filter((key) => query.deleteBytes !== true || !query.checkedKeys?.includes(key) || media.shared.has(key)).sort() : [],
    lessonProgressRows: await countLessonProgress(db, lessons),
    redirects: await redirectsInto(db, String(course.slug)),
    blockedBy,
  };
}

export async function deleteCourse(context: HandlerContext<{ id: string }, CourseDeleteQuery, unknown>): Promise<Outcome> {
  const { id } = context.params;
  const query = context.query;
  const course = await selectCourseRow(context.db, id);
  if (!course) {
    // A purge that committed but left R2 objects is finished by re-running it.
    const pending = await countPending(context.db, { courseId: id });
    if (query.mode !== "purge" || pending === 0) throw notFound(`Course ${id}`);
    if (query.confirm !== true) return { data: { dryRun: true, alreadyPurged: true, r2Pending: pending, report: { r2Candidates: await pendingKeys(context.db, { courseId: id }) } } };
    const bytes = await finishBytes(context, { courseId: id }, { kind: "course", id, action: "course.delete.purge" }, true);
    return { data: { dryRun: false, purged: true, alreadyPurged: true, bytes }, entity: `course:${id}` };
  }
  const report = await courseReport(context.db, course, query);
  if (query.confirm !== true) return { data: { dryRun: true, report } };
  if (query.expectedRevision === undefined) throw invalid("confirm=true needs expectedRevision.");
  const expectedRevision = query.expectedRevision;
  return query.mode === "archive" ? archiveCourse(context, id, expectedRevision) : purgeCourse(context, id, expectedRevision);
}

async function archiveCourse(context: HandlerContext<{ id: string }, CourseDeleteQuery, unknown>, id: string, expectedRevision: number): Promise<Outcome> {
  let publication: Publication | null = null;
  const outcome = await context.mutate(async (tx) => {
    await lockMediaOwners(tx, [{ owner: "course", ownerId: id }]);
    const locked = await lockRow(tx, "courses", id, `Course ${id}`, expectedRevision);
    if (locked.status === "archived") return { data: { dryRun: false, archived: true, noop: true }, noop: true, entity: `course:${id}` };
    if (locked.status === "published") {
      const { replacementFeaturedId } = context.query;
      publication = await unpublishInTx(tx, context, id, { expectedRevision, to: "archived", note: context.query.note ?? `Archive ${id}`, action: "course.delete.archive", ...(replacementFeaturedId === undefined ? {} : { replacementFeaturedId }) });
      scheduleActivation(tx, context.deps, publication.release, publication.release.created);
      return { data: { dryRun: false, archived: true, release: publication.release, diff: publication.diff }, entity: `course:${id}` };
    }
    const row = await archiveCourseRow(tx, id);
    await tx.audit({ action: "course.delete.archive", entityKind: "course", entityId: id, before: { status: locked.status }, after: { status: "archived" } });
    return { data: { dryRun: false, archived: true, course: courseView(row ?? {}) }, entity: `course:${id}` };
  });
  return outcome;
}

/**
 * Purge, in one transaction and in FK order: Home items, texts (course and lessons), asset rows (media repository; 0008
 * makes them RESTRICT their course and lessons), videos, lessons, redirects into the course, the course. catalog_imports.course_id becomes NULL by its FK; lesson_progress is
 * never touched. R2 bytes are queued in the transaction and deleted after the commit.
 */
async function purgeCourse(context: HandlerContext<{ id: string }, CourseDeleteQuery, unknown>, id: string, expectedRevision: number): Promise<Outcome> {
  const deleteBytes = context.query.deleteBytes === true;
  let summary: Record<string, unknown> = {};
  await context.mutate(async (tx) => {
    const preview = await selectCoursePurgeOwners(tx, id);
    const subareaId = preview.find((row) => typeof row.subarea_id === "string")?.subarea_id;
    const lessonIds = preview.flatMap((row) => typeof row.lesson_id === "string" ? [row.lesson_id] : []);
    await lockMediaOwners(tx, [
      { owner: "course", ownerId: id },
      ...(typeof subareaId === "string" ? [{ owner: "subarea" as const, ownerId: subareaId }] : []),
      ...lessonIds.map((lessonId) => ({ owner: "lesson" as const, ownerId: lessonId })),
    ]);
    const locked = await lockRow(tx, "courses", id, `Course ${id}`, expectedRevision);
    const lessons = (await selectLessonIdsOfCourse(tx, id)).map((row) => String(row.id));
    if (lessons.some((lessonId) => !lessonIds.includes(lessonId))) throw stateConflict("Media owners changed; retry the deletion.");
    const report = await courseReport(tx, locked, context.query);
    if (report.blockedBy.length > 0) throw stateConflict(report.blockedBy.map((blocker) => blocker.message).join(" "), { blockedBy: report.blockedBy });
    const media = await ownedMedia(tx, { courses: [id], lessons });
    await deleteHomeItemsForCourse(tx, id);
    await deleteCourseAndLessonTextRows(tx, id, lessons);
    await deleteOwnedMedia(tx, media.rows);
    await deleteVideosForLessons(tx, lessons);
    await deleteLessonsByCourse(tx, id);
    await deleteEditionsByCourse(tx, id);
    await deleteRedirectsUnder(tx, coursePath(String(locked.slug)));
    const keys = deletableKeys(media, deleteBytes, context.query.checkedKeys);
    await queuePending(tx, keys, media.rows, id, context.requestId);
    await deleteCourseById(tx, id);
    const counts = { course: report.course, editions: report.editions, lessons: report.lessons, videos: report.videos, texts: report.texts, homeRowItems: report.homeRowItems, coverAssets: report.coverAssets,
      lessonAssets: report.lessonAssets, lessonProgressRows: report.lessonProgressRows, redirects: report.redirects };
    const keptBytes = report.keptBytes;
    summary = counts;
    await tx.audit({ action: "course.delete.purge", entityKind: "course", entityId: id, before: counts, after: { purged: true, r2Pending: keys, keptBytes } });
    return { data: null };
  });
  // A purged course was never in the active release (archived first), so no page shows its media: nothing to expire.
  const bytes = await finishBytes(context, { courseId: id }, { kind: "course", id, action: "course.delete.purge" }, false);
  return { data: { dryRun: false, purged: true, report: summary, bytes }, entity: `course:${id}` };
}

// ---- DELETE /lessons/:id ----

async function lessonReport(db: Queryable, lesson: Record<string, unknown>, deleteBytes: boolean, checkedKeys?: readonly string[]) {
  const id = String(lesson.id);
  const course = await selectCourseSlugStatus(db, String(lesson.course_id)) ?? {};
  const published = course.status === "published";
  const visible = lesson.visible === true;
  const media = await ownedMedia(db, { courses: [], lessons: [id] });
  const others = await countOtherVisibleLessons(db, String(lesson.course_id), id);
  const blockedBy: Blocker[] = lessonDeleteBlockers({ published, visible, otherVisible: others });
  return {
    lesson: { id, slug: String(lesson.slug), courseId: String(lesson.course_id), position: Number(lesson.position), visible, revision: Number(lesson.revision) },
    coursePublished: published,
    recommendation: published ? "The course is published: PATCH {visible:false} hides the lesson and keeps it; delete only with confirm=true." : null,
    texts: await countLessonTexts(db, id),
    lessonAssets: media.rows.length,
    r2Candidates: candidateKeys(media),
    r2Objects: deletableKeys(media, deleteBytes, checkedKeys),
    lessonProgressRows: await countLessonProgress(db, [id]),
    redirect: published && visible ? { from: lessonPath(String(course.slug), String(lesson.slug)), to: coursePath(String(course.slug)) } : null,
    blockedBy,
  };
}

export async function deleteLesson(context: HandlerContext<{ id: string }, { confirm?: boolean; expectedRevision?: number; deleteBytes?: boolean; checkedKeys?: string[] }, unknown>): Promise<Outcome> {
  const { id } = context.params;
  const deleteBytes = context.query.deleteBytes === true;
  const lesson = await selectLessonRow(context.db, id);
  if (!lesson) {
    const pending = await countPending(context.db, { lessonId: id });
    if (pending === 0) throw notFound(`Lesson ${id}`);
    if (context.query.confirm !== true) return { data: { dryRun: true, alreadyDeleted: true, r2Pending: pending } };
    const bytes = await finishBytes(context, { lessonId: id }, { kind: "lesson", id, action: "lesson.delete" }, true);
    return { data: { dryRun: false, deleted: true, alreadyDeleted: true, bytes }, entity: `lesson:${id}` };
  }
  if (context.query.confirm !== true) return { data: { dryRun: true, report: await lessonReport(context.db, lesson, deleteBytes, context.query.checkedKeys) } };
  const expectedRevision = context.query.expectedRevision;
  if (expectedRevision === undefined) throw invalid("confirm=true needs expectedRevision.");
  const courseId = String(lesson.course_id);
  let summary: Record<string, unknown> = {};
  await context.mutate(async (tx: Tx) => {
    await lockMediaOwners(tx, [{ owner: "course", ownerId: courseId }, { owner: "lesson", ownerId: id }]);
    await lockRow(tx, "courses", courseId, `Course ${courseId}`);
    const locked = await lockRow(tx, "lessons", id, `Lesson ${id}`, expectedRevision);
    const report = await lessonReport(tx, locked, deleteBytes, context.query.checkedKeys);
    if (report.blockedBy.length > 0) throw preconditionsFailed(report.blockedBy.map((blocker) => ({ rule: blocker.rule, entity: `course:${courseId}`, message: blocker.message })));
    const media = await ownedMedia(tx, { courses: [], lessons: [id] });
    await deleteLessonTextRows(tx, id);
    await deleteOwnedMedia(tx, media.rows);
    await deleteVideoForLesson(tx, id);
    await deleteLessonById(tx, id);
    await compactPositions(tx, String(locked.edition_id));
    if (report.redirect) await addRedirect(tx, report.redirect.from, report.redirect.to);
    const keys = deletableKeys(media, deleteBytes, context.query.checkedKeys);
    await queuePending(tx, keys, media.rows, courseId, context.requestId);
    const courseRevision = await touchCourse(tx, courseId);
    const counts = { lesson: report.lesson, coursePublished: report.coursePublished, texts: report.texts, lessonAssets: report.lessonAssets, lessonProgressRows: report.lessonProgressRows, redirect: report.redirect };
    summary = { ...counts, courseRevision };
    await tx.audit({ action: "lesson.delete", entityKind: "lesson", entityId: id, before: counts, after: { deleted: true, r2Pending: keys, courseRevision } });
    return { data: null };
  });
  invalidateLessonMedia(context, courseId, summary.coursePublished === true);
  const bytes = await finishBytes(context, { lessonId: id }, { kind: "lesson", id, action: "lesson.delete" }, false);
  return { data: { dryRun: false, deleted: true, report: summary, bytes }, entity: `lesson:${id}` };
}


// ---- DELETE /editions/:id (ADR-21) ----

/**
 * What deleting an edition does. An empty edition just goes; one with lessons only with `mode=with-lessons`, which applies
 * the lesson deletion of DELETE /lessons/:id to each (progress kept, redirects to the course page, R2 after the commit).
 * The last edition of a course never goes (409 has_dependents), nor the last visible lessons of a published course (412).
 */
async function editionReport(db: Queryable, edition: Record<string, unknown>, query: EditionDeleteQuery) {
  const id = String(edition.id);
  const courseId = String(edition.course_id);
  const course = await selectCourseSlugStatus(db, courseId) ?? {};
  const published = course.status === "published";
  const rows = await selectEditionLessonRows(db, id);
  const lessons = rows.map((row) => ({ id: String(row.id), slug: String(row.slug), visible: row.visible === true }));
  const ids = lessons.map((lesson) => lesson.id);
  const media = await ownedMedia(db, { courses: [], lessons: ids });
  const editions = await countCourseEditions(db, courseId);
  const visibleElsewhere = await countVisibleLessonsOutsideEdition(db, courseId, id);
  const blockedBy: Blocker[] = editionDeleteBlockers({ editions, lessons: lessons.length, withLessons: query.mode === "with-lessons", published, visibleHere: lessons.some((lesson) => lesson.visible), visibleElsewhere });
  const redirects = published ? lessons.filter((lesson) => lesson.visible).map((lesson) => ({ from: lessonPath(String(course.slug), lesson.slug), to: coursePath(String(course.slug)) })) : [];
  return {
    edition: editionView(edition), mode: query.mode ?? "empty", coursePublished: published, lessons,
    texts: await countTextsForLessons(db, ids),
    lessonAssets: media.rows.length,
    r2Candidates: candidateKeys(media),
    r2Objects: deletableKeys(media, query.deleteBytes === true, query.checkedKeys),
    lessonProgressRows: await countLessonProgress(db, ids),
    redirects,
    blockedBy,
  };
}

export async function deleteEdition(context: HandlerContext<{ id: string }, EditionDeleteQuery, unknown>): Promise<Outcome> {
  const { id } = context.params;
  const query = context.query;
  const edition = await selectEditionRow(context.db, id);
  if (!edition) throw notFound(`Edition ${id}`);
  if (query.confirm !== true) return { data: { dryRun: true, report: await editionReport(context.db, edition, query) } };
  const expectedRevision = query.expectedRevision;
  if (expectedRevision === undefined) throw invalid("confirm=true needs expectedRevision (the edition's).");
  const courseId = String(edition.course_id);
  let summary: Record<string, unknown> = {};
  await context.mutate(async (tx: Tx) => {
    await lockRow(tx, "courses", courseId, `Course ${courseId}`);
    const locked = await lockRow(tx, "course_editions", id, `Edition ${id}`, expectedRevision);
    const report = await editionReport(tx, locked, query);
    const dependents = report.blockedBy.filter((blocker) => blocker.rule === "has_dependents");
    if (dependents.length > 0) throw new AppError("has_dependents", dependents.map((blocker) => blocker.message).join(" "), { blockedBy: dependents });
    if (report.blockedBy.length > 0) throw preconditionsFailed(report.blockedBy.map((blocker) => ({ rule: blocker.rule, entity: `edition:${id}`, message: blocker.message })));
    const ids = report.lessons.map((lesson) => lesson.id);
    const media = await ownedMedia(tx, { courses: [], lessons: ids });
    await deleteTextsForLessonIds(tx, ids);
    await deleteOwnedMedia(tx, media.rows);
    await deleteVideosForLessons(tx, ids);
    await deleteLessonsByEdition(tx, id);
    await deleteEditionById(tx, id);
    const remaining = (await selectEditionIds(tx, courseId)).map((row) => String(row.id));
    await writeEditionPositions(tx, courseId, remaining);
    for (const redirect of report.redirects) await addRedirect(tx, redirect.from, redirect.to);
    const keys = deletableKeys(media, query.deleteBytes === true, query.checkedKeys);
    await queuePending(tx, keys, media.rows, courseId, context.requestId);
    const courseRevision = await touchCourse(tx, courseId);
    const counts = { edition: report.edition, coursePublished: report.coursePublished, lessons: ids, texts: report.texts, lessonAssets: report.lessonAssets, lessonProgressRows: report.lessonProgressRows, redirects: report.redirects };
    summary = { ...counts, editions: remaining, courseRevision };
    await tx.audit({ action: "edition.delete", entityKind: "edition", entityId: id, before: counts, after: { deleted: true, editions: remaining, r2Pending: keys, courseRevision } });
    return { data: null };
  });
  invalidateLessonMedia(context, courseId, summary.coursePublished === true);
  const bytes = await finishBytes(context, { courseId }, { kind: "edition", id, action: "edition.delete" }, false);
  return { data: { dryRun: false, deleted: true, report: summary, bytes }, entity: `edition:${id}` };
}
