import { hideLessonFailures } from "../domain/rules/lifecycle.ts";
import { unsharedVideoPairs } from "../domain/video-share.ts";
import type { Queryable } from "../../platform/db/uow.ts";
import { textIssues } from "../domain/fields.ts";
import type { LessonCreate, LessonOrder, LessonPart, LessonPatch, LessonPatchQuery } from "../domain/contracts.ts";
import { lockRow, touchCourse, type Outcome } from "./mutation.ts";
import { AppError, notFound, preconditionsFailed, stateConflict, unprocessable } from "../../kernel/errors.ts";
import type { HandlerContext } from "./http.ts";
import { cleanLessonSlug, cleanTitle } from "../domain/lesson-address.ts";
import { assertExists, assertPathFree, compactPositions, lessonPath, visibleLessons, writePositions } from "./common.ts";
import { changed } from "./courses.ts";
import { assertCourseEdition, editionRow } from "./editions.ts";
import { planSlugChange, type SlugPlan } from "../domain/lesson-slug.ts";
import { countLessonsInEdition, deleteRedirectsByFrom, insertLessonDisplayTitle, insertLessonRow, insertLessonVideo, restoreLessonPositions, retargetRedirectTo, selectCoursePresence, selectCourseSharedWith, selectCourseSlug, selectCourseStatus, selectEditionIds, selectLessonAddress, selectLessonCourseId, selectLessonIdsInEdition, selectLessonSlugClash, selectLessonSlugs, selectNextLessonPosition, selectRelatedRedirects, selectSharedVideoCourses, selectVideoOwnerRow, shiftLessonPositions, updateLessonColumns, upsertRedirect } from "./table-io.ts";

export function lessonView(row: Record<string, unknown>) {
  return {
    id: String(row.id), courseId: String(row.course_id), editionId: String(row.edition_id), part: String(row.part), slug: String(row.slug), position: Number(row.position), kind: String(row.kind),
    youtubeTitle: String(row.youtube_title), durationSeconds: Number(row.duration_seconds), visible: row.visible === true,
    licenseCode: (row.license_code ?? null) as string | null, attributionText: (row.attribution_text ?? null) as string | null, revision: Number(row.revision),
  };
}

/** The lesson of `courseId` that already holds this YouTube video. Another course may use it only when both declare the share (D-032). */
export async function videoOwner(db: Queryable, courseId: string, youtubeId: string): Promise<{ lessonId: string; courseId: string } | null> {
  const row = await selectVideoOwnerRow(db, youtubeId, courseId);
  return row ? { lessonId: String(row.lesson_id), courseId: String(row.course_id) } : null;
}
export function videoTaken(youtubeId: string, owner: { lessonId: string; courseId: string }): AppError {
  return stateConflict(`YouTube video ${youtubeId} already belongs to ${owner.lessonId} in ${owner.courseId}.`, { owner });
}

/** Opens a gap at `position` (1..N+1) with the transient-negative technique, so (edition_id, position) never collides. */
async function openGap(tx: Queryable, editionId: string, position: number): Promise<void> {
  await shiftLessonPositions(tx, editionId, position);
  await restoreLessonPositions(tx, editionId);
}

/** "Lab 3", "Recitation" or a Labs playlist: what the import suggests as the Labs part (ADR-21). */
export function looksLikeLab(...titles: readonly (string | null | undefined)[]): boolean {
  return titles.some((title) => typeof title === "string" && /\b(labs?|recitations?)\b/i.test(title));
}

export interface NewLesson {
  /** Stable id from a course bundle. Omitted imports and API creates keep the `lesson-N` sequence. */
  readonly id?: string;
  readonly courseId: string;
  readonly editionId: string;
  readonly part?: LessonPart;
  readonly youtubeId: string;
  readonly youtubeTitle: string;
  readonly durationSeconds: number;
  readonly slug?: string;
  readonly kind?: string;
  readonly displayTitle: { readonly text: string; readonly source: "manual" | "youtube"; readonly confidence: "high" | "medium" };
  readonly checkedAt: string;
  readonly checkedBy: string;
  readonly channelId?: string | null;
  readonly position?: number;
}

function shareList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

/** Another course already holds this video. The write stands only when both stored lists name the other course. */
async function assertDeclaredShare(tx: Queryable, courseId: string, youtubeId: string): Promise<void> {
  const rows = await selectSharedVideoCourses(tx, youtubeId, courseId);
  if (rows.length === 0) return;
  const mine = await selectCourseSharedWith(tx, courseId);
  const shares = new Map<string, readonly string[]>([[courseId, shareList(mine?.shared_with)]]);
  const uses = [{ courseId, youtubeId }];
  for (const row of rows) {
    const other = String(row.course_id);
    shares.set(other, shareList(row.shared_with));
    uses.push({ courseId: other, youtubeId });
  }
  const problem = unsharedVideoPairs(uses, shares, new Set([courseId]))[0];
  if (problem) throw stateConflict(`Video ${problem.youtubeId} is also in ${problem.otherCourseId}; both courses must declare the share.`);
}

/** Lesson + YouTube video (status ok) + displayTitle draft, inside the caller's transaction. Shared with imports. */
export async function insertLesson(tx: Queryable, lesson: NewLesson): Promise<ReturnType<typeof lessonView>> {
  const owner = await videoOwner(tx, lesson.courseId, lesson.youtubeId);
  if (owner) throw videoTaken(lesson.youtubeId, owner);
  await assertDeclaredShare(tx, lesson.courseId, lesson.youtubeId);
  const courseRow = await selectCourseSlug(tx, lesson.courseId);
  const courseSlug = typeof courseRow?.slug === "string" ? courseRow.slug : "";
  const existing = await selectLessonSlugs(tx, lesson.courseId);
  const taken = new Set(existing.map((row) => String(row.slug)));
  const inEdition = await countLessonsInEdition(tx, lesson.editionId);
  const count = Number(inEdition?.n ?? 0);
  const position = lesson.position ?? count + 1;
  if (position > count + 1) throw unprocessable(`position ${String(position)} is past the end (the edition has ${String(count)} lessons).`);
  let slug: string;
  if (lesson.slug !== undefined) {
    if (taken.has(lesson.slug)) throw new AppError("slug_taken", `The lesson slug ${lesson.slug} is taken in ${lesson.courseId}.`);
    slug = lesson.slug;
  } else {
    const place = await selectLessonAddress(tx, lesson.courseId, lesson.editionId);
    if (!place) throw unprocessable(`Course ${lesson.courseId} has no edition ${lesson.editionId}.`);
    const rawYear = place.edition_year;
    const year = typeof rawYear === "number" ? rawYear : typeof rawYear === "string" && rawYear !== "" ? Number(rawYear) : null;
    const text = (value: unknown): string => (typeof value === "string" ? value : "");
    slug = cleanLessonSlug({
      youtubeTitle: lesson.youtubeTitle,
      courseTitle: text(place.course_title),
      courseSlug: text(place.course_slug),
      institution: typeof place.institution === "string" ? place.institution : null,
      edition: {
        label: text(place.edition_label),
        term: typeof place.edition_term === "string" ? place.edition_term : null,
        year: year !== null && Number.isFinite(year) ? year : null,
      },
      position,
      kind: lesson.kind ?? ((lesson.part ?? "lectures") === "labs" ? "lab" : "lecture"),
    }, taken);
  }
  await assertPathFree(tx, lessonPath(courseSlug, slug));
  if (position <= count) await openGap(tx, lesson.editionId, position);
  const columns = ["course_id", "edition_id", "part", "slug", "position", "kind", "youtube_title", "duration_seconds"];
  const values: unknown[] = [lesson.courseId, lesson.editionId, lesson.part ?? "lectures", slug, position, lesson.kind ?? null, lesson.youtubeTitle, lesson.durationSeconds];
  if (lesson.id !== undefined) { columns.unshift("id"); values.unshift(lesson.id); }
  const created = lessonView(await insertLessonRow(tx, columns, values) ?? {});
  await insertLessonVideo(tx, created.id, lesson.youtubeId, lesson.channelId ?? null, lesson.checkedAt, lesson.checkedBy);
  await insertLessonDisplayTitle(tx, created.id, lesson.displayTitle.text, lesson.displayTitle.source, lesson.displayTitle.source === "youtube" ? `youtube:${lesson.youtubeId}` : "admin-api", lesson.displayTitle.confidence);
  return created;
}

export async function createLesson(context: HandlerContext<{ id: string }, unknown, LessonCreate>): Promise<Outcome> {
  const courseId = context.params.id;
  const body = context.body;
  const statusRow = await selectCourseStatus(context.db, courseId);
  if (!statusRow) throw notFound(`Course ${courseId}`);
  if (statusRow.status === "archived") throw stateConflict("An archived course takes no new lessons; move it to draft first.");
  await assertCourseEdition(context.db, courseId, body.editionId);
  if (body.displayTitle !== undefined) {
    const issues = textIssues("lesson", "displayTitle", body.displayTitle);
    if (issues.length > 0) throw unprocessable("displayTitle cannot fill its slot.", { issues });
  }
  // The video-owner check runs inside the transaction, after the idempotency key: checked here, a request racing its own
  // replay saw the first one's lesson and answered 409 instead of replaying it.
  // The embed check is network I/O: it runs before the transaction opens.
  const embed = await context.deps.oembed(body.youtubeId);
  if (embed.status !== "ok") throw unprocessable(`YouTube video ${body.youtubeId} is ${embed.status}.`, { status: embed.status });
  const youtubeTitle = embed.title?.trim() || body.youtubeId;
  return context.mutate(async (tx) => {
    const course = await lockRow(tx, "courses", courseId, `Course ${courseId}`);
    if (course.status === "archived") throw stateConflict("An archived course takes no new lessons; move it to draft first.");
    await assertCourseEdition(tx, courseId, body.editionId);
    const owner = await videoOwner(tx, courseId, body.youtubeId);
    if (owner) throw videoTaken(body.youtubeId, owner);
    const lesson = await insertLesson(tx, {
      courseId, editionId: body.editionId, ...(body.part === undefined ? {} : { part: body.part }), youtubeId: body.youtubeId, youtubeTitle, durationSeconds: body.durationSeconds, checkedAt: context.deps.now().toISOString(), checkedBy: context.deps.oembedChecker,
      displayTitle: body.displayTitle === undefined ? { text: cleanTitle(youtubeTitle), source: "youtube", confidence: "medium" } : { text: body.displayTitle, source: "manual", confidence: "high" },
      ...(body.slug === undefined ? {} : { slug: body.slug }), ...(body.kind === undefined ? {} : { kind: body.kind }), ...(body.position === undefined ? {} : { position: body.position }),
    });
    const courseRevision = await touchCourse(tx, courseId);
    await tx.audit({ action: "lesson.create", entityKind: "lesson", entityId: lesson.id, after: { ...lesson, youtubeId: body.youtubeId, courseRevision } });
    return { status: 201, data: { lesson, youtubeId: body.youtubeId, courseRevision }, entity: `lesson:${lesson.id}` };
  });
}

/** Full, atomic reorder inside one edition: `lessonIds` must be exactly its lessons; positions become 1..N in that order. */
async function reorderEdition(context: HandlerContext<unknown, unknown, LessonOrder>, courseId: string, editionId: string): Promise<Outcome> {
  const { lessonIds, expectedRevision } = context.body;
  return context.mutate(async (tx) => {
    await lockRow(tx, "courses", courseId, `Course ${courseId}`, expectedRevision);
    const rows = await selectLessonIdsInEdition(tx, editionId);
    const current = rows.map((row) => String(row.id));
    const known = new Set(current);
    const seen = new Set<string>();
    const duplicated = [...new Set(lessonIds.filter((id) => (seen.has(id) ? true : (seen.add(id), false))))];
    const missing = current.filter((id) => !seen.has(id));
    const unknown = [...seen].filter((id) => !known.has(id));
    if (missing.length + unknown.length + duplicated.length > 0) throw unprocessable("lessonIds must list every lesson of the edition exactly once.", { missing, unknown, duplicated });
    if (current.every((id, index) => lessonIds[index] === id)) return { data: { editionId, lessonIds: current, revision: expectedRevision, noop: true }, noop: true, entity: `edition:${editionId}` };
    await writePositions(tx, editionId, lessonIds);
    const revision = await touchCourse(tx, courseId);
    await tx.audit({ action: "lesson.reorder", entityKind: "edition", entityId: editionId, before: { lessonIds: current }, after: { lessonIds, courseId } });
    return { data: { editionId, lessonIds, revision }, entity: `edition:${editionId}` };
  });
}

/** PUT /editions/:id/lessons/order; `expectedRevision` is the course's (lesson and edition changes bump it). */
export async function reorderEditionLessons(context: HandlerContext<{ id: string }, unknown, LessonOrder>): Promise<Outcome> {
  const edition = await editionRow(context.db, context.params.id);
  return reorderEdition(context, String(edition.course_id), context.params.id);
}

/** PUT /courses/:id/lessons/order (P4): still valid for a course with one edition; with more, the order is per edition. */
export async function reorderLessons(context: HandlerContext<{ id: string }, unknown, LessonOrder>): Promise<Outcome> {
  const courseId = context.params.id;
  const course = await selectCoursePresence(context.db, courseId);
  if (!course) throw notFound(`Course ${courseId}`);
  const rows = await selectEditionIds(context.db, courseId);
  if (rows.length !== 1) {
    throw stateConflict(`Course ${courseId} has ${String(rows.length)} editions: reorder each one with PUT /editions/:id/lessons/order.`, { editionIds: rows.map((row) => String(row.id)) });
  }
  return reorderEdition(context, courseId, String(rows[0]?.id));
}

/**
 * PATCH /lessons/:id. A slug change, in the same transaction, redirects the old path to the new one, flattens the chains
 * into the old path and drops the redirect from the new path when it goes back to an earlier slug (planSlugChange); it
 * reaches the site with the next release, which carries the redirects (308). `?dryRun=true` answers the same report
 * without writing.
 */
export async function patchLesson(context: HandlerContext<{ id: string }, LessonPatchQuery, LessonPatch>): Promise<Outcome> {
  const { id } = context.params;
  const body = context.body;
  const lessonRow = await selectLessonCourseId(context.db, id);
  if (!lessonRow) throw notFound(`Lesson ${id}`);
  const courseId = String(lessonRow.course_id);
  // Every read and check; the dry-run stops here (outside a transaction, so its row locks end with each statement).
  const prepare = async (tx: Queryable) => {
    const course = await lockRow(tx, "courses", courseId, `Course ${courseId}`);
    const locked = await lockRow(tx, "lessons", id, `Lesson ${id}`, body.expectedRevision);
    const before = lessonView(locked);
    const next: Record<string, unknown> = {};
    const columns = { slug: "slug", kind: "kind", visible: "visible", licenseCode: "license_code", attributionText: "attribution_text", editionId: "edition_id", part: "part" } as const;
    for (const [field, column] of Object.entries(columns)) {
      const value = body[field as keyof typeof columns];
      if (value !== undefined && JSON.stringify(value) !== JSON.stringify(locked[column] ?? null)) next[column] = value;
    }
    if (typeof next.license_code === "string") await assertExists(tx, "licenses", next.license_code, "license");
    if (typeof next.edition_id === "string") {
      // Moving to another edition: the lesson goes last there, and both editions stay 1..N.
      await assertCourseEdition(tx, courseId, next.edition_id);
      const target = await selectNextLessonPosition(tx, next.edition_id);
      next.position = Number(target?.next ?? 1);
    }
    if (next.visible === false && course.status === "published" && before.visible) {
      const failed = hideLessonFailures(courseId, true, await visibleLessons(tx, courseId));
      if (failed.length > 0) throw preconditionsFailed(failed);
    }
    let slugPlan: SlugPlan | null = null;
    if (typeof next.slug === "string") {
      const clash = await selectLessonSlugClash(tx, courseId, next.slug, id);
      if (clash) throw new AppError("slug_taken", `The lesson slug ${next.slug} is taken in ${courseId}.`, { lessonId: clash.id });
      const oldPath = lessonPath(String(course.slug), before.slug);
      const newPath = lessonPath(String(course.slug), next.slug);
      const related = await selectRelatedRedirects(tx, newPath, oldPath);
      slugPlan = planSlugChange(related.map((row) => ({ from: String(row.from_path), to: String(row.to_path) })), oldPath, newPath);
    }
    return { before, next, slugPlan };
  };
  const changes = (before: Record<string, unknown>, next: Record<string, unknown>) => Object.fromEntries(Object.entries(columnsOf(next)).map(([field, value]) => [field, { before: before[field], after: value }]));
  if (context.query.dryRun === true) {
    const { before, next, slugPlan } = await prepare(context.db);
    return { data: { dryRun: true, lesson: before, changes: changes(before, next), redirects: slugPlan, noop: Object.keys(next).length === 0 } };
  }
  return context.mutate(async (tx) => {
    const { before, next, slugPlan } = await prepare(tx);
    if (Object.keys(next).length === 0) return { data: { lesson: before, noop: true }, noop: true, entity: `lesson:${id}` };
    if (slugPlan) {
      const removed = slugPlan.removed.map((redirect) => redirect.from);
      if (removed.length > 0) await deleteRedirectsByFrom(tx, removed);
      await retargetRedirectTo(tx, slugPlan.created.from, slugPlan.created.to);
      await upsertRedirect(tx, slugPlan.created.from, slugPlan.created.to);
    }
    const names = Object.keys(next);
    const updated = await updateLessonColumns(tx, id, names, names.map((column) => next[column]));
    const after = lessonView(updated ?? {});
    if (after.editionId !== before.editionId) await compactPositions(tx, before.editionId);
    const courseRevision = await touchCourse(tx, courseId);
    if (slugPlan) {
      await tx.audit({ action: "lesson.slug", entityKind: "lesson", entityId: id, before: { slug: before.slug, path: slugPlan.created.from }, after: { slug: after.slug, path: slugPlan.created.to, redirects: slugPlan, courseRevision } });
    }
    const rest = changed({ ...before, slug: after.slug }, after);
    if (Object.keys(rest.after).length > 0) await tx.audit({ action: "lesson.update", entityKind: "lesson", entityId: id, ...rest });
    return { data: { lesson: after, courseRevision, ...(slugPlan ? { redirects: slugPlan } : {}) }, entity: `lesson:${id}` };
  });
}

/** The PATCH columns back as LessonView fields (edition moves also set position). */
function columnsOf(next: Record<string, unknown>): Record<string, unknown> {
  const fields: Record<string, string> = { slug: "slug", kind: "kind", visible: "visible", license_code: "licenseCode", attribution_text: "attributionText", edition_id: "editionId", part: "part", position: "position" };
  return Object.fromEntries(Object.entries(next).map(([column, value]) => [fields[column] ?? column, value]));
}
